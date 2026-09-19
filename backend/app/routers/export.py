import asyncio
import logging
from json import loads

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_org
from app.config import get_settings
from app.database import get_db
from app.models.db_models import Enrollment, Job, OutputFile, Student, SubjectOffering
from app.schemas.schemas import (
    ExportRequest,
    ExtractedDataSchema,
    StudentRecord,
    StudentStatus,
    SubjectEntry,
)
from app.services.generators.excel_generator import generate_excel
from app.services import storage
from app.utils.subject_utils import sort_subjects

logger = logging.getLogger(__name__)
router = APIRouter(tags=["export"], dependencies=[Depends(require_org)])
_settings = get_settings()

_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _load_extracted(job: Job) -> ExtractedDataSchema:
    if not job.extracted_data:
        raise HTTPException(status_code=400, detail="No extracted data for this job")
    ed = job.extracted_data
    students = [StudentRecord(**s) for s in loads(ed.students_json)]
    subjects_raw = loads(ed.subjects_json)
    subjects = [SubjectEntry(code=c, name=n) for c, n in subjects_raw.items()]
    return ExtractedDataSchema(
        students=students,
        subjects=subjects,
        source_file=job.filename,
        total_students=job.total_students or len(students),
        document_type=job.document_type or "unknown",
        course=job.course,
        semester=job.semester,
        exam_name=job.exam_name,
        ai_confidence=job.ai_confidence or 0.0,
    )


async def _load_extracted_relational(
    job: Job, db: AsyncSession
) -> ExtractedDataSchema | None:
    """Source from Enrollment ⋈ Student ⋈ SubjectOffering — the relational
    model processor.py's persisting_rows stage populates — instead of the
    legacy students_json/subjects_json blob (P11, DECISIONS.md 2026-09-20).

    Filtered to THIS job's own enrollments (Enrollment.source_job_id ==
    job.id), not the whole exam's cumulative roster — persisting_rows moves
    an enrollment's source_job_id to "the most recent upload that confirmed
    it," so this reproduces exactly what students_json used to hold for this
    job: what THIS upload's extraction found, not every historical upload
    under the same exam.

    Returns None when there's nothing relational to read (job.exam_id unset,
    or a job that predates the exam/college picker), so the caller falls
    back to _load_extracted() — an existing job's export never breaks.
    """
    if not job.exam_id:
        return None

    result = await db.execute(
        select(Student, SubjectOffering)
        .join(Enrollment, Enrollment.student_id == Student.id)
        .join(SubjectOffering, SubjectOffering.id == Enrollment.offering_id)
        .where(Enrollment.source_job_id == job.id)
        .order_by(Student.roll_sort_key)
    )
    rows = result.all()
    if not rows:
        return None

    students_by_roll: dict[str, StudentRecord] = {}
    subjects_by_code: dict[str, SubjectEntry] = {}
    roll_order: list[str] = []

    for student, offering in rows:
        if student.roll_number not in students_by_roll:
            students_by_roll[student.roll_number] = StudentRecord(
                roll_number=student.roll_number,
                subjects=[],
                name=student.name,
                status=StudentStatus(student.status),
                admission_year=student.admission_year,
            )
            roll_order.append(student.roll_number)
        students_by_roll[student.roll_number].subjects.append(offering.exam_code)

        if offering.exam_code not in subjects_by_code:
            subjects_by_code[offering.exam_code] = SubjectEntry(
                code=offering.exam_code,
                name=offering.subject_name,
                exam_code=offering.exam_code,
                paper_no=offering.paper_no,
                group_label=offering.group_label,
            )

    students = [students_by_roll[r] for r in roll_order]
    # Column order must match the existing sort_subjects rule (numeric suffix
    # of the code) — reuse it for the ORDER, not to rebuild the entries, since
    # it only knows code/name and would drop exam_code/paper_no/group_label.
    ordered_codes = [
        e.code for e in sort_subjects({c: e.name for c, e in subjects_by_code.items()})
    ]
    subjects = [subjects_by_code[c] for c in ordered_codes]

    return ExtractedDataSchema(
        students=students,
        subjects=subjects,
        source_file=job.filename,
        total_students=len(students),
        document_type=job.document_type or "unknown",
        course=job.course,
        semester=job.semester,
        exam_name=job.exam_name,
        ai_confidence=job.ai_confidence or 0.0,
    )


def _xlsx_response(data: bytes, download_name: str) -> Response:
    return Response(
        content=data,
        media_type=_XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


@router.post("/export")
async def export_job(
    req: ExportRequest,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Job)
        .where(Job.id == req.job_id, Job.org_id == org_id)
        .options(selectinload(Job.extracted_data))
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        raise HTTPException(
            status_code=400, detail=f"Job is not completed (status: {job.status})"
        )

    extracted = await _load_extracted_relational(job, db) or _load_extracted(job)

    try:
        # generate_excel is synchronous openpyxl work — real CPU time for a
        # large roster, so it runs off the event loop rather than blocking
        # every other in-flight request for its duration (P1-18).
        xlsx_bytes = await asyncio.to_thread(
            generate_excel, extracted, req.style_config, req.filename
        )
    except Exception as exc:
        logger.exception("Excel generation failed for job %s", req.job_id)
        raise HTTPException(status_code=500, detail=f"Excel generation failed: {exc}") from exc

    # Object storage (Cloudflare R2, DECISIONS.md 2026-09-20): generate_excel
    # already returns bytes — no local temp file to write-then-reread, the
    # bytes go straight to the configured storage backend. A PUT to a given
    # key is atomic on S3-compatible storage (a concurrent GET sees the old
    # or the new object whole, never a torn write) — the local-disk race
    # P1-17 originally described no longer applies at the byte level.
    safe_stem = req.filename.replace("/", "_").replace("\\", "_")
    out_filename = f"output_{safe_stem}.xlsx"
    out_key = f"{req.job_id}/{out_filename}"
    try:
        await storage.upload_bytes(xlsx_bytes, out_key)
    except Exception as exc:
        logger.exception("Could not store output file for job %s", req.job_id)
        raise HTTPException(status_code=500, detail="Could not store output file") from exc

    file_size_kb = max(1, len(xlsx_bytes) // 1024)
    # Re-exporting the same job with the same filename (a double-click, or
    # re-running export after tweaking style) reuses the existing OutputFile
    # row instead of inserting a duplicate that points at the same key —
    # without this, an older row's download link would silently start
    # serving whatever the newest export overwrote it with (P1-17). This
    # narrows but does not fully close the race on a genuinely simultaneous
    # double-click — that needs a DB-level unique constraint on
    # (job_id, filename), deferred since it's a new migration for a benign
    # worst case (one extra row, not corrupt data); see DECISIONS.md.
    existing = (
        await db.execute(
            select(OutputFile).where(
                OutputFile.job_id == req.job_id, OutputFile.filename == out_filename
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.file_size_kb = file_size_kb
        existing.filepath = out_key
    else:
        db.add(OutputFile(
            job_id=req.job_id,
            format="xlsx",
            filename=out_filename,
            filepath=out_key,
            file_size_kb=file_size_kb,
        ))
    await db.commit()

    return _xlsx_response(xlsx_bytes, f"{safe_stem}.xlsx")


@router.get("/export/{job_id}/download/{file_id}")
async def redownload_output(
    job_id: str,
    file_id: str,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    # OutputFile carries no org_id of its own — join through Job, the same
    # pattern as every other tenant-scoped query.
    result = await db.execute(
        select(OutputFile)
        .join(Job, Job.id == OutputFile.job_id)
        .where(OutputFile.id == file_id, OutputFile.job_id == job_id, Job.org_id == org_id)
    )
    output_file = result.scalar_one_or_none()
    if not output_file:
        raise HTTPException(status_code=404, detail="Output file not found")
    if not await storage.object_exists(output_file.filepath):
        raise HTTPException(status_code=404, detail="File no longer exists in storage")

    data = await storage.download_bytes(output_file.filepath)
    return _xlsx_response(data, output_file.filename)
