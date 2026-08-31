import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal, get_db
from app.models.db_models import Job
from app.schemas.schemas import UploadResponse
from app.services.pipeline.processor import processor
from app.utils.file_utils import detect_file_type, stream_upload_to_job_dir
from app.websocket_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["upload"])
_settings = get_settings()


async def _run_processing(job_id: str, files: list[tuple[str, str]]) -> None:
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
    db: AsyncSession = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if len(files) > _settings.max_batch_files:
        raise HTTPException(
            status_code=400,
            detail=f"{len(files)} files exceeds the {_settings.max_batch_files}-file batch limit",
        )

    job_id = str(uuid.uuid4())
    job_dir = os.path.join(_settings.upload_dir, job_id)

    # Stream every file STRAIGHT to uploads/{job_id}/ rather than reading it
    # into memory: the whole batch used to be resident at once (and stayed
    # resident for the entire background job, since the bytes were handed to
    # the task), which is what OOM-killed the 512 MB container. Now only a
    # 1 MiB chunk is ever in flight, and the pipeline receives file PATHS.
    #
    # Validation still rejects the whole request naming the offending file —
    # the partially written job dir is removed so nothing half-uploaded is left
    # behind for a later job to trip over.
    batch: list[tuple[str, str]] = []
    file_types: list[str] = []
    total_bytes = 0
    try:
        for i, upload in enumerate(files, start=1):
            original_name = upload.filename or "upload"
            try:
                file_types.append(detect_file_type(original_name))
                path, written = await stream_upload_to_job_dir(
                    upload, _settings.upload_dir, job_id, i, _settings.max_file_size_mb
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"'{original_name}': {exc}")
            total_bytes += written
            if total_bytes > _settings.max_total_batch_bytes:
                raise HTTPException(
                    status_code=400,
                    detail=f"Batch exceeds the {_settings.max_total_batch_mb} MB total limit",
                )
            batch.append((original_name, path))
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise

    names = [name for name, _ in batch]

    job = Job(
        id=job_id,
        filename=_batch_summary_name(names),
        file_type=file_types[0] if len(set(file_types)) == 1 else "mixed",
        file_path=os.path.join(_settings.upload_dir, job_id),
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


@router.websocket("/ws/{job_id}")
async def websocket_job_progress(websocket: WebSocket, job_id: str):
    await manager.connect(websocket, job_id)
    try:
        # Send current job state immediately on connect
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if job:
                await websocket.send_text(json.dumps({
                    "progress": job.progress,
                    "status": job.status,
                    "message": f"Job is {job.status}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }))
            else:
                await websocket.send_text(json.dumps({"error": "Job not found"}))

        # Keep connection alive until client disconnects or job finishes
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, job_id)
    except Exception as exc:
        logger.warning("WebSocket error for job %s: %s", job_id, exc)
        manager.disconnect(websocket, job_id)
