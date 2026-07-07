import logging
import os
import shutil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.db_models import Job
from app.schemas.schemas import JobDetailResponse, JobResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["jobs"])


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
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Job).order_by(Job.created_at.desc()).offset(skip).limit(limit)
    )
    jobs = result.scalars().all()
    return [_job_to_response(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job)
        .where(Job.id == job_id)
        .options(selectinload(Job.extracted_data), selectinload(Job.output_files))
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_detail(job)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job)
        .where(Job.id == job_id)
        .options(selectinload(Job.output_files))
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Collect paths to delete from disk before removing DB records
    paths_to_delete: list[str] = []
    if job.file_path:
        paths_to_delete.append(job.file_path)
    for output_file in job.output_files or []:
        if output_file.filepath:
            paths_to_delete.append(output_file.filepath)

    await db.delete(job)
    await db.commit()

    for path in paths_to_delete:
        try:
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isdir(path):
                # Multi-file jobs store file_path as the uploads/{job_id}
                # directory holding every source file + generated outputs.
                shutil.rmtree(path, ignore_errors=True)
        except OSError as exc:
            logger.warning("Could not delete file %s: %s", path, exc)
