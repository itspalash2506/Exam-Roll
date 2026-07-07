import logging
import os
from json import loads

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

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

logger = logging.getLogger(__name__)
router = APIRouter(tags=["export"])
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


@router.post("/export")
async def export_job(req: ExportRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job).where(Job.id == req.job_id).options(selectinload(Job.extracted_data))
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

    # Save to uploads/{job_id}/output_{filename}.xlsx
    out_dir = os.path.join(_settings.upload_dir, req.job_id)
    os.makedirs(out_dir, exist_ok=True)
    safe_stem = req.filename.replace("/", "_").replace("\\", "_")
    out_filename = f"output_{safe_stem}.xlsx"
    out_path = os.path.join(out_dir, out_filename)
    try:
        with open(out_path, "wb") as fh:
            fh.write(xlsx_bytes)
    except OSError as exc:
        logger.exception("Could not write output file for job %s", req.job_id)
        raise HTTPException(status_code=500, detail="Could not write output file") from exc

    file_size_kb = max(1, len(xlsx_bytes) // 1024)
    output_record = OutputFile(
        job_id=req.job_id,
        format="xlsx",
        filename=out_filename,
        filepath=out_path,
        file_size_kb=file_size_kb,
    )
    db.add(output_record)
    await db.commit()

    download_name = f"{safe_stem}.xlsx"
    return FileResponse(
        path=out_path,
        media_type=_XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


@router.get("/export/{job_id}/download/{file_id}")
async def redownload_output(
    job_id: str, file_id: str, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(OutputFile).where(
            OutputFile.id == file_id, OutputFile.job_id == job_id
        )
    )
    output_file = result.scalar_one_or_none()
    if not output_file:
        raise HTTPException(status_code=404, detail="Output file not found")
    if not os.path.isfile(output_file.filepath):
        raise HTTPException(status_code=404, detail="File no longer exists on disk")

    return FileResponse(
        path=output_file.filepath,
        media_type=_XLSX_MEDIA,
        headers={
            "Content-Disposition": f'attachment; filename="{output_file.filename}"'
        },
    )
