import json
import logging
import shutil
import tempfile
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user, require_org
from app.config import get_settings
from app.database import AsyncSessionLocal, get_db
from app.models.db_models import College, Exam, Job, User
from app.schemas.schemas import UploadResponse
from app.services.pipeline.processor import processor
from app.services import storage
from app.utils.file_utils import detect_file_type, safe_indexed_filename, stream_upload_to_job_dir
from app.websocket_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["upload"], dependencies=[Depends(require_org)])
_settings = get_settings()


async def _run_processing(job_id: str, files: list[tuple[str, str, int]]) -> None:
    async with AsyncSessionLocal() as db:
        await processor.process(job_id, files, db, manager)


def _batch_summary_name(names: list[str]) -> str:
    """Human summary for Job.filename: the name itself for one file, else 'N files (first, …)'."""
    if len(names) == 1:
        return names[0][:255]
    return f"{len(names)} files ({names[0]}, …)"[:255]


@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    # §14.3's picker — optional for now (an upload predating the picker, or
    # a caller that hasn't adopted it, is still valid; DECISIONS.md,
    # 2026-09-19). When given, must belong to the uploader's own org: never
    # trust an id from the client without checking it against org_id, or an
    # upload could get silently attached to another tenant's exam.
    exam_id: str | None = Form(None),
    college_id: str | None = Form(None),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if len(files) > _settings.max_batch_files:
        raise HTTPException(
            status_code=400,
            detail=f"{len(files)} files exceeds the {_settings.max_batch_files}-file batch limit",
        )
    if exam_id is not None:
        result = await db.execute(
            select(Exam.id).where(Exam.id == exam_id, Exam.org_id == user.org_id)
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Unknown exam_id")
    if college_id is not None:
        result = await db.execute(
            select(College.id).where(College.id == college_id, College.org_id == user.org_id)
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Unknown college_id")

    job_id = str(uuid.uuid4())
    key_prefix = f"{job_id}/"

    # Object storage (Cloudflare R2, DECISIONS.md 2026-09-20): each file is
    # streamed to a TRANSIENT local staging directory first — chunked async
    # I/O can't hand bytes directly to boto3 (sync), so a brief local touch
    # is unavoidable — then pushed to the configured storage backend and the
    # staged copy deleted immediately. Local disk stops accumulating
    # anything; it's scratch space for the duration of one upload, not
    # long-term storage. staging_dir is a real OS temp directory, NEVER
    # upload_dir — when object storage is disabled (local-disk fallback),
    # upload_dir IS the permanent store, and staging there would mean
    # deleting the only copy after "uploading" it to itself.
    staging_dir = tempfile.mkdtemp(prefix="examroll-upload-")
    batch: list[tuple[str, str, int]] = []
    file_types: list[str] = []
    total_bytes = 0
    try:
        for i, upload in enumerate(files, start=1):
            original_name = upload.filename or "upload"
            try:
                file_types.append(detect_file_type(original_name))
                staged_path, written = await stream_upload_to_job_dir(
                    upload, staging_dir, job_id, i, _settings.max_file_size_mb
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"'{original_name}': {exc}")
            total_bytes += written
            if total_bytes > _settings.max_total_batch_bytes:
                raise HTTPException(
                    status_code=400,
                    detail=f"Batch exceeds the {_settings.max_total_batch_mb} MB total limit",
                )
            key = key_prefix + safe_indexed_filename(i, original_name)
            await storage.upload_local_file(staged_path, key)
            batch.append((original_name, key, written))
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        await storage.delete_prefix(key_prefix)
        raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    names = [name for name, _, _ in batch]

    job = Job(
        id=job_id,
        org_id=user.org_id,
        created_by=user.id,
        exam_id=exam_id,
        college_id=college_id,
        filename=_batch_summary_name(names),
        file_type=file_types[0] if len(set(file_types)) == 1 else "mixed",
        file_path=key_prefix,
        source_files=json.dumps(names),
        file_count=len(batch),
        status="queued",
    )
    db.add(job)
    await db.commit()

    background_tasks.add_task(_run_processing, job_id, batch)

    logger.info("Uploaded %d file(s) (%s) → job %s", len(batch), ", ".join(names), job_id)
    return UploadResponse(
        job_id=job_id,
        message=f"{len(batch)} file(s) uploaded, processing started",
        ai_insight=None,
    )


# The WebSocket endpoint that used to live here (/api/v1/ws/{job_id}) was
# dead code — the frontend has only ever connected to the one on main.py
# (/ws/jobs/{job_id}), confirmed via client.js. Two near-identical WebSocket
# endpoints with divergent behaviour is a standing maintenance hazard: a fix
# applied to one silently misses the other, which is exactly what happened
# here — this one sent a state snapshot on connect and the real one didn't,
# until main.py's endpoint gained authorize_ws (DECISIONS.md, 2026-09-19).
