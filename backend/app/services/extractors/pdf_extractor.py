import re
import logging
from io import BytesIO

import pdfplumber

from app.schemas.schemas import StudentRecord
from app.utils.file_utils import clean_text
from app.utils.subject_utils import extract_all_subjects

logger = logging.getLogger(__name__)

# Roll number patterns common in Indian college attestation sheets
_ROLL_RE = re.compile(
    r"Roll\s*No\.?\s*[:\-]?\s*(\d{4,12})", re.IGNORECASE
)
_ENROLL_RE = re.compile(
    r"(?:Enroll\w*|Reg(?:istration)?\.?\s*No\.?)\s*[:\-]?\s*([A-Z0-9]{5,15})",
    re.IGNORECASE,
)


def extract_from_pdf(
    file_bytes: bytes, filename: str
) -> tuple[list[StudentRecord], dict[str, str], str]:
    """Extract students, subjects, and a text sample from a PDF.

    Returns:
        students   — one StudentRecord per unique roll number found
        subjects   — {code: name} map aggregated across all pages
        text_sample — first ~3000 chars from pages 1-2, for AI classifier
    """
    students, subjects, text_sample, _page_count = extract_from_pdf_with_stats(
        file_bytes, filename
    )
    return students, subjects, text_sample


def extract_from_pdf_with_stats(
    file_bytes: bytes, filename: str
) -> tuple[list[StudentRecord], dict[str, str], str, int]:
    """Same extraction as extract_from_pdf, plus the real page count for progress reporting."""
    page_texts = _extract_page_texts(file_bytes, filename)

    if not page_texts:
        return [], {}, "", 0

    text_sample = "\n\n".join(page_texts[:2])[:3000]
    full_text = "\n\n".join(page_texts)

    # Collect subject codes + names across the whole document
    all_subjects: dict[str, str] = extract_all_subjects(full_text)

    # Per-page: find roll number → assign subject codes found on that page
    merged: dict[str, set[str]] = {}
    for page_text in page_texts:
        if not page_text.strip():
            continue

        roll_match = _ROLL_RE.search(page_text) or _ENROLL_RE.search(page_text)
        if not roll_match:
            continue

        roll_no = roll_match.group(1).strip()
        page_subjects = extract_all_subjects(page_text)

        if page_subjects:
            merged.setdefault(roll_no, set()).update(page_subjects.keys())
            # Promote any named subjects found on this page to the global map
            for code, name in page_subjects.items():
                if name and (code not in all_subjects or not all_subjects[code]):
                    all_subjects[code] = name

    students = [
        StudentRecord(roll_number=roll, subjects=sorted(subs))
        for roll, subs in merged.items()
    ]

    # Prefer subjects that have names; fall back to nameless codes if none do
    named = {k: v for k, v in all_subjects.items() if v}
    final_subjects = named if named else all_subjects

    return students, final_subjects, text_sample, len(page_texts)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _extract_page_texts(file_bytes: bytes, filename: str) -> list[str]:
    """Return one cleaned string per page, using pdfplumber with pypdf fallback."""
    try:
        return _extract_with_pdfplumber(file_bytes)
    except Exception as exc:
        logger.warning(
            "pdfplumber failed for '%s' (%s) — falling back to pypdf entirely",
            filename, exc,
        )
        return _extract_with_pypdf(file_bytes, filename)


def _extract_with_pdfplumber(file_bytes: bytes) -> list[str]:
    page_texts: list[str] = []
    _pypdf_reader = None
    _pypdf_failed = False

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for i, page in enumerate(pdf.pages):
            text: str = page.extract_text() or ""

            if not text.strip():
                # Try pdfplumber table extraction as first fallback
                tables = page.extract_tables() or []
                rows: list[str] = []
                for table in tables:
                    for row in table:
                        if row:
                            rows.append(
                                "\t".join(str(c) if c is not None else "" for c in row)
                            )
                text = "\n".join(rows)

            if not text.strip() and not _pypdf_failed:
                # Try pypdf as per-page fallback
                try:
                    if _pypdf_reader is None:
                        from pypdf import PdfReader
                        _pypdf_reader = PdfReader(BytesIO(file_bytes))
                    if i < len(_pypdf_reader.pages):
                        text = _pypdf_reader.pages[i].extract_text() or ""
                except Exception as exc:
                    logger.debug("pypdf per-page fallback failed for page %d: %s", i, exc)
                    _pypdf_failed = True

            page_texts.append(clean_text(text))

    return page_texts


def _extract_with_pypdf(file_bytes: bytes, filename: str) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            f"Neither pdfplumber nor pypdf could extract '{filename}'"
        ) from exc

    try:
        reader = PdfReader(BytesIO(file_bytes))
        return [clean_text(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        raise RuntimeError(
            f"PDF extraction failed (both pdfplumber and pypdf) for '{filename}': {exc}"
        ) from exc
