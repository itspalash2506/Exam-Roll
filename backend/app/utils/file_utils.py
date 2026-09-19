import os
import re
import uuid

from fastapi import HTTPException, UploadFile

ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}

_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


# Chunk size for copying an UploadFile to disk. 1 MiB keeps the transient
# buffer negligible no matter how large the upload is, so peak RSS during an
# upload no longer scales with file size or with how many files are in a batch.
_UPLOAD_CHUNK_BYTES = 1024 * 1024


# ── New pipeline-facing functions ────────────────────────────────────────────

def detect_file_type(filename: str) -> str:
    """Return 'pdf' or 'xlsx'; raise ValueError for anything else."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext == ".xlsx":
        return "xlsx"
    raise ValueError(f"Unsupported file type '{ext}'. Supported: .pdf, .xlsx")


def validate_size_bytes(n_bytes: int, max_mb: int) -> None:
    """Size check taking a byte COUNT, so callers never need the bytes in RAM."""
    size_mb = n_bytes / (1024 * 1024)
    if size_mb > max_mb:
        raise ValueError(
            f"File size {size_mb:.1f} MB exceeds the {max_mb} MB limit"
        )


def validate_file_size(file_bytes: bytes, max_mb: int) -> None:
    """Byte-buffer form of validate_size_bytes, kept for in-memory callers."""
    validate_size_bytes(len(file_bytes), max_mb)


def save_upload(file_bytes: bytes, filename: str, upload_dir: str) -> str:
    """Save bytes to upload_dir/<uuid><ext> and return the full filepath."""
    os.makedirs(upload_dir, exist_ok=True)
    ext = os.path.splitext(filename)[1].lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(upload_dir, unique_name)
    with open(filepath, "wb") as fh:
        fh.write(file_bytes)
    return filepath


def safe_indexed_filename(index: int, filename: str) -> str:
    """<index>_<safe_name> — original basename kept for traceability but
    stripped of any path components and characters unsafe in either a local
    filename or an object storage key. Shared by job_file_path (local paths)
    and upload.py's object storage key construction, so the two naming
    schemes can never drift apart."""
    safe_name = os.path.basename(filename.replace("\\", "/")) or "upload"
    safe_name = re.sub(r'[<>:"|?*]', "_", safe_name)
    return f"{index:02d}_{safe_name}"


def job_file_path(upload_dir: str, job_id: str, index: int, filename: str) -> str:
    """Destination path for one batch file: upload_dir/<job_id>/<index>_<safe_name>.

    The job directory keeps every source file of a multi-file job together
    (and next to the generated outputs, which already live there). The index
    prefix preserves upload order and avoids collisions; the original basename
    is kept for traceability but stripped of any path components.
    """
    job_dir = os.path.join(upload_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)
    return os.path.join(job_dir, safe_indexed_filename(index, filename))


def save_upload_to_job_dir(
    file_bytes: bytes, filename: str, upload_dir: str, job_id: str, index: int
) -> str:
    """Write already-in-memory bytes to the job dir and return the path."""
    filepath = job_file_path(upload_dir, job_id, index, filename)
    with open(filepath, "wb") as fh:
        fh.write(file_bytes)
    return filepath


async def stream_upload_to_job_dir(
    upload: UploadFile, upload_dir: str, job_id: str, index: int, max_mb: int
) -> tuple[str, int]:
    """Copy an UploadFile to the job dir in chunks, enforcing max_mb as it goes.

    Never holds more than one chunk in memory, so an upload's RAM cost is flat
    regardless of file size. The previous read-it-all-then-check approach
    materialised every file in the batch at once, which is what OOM-killed the
    512 MB container. An oversized file is now also rejected the moment it
    crosses the limit instead of after being fully read, and its partial file
    is deleted so the pipeline never sees a truncated document.

    Returns (filepath, bytes_written).
    """
    filepath = job_file_path(upload_dir, job_id, index, upload.filename or "upload")
    limit = max_mb * 1024 * 1024
    written = 0
    try:
        with open(filepath, "wb") as fh:
            while chunk := await upload.read(_UPLOAD_CHUNK_BYTES):
                written += len(chunk)
                if written > limit:
                    raise ValueError(f"File size exceeds the {max_mb} MB limit")
                fh.write(chunk)
    except Exception:
        if os.path.exists(filepath):
            os.remove(filepath)
        raise
    return filepath, written


def clean_text(text: str) -> str:
    """Normalize line endings, collapse extra whitespace, strip trailing spaces."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _BLANK_LINES_RE.sub("\n\n", text)
    text = "\n".join(_WHITESPACE_RE.sub(" ", line).rstrip() for line in text.split("\n"))
    return text.strip()


# ── Backward-compat helpers used by the scaffold upload router ───────────────

def validate_upload(file: UploadFile) -> None:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Supported: {', '.join(ALLOWED_EXTENSIONS)}",
        )
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"MIME type '{file.content_type}' not allowed",
        )


def safe_upload_path(upload_dir: str, original_filename: str) -> str:
    ext = os.path.splitext(original_filename or "file")[1].lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"
    return os.path.join(upload_dir, unique_name)
