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


# ── New pipeline-facing functions ────────────────────────────────────────────

def detect_file_type(filename: str) -> str:
    """Return 'pdf' or 'xlsx'; raise ValueError for anything else."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext == ".xlsx":
        return "xlsx"
    raise ValueError(f"Unsupported file type '{ext}'. Supported: .pdf, .xlsx")


def validate_file_size(file_bytes: bytes, max_mb: int) -> None:
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > max_mb:
        raise ValueError(
            f"File size {size_mb:.1f} MB exceeds the {max_mb} MB limit"
        )


def save_upload(file_bytes: bytes, filename: str, upload_dir: str) -> str:
    """Save bytes to upload_dir/<uuid><ext> and return the full filepath."""
    os.makedirs(upload_dir, exist_ok=True)
    ext = os.path.splitext(filename)[1].lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(upload_dir, unique_name)
    with open(filepath, "wb") as fh:
        fh.write(file_bytes)
    return filepath


def save_upload_to_job_dir(
    file_bytes: bytes, filename: str, upload_dir: str, job_id: str, index: int
) -> str:
    """Save one batch file to upload_dir/<job_id>/<index>_<safe_name> and return the path.

    The job directory keeps every source file of a multi-file job together
    (and next to the generated outputs, which already live there). The index
    prefix preserves upload order and avoids collisions; the original basename
    is kept for traceability but stripped of any path components.
    """
    job_dir = os.path.join(upload_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)
    safe_name = os.path.basename(filename.replace("\\", "/")) or "upload"
    safe_name = re.sub(r'[<>:"|?*]', "_", safe_name)
    filepath = os.path.join(job_dir, f"{index:02d}_{safe_name}")
    with open(filepath, "wb") as fh:
        fh.write(file_bytes)
    return filepath


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
