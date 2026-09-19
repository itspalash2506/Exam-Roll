import asyncio
import json
import logging
import traceback

from sqlalchemy import select

from app.models.db_models import (
    Enrollment,
    ExtractedData,
    Job,
    Organization,
    Student,
    SubjectOffering,
)
from app.schemas.schemas import (
    StudentRecord,
    StudentStatus,
    SubjectConflict,
    SubjectEntry,
)
from app.services.ai.classifier import classify_document
from app.services.ai.extractor import extract_students_ai, validate_extraction
from app.services import storage
from app.utils.file_utils import detect_file_type, validate_size_bytes
from app.utils.roll_sort import roll_sort_key
from app.utils.subject_utils import sort_subjects
from app.websocket_manager import manager

logger = logging.getLogger(__name__)

# When a batch contains the same (roll_number, subject_code) pair more than
# once — the same student listed for the same subject in two files, or twice
# in one file — keep it ONCE in the final data. Flip to False to keep every
# occurrence verbatim (duplicates will then be flagged by validate_extraction
# instead of merged).
DEDUPE_ACROSS_FILES = True

# ── Stage definitions ─────────────────────────────────────────────────────────
# Every stage below corresponds to a real, distinct unit of work the pipeline
# actually performs. Order matters: it drives the overall percent shown in the
# thin top bar (stages_completed / total_stages), not a hand-tuned schedule.

STAGE_IDS = [
    "validating",
    "reading_document",
    "extracting_rolls",
    "detecting_subjects",
    "deduplicating",
    "ai_analysis",
    "matching",
    "validating_data",
    "saving",
    "persisting_rows",
]

STAGE_LABELS = {
    "validating": "Validating files",
    "reading_document": "Reading documents",
    "extracting_rolls": "Extracting roll numbers",
    "detecting_subjects": "Detecting subjects",
    "deduplicating": "Merging duplicates",
    "ai_analysis": "AI identifying document type",
    "matching": "Matching AI labels to codes",
    "validating_data": "Validating records",
    "saving": "Saving results",
    "persisting_rows": "Updating student & subject records",
}


def _humanize_doc_type(doc_type: str) -> str:
    words = doc_type.replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else "Unknown"


# ── Pure aggregation helpers (unit-testable, no side effects) ─────────────────

def merge_subject_maps(
    maps: list[dict[str, str]],
) -> tuple[dict[str, str], list[str], list[SubjectConflict]]:
    """Merge per-file {code: name} maps into one unified map.

    Later files fill in names missing from earlier files. If two files disagree
    on a subject's name that is a **conflict** (FUTURE.md §14.4): neither name is
    chosen, the code is left unnamed, and a SubjectConflict is recorded for the
    review step to resolve.

    The previous rule picked the longer name automatically, which silently
    renamed subjects in the delivered workbook — "OS" and "Operating Systems"
    are a safe guess, but "Paper I" and "Paper II" are not, and the generator
    cannot tell the two cases apart.
    """
    merged: dict[str, str] = {}
    conflicting: dict[str, list[str]] = {}

    for subject_map in maps:
        for code, name in subject_map.items():
            existing = merged.get(code)
            if existing is None:
                merged[code] = name
            elif name and not existing:
                merged[code] = name
            elif name and existing and name != existing:
                names = conflicting.setdefault(code, [existing])
                if name not in names:
                    names.append(name)

    # Pick neither: an unnamed code exports as the bare code, which is honest.
    for code in conflicting:
        merged[code] = ""

    conflicts = [
        SubjectConflict(code=code, names=names)
        for code, names in sorted(conflicting.items())
    ]
    return merged, [c.as_warning() for c in conflicts], conflicts


def apply_ai_subject_labels(
    merged_subjects: dict[str, str],
    ai_subjects_detected: list[SubjectEntry],
) -> tuple[dict[str, str], set[str]]:
    """Let the AI LABEL a subject code rule-based extraction already found;
    never let it INVENT a new one (P0-10, DECISIONS.md 2026-09-19).

    Returns (merged_with_ai_names, invented_codes). The caller counts and
    warns about invented_codes — silently dropping them would repeat the
    P0-1 failure class (a check that discards bad data and says nothing).

    Before this function existed, the matching stage did `merged[code] =
    name` unconditionally on any code the AI returned, so a hallucinated
    subject code became a real column in the delivered workbook with zero
    signal it was never on the document.
    """
    merged = dict(merged_subjects)
    invented: set[str] = set()
    for ai_sub in ai_subjects_detected:
        if ai_sub.code not in merged:
            invented.add(ai_sub.code)
            continue
        if ai_sub.name:
            merged[ai_sub.code] = ai_sub.name  # AI name wins, for a code we already found
    return merged, invented


def summarize_status_warnings(students: list[StudentRecord]) -> list[str]:
    """Warn about every student whose status was defaulted or unrecognised.

    §14.1 — neither case may be silent. `other` means the sheet said something
    the allowlist does not know; a defaulted `regular` means it said nothing.
    """
    warnings: list[str] = []

    defaulted = sum(1 for s in students if not s.status_explicit)
    if defaulted:
        warnings.append(
            f"{defaulted} student(s) had no status on the sheet and were "
            f"defaulted to Regular — confirm before export."
        )

    unknown = [s for s in students if s.status == StudentStatus.OTHER]
    if unknown:
        sample = ", ".join(sorted({s.roll_number for s in unknown})[:3])
        warnings.append(
            f"{len(unknown)} student(s) had an unrecognised status "
            f"(e.g. roll {sample}) and were recorded as Other."
        )

    return warnings


def aggregate_students(
    per_file_students: list[list[StudentRecord]],
    dedupe: bool = DEDUPE_ACROSS_FILES,
) -> tuple[list[StudentRecord], int]:
    """Merge per-file student lists into one combined list.

    With dedupe on, (roll_number, subject_code) is treated as unique: a pair
    appearing in multiple files (or twice in one) is kept once, and the number
    of duplicate pairs dropped is returned so progress can report a REAL count.
    First-seen order of roll numbers is preserved; each student's subject list
    is sorted (matching what the extractors already emit for a single file).
    """
    if not dedupe:
        return [s for file_students in per_file_students for s in file_students], 0

    subjects_by_roll: dict[str, list[str]] = {}
    # The per-student fields (§14.1) are carried on the first record seen for a
    # roll; later files fill in a name only if the first had none. Rebuilding a
    # bare StudentRecord here would silently discard them.
    first_seen: dict[str, StudentRecord] = {}
    seen_pairs: set[tuple[str, str]] = set()
    duplicate_pairs = 0
    for file_students in per_file_students:
        for student in file_students:
            bucket = subjects_by_roll.setdefault(student.roll_number, [])
            kept = first_seen.get(student.roll_number)
            if kept is None:
                first_seen[student.roll_number] = student
            elif not kept.name and student.name:
                first_seen[student.roll_number] = student.model_copy(
                    update={"subjects": kept.subjects}
                )
            for code in student.subjects:
                if (student.roll_number, code) in seen_pairs:
                    duplicate_pairs += 1
                else:
                    seen_pairs.add((student.roll_number, code))
                    bucket.append(code)

    students = [
        first_seen[roll].model_copy(update={"subjects": sorted(codes)})
        for roll, codes in subjects_by_roll.items()
    ]
    return students, duplicate_pairs


def _mixed_type_warning(per_file_results: list[dict]) -> str | None:
    """Heuristic: two files with subject codes but ZERO overlap probably aren't
    the same kind of document (e.g. an attestation sheet mixed with an
    unrelated roll list). Returns a warning string, or None."""
    coded = [
        (r["name"], set(r["subjects"].keys()))
        for r in per_file_results
        if r["subjects"]
    ]
    for i in range(len(coded)):
        for j in range(i + 1, len(coded)):
            if coded[i][1].isdisjoint(coded[j][1]):
                return (
                    "Files may be different document types: no subject codes "
                    f"in common between '{coded[i][0]}' and '{coded[j][0]}'"
                )
    return None


def _combined_text_sample(per_file_results: list[dict], max_chars: int = 3000) -> str:
    """One classifier-ready sample containing a slice of EVERY file, so the AI
    sees the whole batch instead of just the first document."""
    if len(per_file_results) == 1:
        return per_file_results[0]["sample"]
    budget = max(max_chars // len(per_file_results), 400)
    sections = [
        f"--- File {r['index']} of {len(per_file_results)}: {r['name']} ---\n{r['sample'][:budget]}"
        for r in per_file_results
    ]
    return "\n\n".join(sections)[:max_chars]


async def persist_relational_rows(
    db_session,
    job: Job,
    students: list[StudentRecord],
    subject_entries: list[SubjectEntry],
) -> tuple[int, list[tuple[str, list[str]]]]:
    """Upsert Student / SubjectOffering / Enrollment for one job's extraction
    result (WS-G, FUTURE_UNIFIED.md §13.5's persisting_rows stage).

    Only called when job.exam_id is set — there's nothing to attach an
    offering/enrollment to otherwise (the caller checks this).

    Returns (already_enrolled_count, offering_name_conflicts). A conflict is
    the SAME exam_code already existing under this exam with a DIFFERENT
    name — the cross-job version of §14.4's rule (the within-batch version
    is apply_ai_subject_labels/merge_subject_maps, which operates on an
    in-memory map since no SubjectOffering row exists yet at that point).
    Neither name is silently picked; the existing name is kept and the
    conflict is recorded for review, exactly like the within-batch case.
    """
    org_id = job.org_id
    exam_id = job.exam_id

    # 1. Upsert SubjectOffering, keyed on (org, exam, exam_code) — identity
    # of a paper is the exam_code, never the name (§13.1 rule 1). Falls back
    # to the extraction's own `code` when no explicit university exam_code
    # was captured (§14.2 — that mapping is entered once per exam in a
    # future Paper Setup screen; until then the extracted code stands in).
    offering_id_by_code: dict[str, str] = {}
    conflicts: list[tuple[str, list[str]]] = []
    for subj in subject_entries:
        exam_code = subj.exam_code or subj.code
        result = await db_session.execute(
            select(SubjectOffering).where(
                SubjectOffering.org_id == org_id,
                SubjectOffering.exam_id == exam_id,
                SubjectOffering.exam_code == exam_code,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            offering = SubjectOffering(
                org_id=org_id,
                exam_id=exam_id,
                exam_code=exam_code,
                subject_name=subj.name or "",
                paper_no=subj.paper_no,
                group_label=subj.group_label,
            )
            db_session.add(offering)
            await db_session.flush()
            offering_id_by_code[subj.code] = offering.id
        else:
            if subj.name and existing.subject_name and subj.name != existing.subject_name:
                conflicts.append((exam_code, [existing.subject_name, subj.name]))
            elif subj.name and not existing.subject_name:
                existing.subject_name = subj.name
            offering_id_by_code[subj.code] = existing.id

    # 2. Upsert Student, keyed on (org, roll_number) — §13.1 rule 2.
    student_id_by_roll: dict[str, str] = {}
    for rec in students:
        result = await db_session.execute(
            select(Student).where(
                Student.org_id == org_id, Student.roll_number == rec.roll_number
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            student = Student(
                org_id=org_id,
                roll_number=rec.roll_number,
                roll_sort_key=roll_sort_key(rec.roll_number),
                name=rec.name or "",
                college_id=job.college_id,
                status=str(rec.status),
                admission_year=rec.admission_year,
            )
            db_session.add(student)
            await db_session.flush()
            student_id_by_roll[rec.roll_number] = student.id
        else:
            student_id_by_roll[rec.roll_number] = existing.id

    # 3. Upsert Enrollment per (student, offering) pair; count how many
    # already existed from a prior upload — this is a DIFFERENT number from
    # the "deduplicating" stage's within-batch duplicate-pair count (that
    # answers "how many repeats were in THIS upload"; this answers "how many
    # of these enrollments did we already know about").
    already_enrolled = 0
    for rec in students:
        student_id = student_id_by_roll[rec.roll_number]
        for code in rec.subjects:
            offering_id = offering_id_by_code.get(code)
            if offering_id is None:
                continue  # defensive: shouldn't happen, code came from subject_entries
            result = await db_session.execute(
                select(Enrollment).where(
                    Enrollment.student_id == student_id,
                    Enrollment.offering_id == offering_id,
                )
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                already_enrolled += 1
                existing.source_job_id = job.id  # most recent upload wins traceability
                continue
            db_session.add(Enrollment(
                org_id=org_id,
                student_id=student_id,
                offering_id=offering_id,
                source_job_id=job.id,
            ))

    await db_session.flush()
    return already_enrolled, conflicts


class DocumentProcessor:
    """Orchestrates the full extract → aggregate → classify → save pipeline for
    one job, which may span multiple uploaded files."""

    async def process(
        self,
        job_id: str,
        files: list[tuple[str, str, int]],
        db_session,
        ws_manager,
    ) -> None:
        current_stage = {"id": STAGE_IDS[0]}

        try:
            await self._run(job_id, files, db_session, ws_manager, current_stage)
        except Exception as exc:
            logger.error(
                "Processing failed for job %s:\n%s", job_id, traceback.format_exc()
            )
            error_msg = str(exc)
            try:
                result = await db_session.execute(select(Job).where(Job.id == job_id))
                job = result.scalar_one_or_none()
                if job:
                    job.status = "failed"
                    job.error_message = error_msg
                    await db_session.commit()
            except Exception:
                logger.error("Could not persist failure state for job %s", job_id)
            if ws_manager:
                await ws_manager.send_stage(job_id, {
                    "type": "error",
                    "stage_id": current_stage["id"],
                    "message": error_msg,
                })

    async def _run(self, job_id, files, db_session, ws_manager, current_stage):
        from app.config import settings

        job_ref: dict = {}
        n_files = len(files)
        # Every warning collected here is persisted on the Job so the frontend
        # can surface it after processing — honestly, not just in server logs.
        file_warnings: list[str] = []

        async def _emit(stage_id, status, detail=None, count=None, warning=None):
            current_stage["id"] = stage_id
            idx = STAGE_IDS.index(stage_id)
            stages_done = idx + 1 if status == "complete" else idx
            percent = round(stages_done / len(STAGE_IDS) * 100)

            payload = {
                "type": "stage",
                "stage_id": stage_id,
                "label": STAGE_LABELS[stage_id],
                "status": status,
                "detail": detail,
                "count": count,
                "percent": percent,
            }
            if warning:
                payload["warning"] = warning

            if ws_manager:
                await ws_manager.send_stage(job_id, payload)

            job = job_ref.get("job")
            if job is not None:
                job.progress = percent

        # ── STAGE: validating ────────────────────────────────────────────────
        await _emit("validating", "active")

        # files is [(original_name, storage_key, size_bytes)] (DECISIONS.md,
        # 2026-09-20) — size travels with the batch from upload.py, which
        # already knew it while streaming, rather than being re-derived here
        # via a filesystem stat that no longer applies once the bytes may
        # live in object storage instead of on local disk. Only one file's
        # bytes are ever resident at once, fetched one at a time in the
        # reading stage below.
        per_file_types: list[str] = []
        file_sizes: list[int] = []
        for name, _key, size in files:
            per_file_types.append(detect_file_type(name))
            file_sizes.append(size)
            validate_size_bytes(size, settings.max_file_size_mb)

        result = await db_session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            raise RuntimeError(f"Job {job_id!r} not found in database")
        job_ref["job"] = job

        job.status = "processing"
        job.file_type = per_file_types[0] if len(set(per_file_types)) == 1 else "mixed"
        total_mb = sum(file_sizes) / (1024 * 1024)
        await db_session.flush()
        if n_files == 1:
            validate_detail = f"{per_file_types[0].upper()} · {total_mb:.1f} MB"
        else:
            validate_detail = f"{n_files} files · {total_mb:.1f} MB"
        await _emit("validating", "complete", detail=validate_detail)

        # ── STAGE: reading_document ──────────────────────────────────────────
        # The rule-based extractor reads each document and, in the same pass,
        # locates roll numbers and subject codes. We report that single pass
        # as three separate real results (this stage, extracting_rolls,
        # detecting_subjects) rather than one lump sum — each number below is
        # read directly off what the extractors actually found, not invented.
        await _emit("reading_document", "active")

        per_file_results: list[dict] = []
        read_failures: list[str] = []
        for i, (name, key, _size) in enumerate(files, start=1):
            file_type = per_file_types[i - 1]
            if n_files > 1:
                await _emit(
                    "reading_document", "active",
                    detail=f"File {i} of {n_files} · {name}",
                )
            try:
                # Fetch bytes from the storage backend (local disk or R2 —
                # storage.py decides), then parse in a worker thread and
                # drop the bytes before moving to the next file. Holding the
                # whole batch resident was what made peak memory scale with
                # batch size.
                file_bytes = await storage.download_bytes(key)
                students, subjects, sample, doc_count, truncated = await asyncio.to_thread(
                    _run_extractor, file_type, file_bytes, name
                )
                del file_bytes
            except Exception as exc:
                # One unreadable file must not abort the batch — record and go on.
                msg = f"File {i} ({name}): could not be read — {exc}"
                logger.warning("Job %s: %s", job_id, msg)
                read_failures.append(msg)
                continue

            unit = "pages" if file_type == "pdf" else "rows"

            if truncated:
                cap = (
                    settings.max_pdf_pages if file_type == "pdf"
                    else settings.max_rows_per_sheet
                )
                truncation_warning = (
                    f"File {i} ({name}): exceeds {cap:,} {unit} — only the "
                    f"first {cap:,} were read. Split the file and re-upload."
                )
                logger.warning("Job %s: %s", job_id, truncation_warning)
                file_warnings.append(truncation_warning)

            # P0-1 honesty check. A one-student-per-page document legitimately
            # yields students == pages; anything far below that means the layout
            # was not recognised and students were dropped. Silence here is what
            # let P0-1 ship: the job completed green while losing most of a roll.
            if doc_count > 1 and len(students) <= 1:
                low_yield = (
                    f"File {i} ({name}): only {len(students)} student(s) found "
                    f"across {doc_count} {unit} — the layout may not be "
                    f"recognised. Verify the output."
                )
                logger.warning("Job %s: %s", job_id, low_yield)
                file_warnings.append(low_yield)

            per_file_results.append({
                "index": i,
                "name": name,
                "students": students,
                "subjects": subjects,
                "sample": sample,
                "count": doc_count,
                "unit": unit,
            })
            if n_files > 1:
                await _emit(
                    "reading_document", "active",
                    detail=f"File {i} of {n_files} · {doc_count} {unit}",
                )

        if not per_file_results:
            raise RuntimeError(
                "All files failed to read: " + "; ".join(read_failures)
            )
        file_warnings.extend(read_failures)

        if n_files == 1:
            only = per_file_results[0]
            read_detail = f"{only['count']} {only['unit']}"
            read_count = only["count"]
        else:
            unit_totals: dict[str, int] = {}
            for r in per_file_results:
                unit_totals[r["unit"]] = unit_totals.get(r["unit"], 0) + r["count"]
            files_read = len(per_file_results)
            prefix = (
                f"{files_read} files"
                if files_read == n_files
                else f"{files_read} of {n_files} files"
            )
            read_detail = f"{prefix} · " + " · ".join(
                f"{total} {unit}" for unit, total in unit_totals.items()
            )
            read_count = sum(unit_totals.values())
        await _emit(
            "reading_document", "complete",
            detail=read_detail, count=read_count,
            warning="; ".join(read_failures) if read_failures else None,
        )

        # ── STAGE: extracting_rolls ──────────────────────────────────────────
        await _emit("extracting_rolls", "active")
        raw_student_total = sum(len(r["students"]) for r in per_file_results)
        zero_warnings: list[str] = []
        if n_files > 1:
            # In a batch, a file contributing nothing is worth flagging. For a
            # single file the existing AI-extraction fallback (matching stage)
            # handles the zero case exactly as before.
            zero_warnings = [
                f"File {r['index']} ({r['name']}): no roll numbers found"
                for r in per_file_results
                if not r["students"]
            ]
            file_warnings.extend(zero_warnings)
        rolls_detail = (
            f"{raw_student_total} students"
            if n_files == 1
            else f"{raw_student_total} students across {n_files} files"
        )
        await _emit(
            "extracting_rolls", "complete",
            detail=rolls_detail, count=raw_student_total,
            warning="; ".join(zero_warnings) if zero_warnings else None,
        )

        # ── STAGE: detecting_subjects ────────────────────────────────────────
        await _emit("detecting_subjects", "active")
        merged_subjects, name_conflicts, _conflicts = merge_subject_maps(
            [r["subjects"] for r in per_file_results]
        )
        file_warnings.extend(name_conflicts)
        subjects_detail = (
            f"{len(merged_subjects)} subjects"
            if n_files == 1
            else f"{len(merged_subjects)} subjects (merged)"
        )
        await _emit(
            "detecting_subjects", "complete",
            detail=subjects_detail, count=len(merged_subjects),
            warning="; ".join(name_conflicts) if name_conflicts else None,
        )

        # ── STAGE: deduplicating ─────────────────────────────────────────────
        # Always emitted so the checklist never skips a real unit of work; the
        # duplicate count is exactly the number of (roll, subject) pairs merged.
        await _emit("deduplicating", "active")
        students, duplicate_pairs = aggregate_students(
            [r["students"] for r in per_file_results], DEDUPE_ACROSS_FILES
        )
        dedupe_detail = (
            f"{duplicate_pairs} duplicate entries merged"
            if duplicate_pairs
            else "No duplicates"
        )
        status_warnings = summarize_status_warnings(students)
        file_warnings.extend(status_warnings)
        await _emit(
            "deduplicating", "complete",
            detail=dedupe_detail, count=duplicate_pairs,
            warning="; ".join(status_warnings) if status_warnings else None,
        )

        # ── STAGE: ai_analysis ───────────────────────────────────────────────
        # The classifier runs ONCE on a combined sample slicing every file, so
        # the AI sees the whole batch. If files look like different document
        # types we warn (in ai_notes and the stage row) rather than failing.
        await _emit("ai_analysis", "active")
        text_sample = _combined_text_sample(per_file_results)
        mixed_warning = _mixed_type_warning(per_file_results) if n_files > 1 else None
        if mixed_warning:
            file_warnings.append(mixed_warning)

        # Organization.ai_processing_enabled (§8.4 item 2) — when an org has
        # opted out of third-party AI, no document sample or roll number ever
        # leaves this process for Groq. Defaults to enabled only if the org
        # row is somehow missing (org_id is a NOT NULL FK, so this should not
        # happen in practice) — never silently disables AI for everyone else.
        org = (
            await db_session.execute(select(Organization).where(Organization.id == job.org_id))
        ).scalar_one_or_none()
        ai_enabled = org.ai_processing_enabled if org else True

        ai_insight = None
        ai_warning = None
        if ai_enabled:
            try:
                ai_insight = await asyncio.to_thread(classify_document, text_sample, job.filename)
            except Exception as exc:
                logger.warning(
                    "Groq classification failed for job %s, using rule-based fallback: %s", job_id, exc
                )
                ai_warning = f"AI classification unavailable: {exc}"

        if ai_insight is None:
            from app.schemas.schemas import AIInsight
            ai_insight = AIInsight(
                document_type="unknown",
                confidence=0.0,
                total_students=raw_student_total,
                subjects_detected=[],
                notes="AI disabled for this organisation; rule-based extraction used."
                if not ai_enabled
                else "AI classification unavailable; rule-based extraction used.",
                suggested_outputs=["Subject-wise Roll Number List"],
            )

        job.document_type = ai_insight.document_type
        job.ai_confidence = ai_insight.confidence
        job.course = ai_insight.course
        job.semester = ai_insight.semester
        job.exam_name = ai_insight.exam_name
        notes = (ai_insight.notes or "").strip()
        if mixed_warning:
            notes = f"{notes} | {mixed_warning}" if notes else mixed_warning
        job.ai_notes = notes or None
        await db_session.flush()
        stage_warning = "; ".join(w for w in [ai_warning, mixed_warning] if w) or None
        stage_detail = (
            "skipped (AI disabled for this organisation)"
            if not ai_enabled
            else f"{_humanize_doc_type(ai_insight.document_type)} · {ai_insight.confidence * 100:.0f}% confidence"
        )
        await _emit(
            "ai_analysis", "complete",
            detail=stage_detail,
            warning=stage_warning,
        )

        # ── STAGE: matching ──────────────────────────────────────────────────
        await _emit("matching", "active")

        merged, ai_invented_codes = apply_ai_subject_labels(
            merged_subjects, ai_insight.subjects_detected
        )

        # If rule-based found no students at all, try AI extraction as fallback
        # — but never when the org has opted out of AI entirely.
        rejected_roll_count = 0
        if not students and merged and ai_enabled:
            subject_entries_for_ai = [
                SubjectEntry(code=c, name=n) for c, n in merged.items()
            ]
            try:
                students, rejected_roll_count = await asyncio.to_thread(
                    extract_students_ai,
                    text_sample,
                    ai_insight.document_type,
                    subject_entries_for_ai,
                )
            except Exception as exc:
                logger.warning(
                    "Groq AI extraction fallback failed for job %s: %s", job_id, exc
                )

        ai_named_codes = {s.code for s in ai_insight.subjects_detected if s.name}
        labelled_count = len(ai_named_codes & set(merged.keys()))

        matching_warnings: list[str] = []
        if ai_invented_codes:
            sample = ", ".join(sorted(ai_invented_codes)[:5])
            matching_warnings.append(
                f"AI suggested {len(ai_invented_codes)} subject code(s) not found "
                f"in the document ({sample}) — ignored, not added as columns."
            )
        if rejected_roll_count:
            matching_warnings.append(
                f"AI extraction returned {rejected_roll_count} malformed roll "
                f"number(s) — rejected, not stored."
            )
        matching_warning = "; ".join(matching_warnings) or None
        file_warnings.extend(matching_warnings)

        subject_entries = sort_subjects(merged)
        job.total_students = len(students)
        await db_session.flush()
        await _emit(
            "matching", "complete",
            detail=f"{labelled_count} subjects labelled", count=labelled_count,
            warning=matching_warning,
        )

        # ── STAGE: validating_data ───────────────────────────────────────────
        await _emit("validating_data", "active")
        validation = validate_extraction(students, subject_entries)
        if validation["warnings"]:
            logger.warning(
                "Extraction warnings for job %s: %s", job_id, validation["warnings"]
            )
            data_detail = f"{len(validation['warnings'])} warning(s)"
            data_warning = "; ".join(validation["warnings"])
        else:
            data_detail = "No duplicates"
            data_warning = None
        await _emit(
            "validating_data", "complete",
            detail=data_detail, warning=data_warning,
        )

        # ── STAGE: saving ────────────────────────────────────────────────────
        await _emit("saving", "active")

        extracted = ExtractedData(
            job_id=job_id,
            students_json=json.dumps([s.model_dump() for s in students]),
            subjects_json=json.dumps({e.code: e.name for e in subject_entries}),
            raw_text_sample=text_sample,
        )
        db_session.add(extracted)
        job.processing_warnings = json.dumps(file_warnings) if file_warnings else None
        job.status = "completed"
        job.progress = 100
        await db_session.commit()
        await _emit(
            "saving", "complete",
            detail=f"{len(students)} record(s) saved", count=len(students),
        )

        # ── STAGE: persisting_rows (WS-G, §13.5) ───────────────────────────
        # Upserts the relational Student/SubjectOffering/Enrollment rows the
        # seating planner and later features need — a roster query has
        # nothing to run against while extraction only ever writes the
        # students_json/subjects_json blob above.
        await _emit("persisting_rows", "active")
        if job.exam_id is None:
            # No exam chosen at upload (§14.3's picker) — nothing to attach
            # an offering/enrollment to. Not an error: most uploads today
            # predate the picker, and this is the honest, expected state for
            # them rather than a silently-skipped failure.
            await _emit(
                "persisting_rows", "complete",
                detail="No exam selected for this upload — skipped",
            )
        else:
            already_enrolled, offering_conflicts = await persist_relational_rows(
                db_session, job, students, subject_entries,
            )
            await db_session.commit()

            persist_warning = None
            if offering_conflicts:
                sample = "; ".join(
                    f"{code} ({' / '.join(names)})" for code, names in offering_conflicts[:5]
                )
                persist_warning = (
                    f"{len(offering_conflicts)} paper(s) already exist under this "
                    f"exam with a different name ({sample}) — kept the existing "
                    f"name, confirm before relying on it."
                )
                file_warnings.append(persist_warning)
                job.processing_warnings = json.dumps(file_warnings)
                await db_session.commit()

            persist_detail = (
                f"{already_enrolled} already enrolled" if already_enrolled
                else "All new enrollments"
            )
            await _emit(
                "persisting_rows", "complete",
                detail=persist_detail, count=already_enrolled,
                warning=persist_warning,
            )


# ── Module-level convenience instance ────────────────────────────────────────

processor = DocumentProcessor()


# ── Backward-compat stub called by the Prompt 3 scaffold upload router ────────
# Prompt 6 replaces upload.py with a real router that calls processor.process().

async def process_job(job_id: str) -> None:
    await manager.send_progress(
        job_id, 0,
        "Pipeline not yet wired up — upload router will be replaced in Prompt 6.",
        "failed",
    )


# ── Sync helper (runs in a thread via asyncio.to_thread) ─────────────────────

def _run_extractor(
    file_type: str, file_bytes: bytes, filename: str
) -> tuple[list[StudentRecord], dict[str, str], str, int, bool]:
    if file_type == "pdf":
        from app.services.extractors.pdf_extractor import extract_from_pdf_with_stats
        return extract_from_pdf_with_stats(file_bytes, filename)
    if file_type == "xlsx":
        from app.services.extractors.excel_extractor import extract_from_excel_with_stats
        return extract_from_excel_with_stats(file_bytes, filename)
    raise ValueError(f"Unsupported file type: {file_type!r}")
