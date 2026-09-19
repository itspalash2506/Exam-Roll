"""Object storage (Cloudflare R2, DECISIONS.md 2026-09-20).

Every function here operates on a `key` — a string like `{job_id}/{filename}`
or `{job_id}/output_{filename}.xlsx` — never a raw local filesystem path, so
callers never need to know which backend is actually storing the bytes.

Two backends, chosen on EVERY call by whether R2 is configured
(`settings.object_storage_enabled`) — not fixed once at import time, so a
test can monkeypatch the R2 settings (as conftest.py already does for
upload_dir) and get real dynamic dispatch to the R2 backend without any
import-order dependency:
- R2 (`_r2.py`) — used whenever R2 credentials are set, i.e. any real
  deployment. boto3 is sync; every call here runs it through
  asyncio.to_thread(), the same pattern this codebase already uses for
  other blocking I/O (Groq, PDF parsing) — no new async library needed.
- Local disk (`_local.py`) — the fallback when R2 isn't configured, so
  local dev and most of the test suite need no R2 account at all. Stores
  each `key` as a real file under `upload_dir`, preserving exactly the
  behaviour this module replaces.

This module is the ONLY thing that should import boto3 or touch
upload_dir directly for source/output files — every router and the
pipeline call these four functions instead.
"""

from app.config import get_settings
from app.services.storage import _local, _r2


def _backend():
    return _r2 if get_settings().object_storage_enabled else _local


async def upload_local_file(local_path: str, key: str) -> None:
    """Move a file that's currently on local disk into the configured
    backend under `key`. The caller's local_path is untouched — deleting a
    transient local copy after this call is the caller's decision, not
    this function's (see upload.py, which stages briefly then deletes)."""
    await _backend().upload_local_file(local_path, key)


async def upload_bytes(data: bytes, key: str) -> None:
    """Store already-in-memory bytes directly under `key`, with no local
    file involved at all — generate_excel() already returns bytes, so
    export.py never needs to write-then-reread a temp file just to hand it
    to this module."""
    await _backend().upload_bytes(data, key)


async def download_bytes(key: str) -> bytes:
    """Fetch the full contents of `key` into memory. Extraction already
    works from in-memory bytes (pdfplumber/openpyxl both open a BytesIO),
    so the pipeline never needs a second local copy just to process a file."""
    return await _backend().download_bytes(key)


async def object_exists(key: str) -> bool:
    return await _backend().object_exists(key)


async def delete_object(key: str) -> None:
    await _backend().delete_object(key)


async def delete_prefix(prefix: str) -> None:
    """Delete every object under `prefix` — used when a job is deleted, to
    remove all of its source files (and, before this module existed, was a
    plain shutil.rmtree of the job's local directory)."""
    await _backend().delete_prefix(prefix)
