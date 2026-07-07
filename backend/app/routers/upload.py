import json
import logging
import os
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
from app.utils.file_utils import detect_file_type, save_upload_to_job_dir, validate_file_size
from app.websocket_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["upload"])
_settings = get_settings()


async def _run_processing(job_id: str, files: list[tuple[str, bytes]]) -> None:
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

    # Validate EVERY file up front — if any single one is invalid, reject the
    # whole request naming the offending file (never silently drop it).
    batch: list[tuple[str, bytes]] = []
    file_types: list[str] = []
    for upload in files:
        original_name = upload.filename or "upload"
        file_bytes = await upload.read()
        try:
            file_types.append(detect_file_type(original_name))
            validate_file_size(file_bytes, _settings.max_file_size_mb)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"'{original_name}': {exc}")
        batch.append((original_name, file_bytes))

    names = [name for name, _ in batch]
    job_id = str(uuid.uuid4())

    # Save every source file under uploads/{job_id}/ before the background task
    # starts, so the bytes are on disk even if the task outlives the request.
    for i, (name, data) in enumerate(batch, start=1):
        save_upload_to_job_dir(data, name, _settings.upload_dir, job_id, i)

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
