import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import init_db
from app.websocket_manager import manager
from app.routers import upload, jobs, export

_settings = get_settings()

logging.basicConfig(
    level=_settings.log_level,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _settings.ensure_runtime_dirs()
    await init_db()
    logger.info("ExamRoll started  env=%s", _settings.app_env)
    yield
    logger.info("ExamRoll shutting down")


app = FastAPI(
    title="ExamRoll API",
    version="1.0.0",
    description="Intelligent exam document processor",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(export.router, prefix="/api/v1")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s  %d  %.1fms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"data": None, "error": "Internal server error"},
    )


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "version": "1.0.0",
        "environment": _settings.app_env,
        "database": "connected",
        "groq": "configured"
        if _settings.groq_api_key and _settings.groq_api_key != "your_groq_api_key_here"
        else "not configured",
    }


@app.websocket("/ws/jobs/{job_id}")
async def websocket_job(websocket: WebSocket, job_id: str):
    await manager.connect(websocket, job_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, job_id)
    except Exception as exc:
        logger.warning("WebSocket error for job %s: %s", job_id, exc)
        manager.disconnect(websocket, job_id)
