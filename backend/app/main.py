import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app.database as database
from app.auth import authorize_ws
from app.config import get_settings
from app.database import get_db
from app.middleware.body_size_limit import BodySizeLimitMiddleware
from app.websocket_manager import manager
from app.routers import auth as auth_router
from app.routers import settings as settings_router
from app.routers import colleges, exams, upload, jobs, export

_settings = get_settings()

logging.basicConfig(
    level=_settings.log_level,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _settings.ensure_runtime_dirs()
    # Schema is applied by `alembic upgrade head` before the app starts, not
    # at boot (DECISIONS.md, 2026-09-19) — see alembic/env.py.
    logger.info("ExamRoll started  env=%s", _settings.app_env)
    yield
    logger.info("ExamRoll shutting down")


_docs_public = _settings.app_env != "production"

app = FastAPI(
    title="ExamRoll API",
    version="1.0.0",
    description="Intelligent exam document processor",
    lifespan=lifespan,
    docs_url="/docs" if _docs_public else None,
    redoc_url="/redoc" if _docs_public else None,
    openapi_url="/openapi.json" if _docs_public else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    # None (not "") when unset. Starlette compiles any non-None value: current
    # versions test it with .fullmatch() (an empty pattern then matches
    # nothing), but older ones used .match(), where an empty pattern matches
    # EVERY origin. starlette isn't pinned in requirements.txt, so normalise to
    # None and the behaviour is correct on both.
    allow_origin_regex=_settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router, prefix="/api/v1")
app.include_router(exams.router, prefix="/api/v1")
app.include_router(colleges.router, prefix="/api/v1")
app.include_router(settings_router.router, prefix="/api/v1")
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
    # database.AsyncSessionLocal is read off the module, not imported by name,
    # because conftest.py reassigns that module attribute for the test DB —
    # an `from app.database import AsyncSessionLocal` binding here would keep
    # pointing at the pre-test-override object (P2-32, DECISIONS.md 2026-09-20).
    try:
        async with database.AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        logger.exception("Health check DB round-trip failed")
        db_status = "unreachable"

    payload = {
        "status": "ok" if db_status == "connected" else "degraded",
        "version": "1.0.0",
        "environment": _settings.app_env,
        "database": db_status,
        "groq": "configured"
        if _settings.groq_api_key and _settings.groq_api_key != "your_groq_api_key_here"
        else "not configured",
    }
    return JSONResponse(status_code=200 if db_status == "connected" else 503, content=payload)


@app.websocket("/ws/jobs/{job_id}")
async def websocket_job(websocket: WebSocket, job_id: str, db: AsyncSession = Depends(get_db)):
    # authorize_ws MUST run before manager.connect() — that call does
    # websocket.accept() internally, and once a handshake succeeds there is
    # no taking it back (P0-8, DECISIONS.md 2026-09-19).
    if await authorize_ws(websocket, job_id, db) is None:
        return
    await manager.connect(websocket, job_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, job_id)
    except Exception as exc:
        logger.warning("WebSocket error for job %s: %s", job_id, exc)
        manager.disconnect(websocket, job_id)


# ── Same-origin frontend serving (DECISIONS.md, 2026-09-19) ─────────────────
# Registered LAST, after every API route and the websocket above, so nothing
# here can shadow them — Starlette matches HTTP routes in registration order,
# and /api/v1/*, /health and /assets/* are all more specific than the SPA
# catch-all below and are always matched first.
#
# Only active when frontend/dist actually exists (npm run build was run).
# pytest's ASGITransport client and `npm run dev`'s Vite proxy both never
# build the frontend, so this stays a no-op for them — nothing to guard at
# each call site, it simply never registers.
_dist = _settings.frontend_dist_path
if _dist is not None:
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    _index_html = _dist / "index.html"

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # Reached only for paths no earlier route matched. A React Router
        # client-side route (e.g. /jobs/abc123) must still return the SPA
        # shell on a hard refresh — StaticFiles(html=True) alone does not do
        # this, it only serves index.html for a request that resolves to a
        # directory and 404s everything else.
        return FileResponse(_index_html)

    logger.info("Serving built frontend from %s (same-origin mode)", _dist)
else:
    logger.info("frontend/dist not found — same-origin serving disabled (dev/test mode)")


# ── Body size limit (P0-6) ────────────────────────────────────────────────
# Registered LAST in the file, deliberately: Starlette's LAST-added
# middleware runs FIRST (verified empirically — see body_size_limit.py's
# docstring), so this must come after CORSMiddleware and log_requests above
# for it to actually be the outermost check, running before anything else
# sees the request — including before any multipart parsing begins.
app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=_settings.max_total_batch_bytes,
)
