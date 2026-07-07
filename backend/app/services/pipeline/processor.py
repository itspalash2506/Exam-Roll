import asyncio
import json
import logging
import traceback

from sqlalchemy import select

from app.models.db_models import ExtractedData, Job
from app.schemas.schemas import StudentRecord, SubjectEntry
from app.services.ai.classifier import classify_document
from app.services.ai.extractor import extract_students_ai, validate_extraction
from app.utils.file_utils import detect_file_type, validate_file_size
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
}


def _humanize_doc_type(doc_type: str) -> str:
    words = doc_type.replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else "Unknown"


# ── Pure aggregation helpers (unit-testable, no side effects) ─────────────────

def merge_subject_maps(maps: list[dict[str, str]]) -> tuple[dict[str, str], list[str]]:
    """Merge per-file {code: name} maps into one unified map.

    Later files fill in names missing from earlier files. If two files disagree
    on a subject's name, the longer (more complete) name wins and a warning is
    recorded so the conflict is never silent.
    """
    merged: dict[str, str] = {}
    warnings: list[str] = []
    for subject_map in maps:
        for code, name in subject_map.items():
            existing = merged.get(code)
            if existing is None:
                merged[code] = name
            elif name and not existing:
                merged[code] = name
            elif name and existing and name != existing:
                longer = name if len(name) > len(existing) else existing
                warnings.append(
                    f"Subject {code}: files disagree on the name "
                    f"('{existing}' vs '{name}') — kept '{longer}'"
                )
                merged[code] = longer
    return merged, warnings


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
    seen_pairs: set[tuple[str, str]] = set()
    duplicate_pairs = 0
    for file_students in per_file_students:
        for student in file_students:
            bucket = subjects_by_roll.setdefault(student.roll_number, [])
            for code in student.subjects:
                if (student.roll_number, code) in seen_pairs:
                    duplicate_pairs += 1
                else:
                    seen_pairs.add((student.roll_number, code))
                    bucket.append(code)

    students = [
        StudentRecord(roll_number=roll, subjects=sorted(codes))
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


class DocumentProcessor:
    """Orchestrates the full extract → aggregate → classify → save pipeline for
    one job, which may span multiple uploaded files."""

    async def process(
        self,
        job_id: str,
        files: list[tuple[str, bytes]],
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

        per_file_types: list[str] = []
        for name, data in files:
            per_file_types.append(detect_file_type(name))
            validate_file_size(data, settings.max_file_size_mb)

        result = await db_session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            raise RuntimeError(f"Job {job_id!r} not found in database")
        job_ref["job"] = job

        job.status = "processing"
        job.file_type = per_file_types[0] if len(set(per_file_types)) == 1 else "mixed"
        total_mb = sum(len(data) for _, data in files) / (1024 * 1024)
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
        for i, (name, data) in enumerate(files, start=1):
            file_type = per_file_types[i - 1]
            if n_files > 1:
                await _emit(
                    "reading_document", "active",
                    detail=f"File {i} of {n_files} · {name}",
                )
            try:
                students, subjects, sample, doc_count = await asyncio.to_thread(
                    _run_extractor, file_type, data, name
                )
            except Exception as exc:
                # One unreadable file must not abort the batch — record and go on.
                msg = f"File {i} ({name}): could not be read — {exc}"
                logger.warning("Job %s: %s", job_id, msg)
                read_failures.append(msg)
                continue

            unit = "pages" if file_type == "pdf" else "rows"
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
        merged_subjects, name_conflicts = merge_subject_maps(
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
        await _emit(
            "deduplicating", "complete",
            detail=dedupe_detail, count=duplicate_pairs,
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

        ai_insight = None
        ai_warning = None
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
                notes="AI classification unavailable; rule-based extraction used.",
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
        await _emit(
            "ai_analysis", "complete",
            detail=f"{_humanize_doc_type(ai_insight.document_type)} · {ai_insight.confidence * 100:.0f}% confidence",
            warning=stage_warning,
        )

        # ── STAGE: matching ──────────────────────────────────────────────────
        await _emit("matching", "active")

        # Rule-based subjects as the base; AI subject names take priority
        merged: dict[str, str] = dict(merged_subjects)
        for ai_sub in ai_insight.subjects_detected:
            if ai_sub.name:
                merged[ai_sub.code] = ai_sub.name  # AI name wins
            elif ai_sub.code not in merged:
                merged[ai_sub.code] = ""

        # If rule-based found no students at all, try AI extraction as fallback
        if not students and merged:
            subject_entries_for_ai = [
                SubjectEntry(code=c, name=n) for c, n in merged.items()
            ]
            try:
                students = await asyncio.to_thread(
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

        subject_entries = sort_subjects(merged)
        job.total_students = len(students)
        await db_session.flush()
        await _emit(
            "matching", "complete",
            detail=f"{labelled_count} subjects labelled", count=labelled_count,
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
) -> tuple[list[StudentRecord], dict[str, str], str, int]:
    if file_type == "pdf":
        from app.services.extractors.pdf_extractor import extract_from_pdf_with_stats
        return extract_from_pdf_with_stats(file_bytes, filename)
    if file_type == "xlsx":
        from app.services.extractors.excel_extractor import extract_from_excel_with_stats
        return extract_from_excel_with_stats(file_bytes, filename)
    raise ValueError(f"Unsupported file type: {file_type!r}")
