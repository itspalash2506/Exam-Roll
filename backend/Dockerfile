# ExamRoll backend — FastAPI + uvicorn, built for Northflank (or any container host).
#
# Build context is THIS directory (backend/), not the repo root:
#   docker build -t examroll-api backend/
# On Northflank set the service's build context / "Dockerfile path" to backend/
# so the frontend and node_modules never enter the build.
#
# Python 3.14 matches backend/.python-version (3.14.5). The Debian release is
# pinned deliberately — plain `3.14-slim` follows Debian's newest release and
# would silently jump the base OS underneath you on a rebuild.

# ── Stage 1: build wheels ────────────────────────────────────────────────────
# Dependencies are resolved and wheeled here so the runtime image never needs a
# compiler or the pip cache. If a future dependency lacks a prebuilt wheel, add
# its build deps to THIS stage only — the runtime image stays slim either way.
FROM python:3.14-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# A compiler, present ONLY in this stage. Most dependencies ship manylinux
# wheels, but Python 3.14 is new enough that a package (uvloop and httptools
# from uvicorn[standard] are the usual candidates) may still need to build from
# source. Without gcc that failure is a confusing mid-build error; with it the
# build just works, and none of this reaches the runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only requirements first: this layer is cached and reused across rebuilds
# as long as requirements.txt is unchanged, so code edits don't reinstall deps.
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.14-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Runtime defaults pointing at the mounted volume (see the VOLUME note below).
# Both are overridable from the Northflank dashboard like any other env var.
ENV DATABASE_URL=sqlite+aiosqlite:////data/examroll.db \
    UPLOAD_DIR=/data/uploads \
    APP_ENV=production \
    LOG_LEVEL=INFO

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*.whl \
    && rm -rf /wheels

# Application code last: the layers above stay cached when only code changes.
COPY app ./app

# Run as a non-root user. /data is the persistent-volume mount point and must be
# owned by that user, otherwise the first write (SQLite file or an upload) fails
# with EACCES. Created here so the image also works with NO volume attached —
# it just won't survive a restart in that case.
RUN useradd --create-home --uid 10001 examroll \
    && mkdir -p /data/uploads \
    && chown -R examroll:examroll /data /app
USER examroll

EXPOSE 8000

# Uses the app's own /health endpoint. Written with urllib rather than curl so
# the slim image needs no extra packages; a non-200 raises and exits non-zero.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health', timeout=4).status==200 else 1)"]

# `exec` so uvicorn replaces the shell and becomes PID 1 — without it the shell
# holds PID 1 and swallows SIGTERM, so the platform's graceful stop would hang
# until it escalates to SIGKILL. The shell form is needed to expand ${PORT},
# which hosts inject at runtime; 8000 is the local default.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
