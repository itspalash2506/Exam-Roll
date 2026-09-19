import logging
from json import loads

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_org
from app.config import get_settings
from app.database import get_db
from app.models.db_models import Job, OutputFile
from app.schemas.schemas import (
    ExportRequest,
    ExtractedDataSchema,
    StudentRecord,
    SubjectEntry,
)
from app.services.generators.excel_generator import generate_excel
from app.services import storage

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

    extracted = _load_extracted(job)

    try:
        xlsx_bytes = generate_excel(extracted, req.style_config, req.filename)
    except Exception as exc:
        logger.exception("Excel generation failed for job %s", req.job_id)
        raise HTTPException(status_code=500, detail=f"Excel generation failed: {exc}") from exc

    # Object storage (Cloudflare R2, DECISIONS.md 2026-09-20): generate_excel
    # already returns bytes — no local temp file to write-then-reread, the
    # bytes go straight to the configured storage backend.
    safe_stem = req.filename.replace("/", "_").replace("\\", "_")
    out_filename = f"output_{safe_stem}.xlsx"
    out_key = f"{req.job_id}/{out_filename}"
    try:
        await storage.upload_bytes(xlsx_bytes, out_key)
    except Exception as exc:
        logger.exception("Could not store output file for job %s", req.job_id)
        raise HTTPException(status_code=500, detail="Could not store output file") from exc

    file_size_kb = max(1, len(xlsx_bytes) // 1024)
    output_record = OutputFile(
        job_id=req.job_id,
        format="xlsx",
        filename=out_filename,
        filepath=out_key,
        file_size_kb=file_size_kb,
    )
    db.add(output_record)
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
