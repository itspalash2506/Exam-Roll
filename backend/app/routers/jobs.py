import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import require_org
from app.database import get_db
from app.models.db_models import Job
from app.schemas.schemas import JobDetailResponse, JobResponse
from app.services import storage

logger = logging.getLogger(__name__)
# require_org at the ROUTER level (not per-endpoint) so a route added later
# is protected by default rather than by memory (P0-4, DECISIONS.md
# 2026-09-19).
router = APIRouter(tags=["jobs"], dependencies=[Depends(require_org)])


def _parse_json_list(raw: str | None) -> list[str]:
    from json import JSONDecodeError, loads

    if not raw:
        return []
    try:
        parsed = loads(raw)
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    except JSONDecodeError:
        return []


def _job_to_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        filename=job.filename,
        status=job.status,
        progress=job.progress,
        document_type=job.document_type,
        total_students=job.total_students,
        created_at=job.created_at.isoformat(),
        error_message=job.error_message,
        file_count=job.file_count or 1,
        source_files=_parse_json_list(job.source_files),
    )


def _job_to_detail(job: Job) -> JobDetailResponse:
    from json import loads
    from app.schemas.schemas import ExtractedDataSchema, StudentRecord, SubjectEntry

    extracted = None
    if job.extracted_data:
        ed = job.extracted_data
        students = [StudentRecord(**s) for s in loads(ed.students_json)]
        subjects_raw = loads(ed.subjects_json)
        subjects = [SubjectEntry(code=c, name=n) for c, n in subjects_raw.items()]
        extracted = ExtractedDataSchema(
            students=students,
            subjects=subjects,
            source_file=job.filename,
            total_students=job.total_students or len(students),
            document_type=job.document_type or "unknown",
            course=job.course,
            semester=job.semester,
            exam_name=job.exam_name,
            ai_confidence=job.ai_confidence or 0.0,
            ai_notes=job.ai_notes,
        )

    output_files = [
        {
            "id": f.id,
            "filename": f.filename,
            "format": f.format,
            "file_size_kb": f.file_size_kb,
            "created_at": f.created_at.isoformat(),
        }
        for f in (job.output_files or [])
    ]

    return JobDetailResponse(
        id=job.id,
        filename=job.filename,
        status=job.status,
        progress=job.progress,
        document_type=job.document_type,
        total_students=job.total_students,
        created_at=job.created_at.isoformat(),
        error_message=job.error_message,
        file_count=job.file_count or 1,
        source_files=_parse_json_list(job.source_files),
        warnings=_parse_json_list(job.processing_warnings),
        extracted_data=extracted,
        output_files=output_files,
    )


@router.get("/jobs", response_model=list[JobResponse])
async def list_jobs(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Job)
        .where(Job.org_id == org_id)
        .order_by(Job.created_at.desc()).offset(skip).limit(limit)
    )
    jobs = result.scalars().all()
    return [_job_to_response(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: str, org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Job)
        .where(Job.id == job_id, Job.org_id == org_id)
        .options(selectinload(Job.extracted_data), selectinload(Job.output_files))
    )
    job = result.scalar_one_or_none()
    if not job:
        # 404, never 403: a 403 would confirm the job exists and turn this
        # endpoint into an existence oracle for other tenants' data
        # (DECISIONS.md, 2026-09-19).
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_detail(job)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: str, org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Job)
        .where(Job.id == job_id, Job.org_id == org_id)
        .options(selectinload(Job.output_files))
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # job.file_path is the job's storage key PREFIX (f"{job_id}/") — every
    # source file AND every generated output shares it (export.py writes
    # outputs to f"{job_id}/output_*.xlsx"), so one prefix delete covers
    # everything the job ever wrote, on whichever backend is configured
    # (DECISIONS.md, 2026-09-20).
    key_prefix = job.file_path

    await db.delete(job)
    await db.commit()

    if key_prefix:
        try:
            await storage.delete_prefix(key_prefix)
        except Exception as exc:
            logger.warning("Could not delete storage prefix %s: %s", key_prefix, exc)
