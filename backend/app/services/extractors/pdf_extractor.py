import re
import logging
from io import BytesIO
from typing import NamedTuple

import pdfplumber

from app.schemas.schemas import StudentRecord
from app.utils.file_utils import clean_text
from app.utils.student_utils import (
    clean_student_name,
    derive_admission_year,
    normalize_status,
)
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

# P0-1 — one pattern covering every labelled roll form, scanned per LINE with
# finditer so a page listing 30-60 students yields 30-60 students. The old code
# used .search() per page, which returns the first match and stops.
# The label ends in an explicit "No", and the captured token must contain a
# digit. Without both guards, `Enroll\w*` backtracks to "Enroll" and — because
# IGNORECASE lets [A-Z0-9] match lowercase — captures the "ment" of
# "Enrollment" as a roll number.
_TOKEN = r"((?=[A-Za-z0-9]*\d)[A-Za-z0-9]{4,15})"

_ROLL_LABEL_RE = re.compile(rf"Roll\.?\s*No\.?\s*[:\-]?\s*{_TOKEN}", re.IGNORECASE)
_ENROLL_LABEL_RE = re.compile(
    rf"(?:Enrol(?:l?ment)?|Reg(?:istration)?)\.?\s*No\.?\s*[:\-]?\s*{_TOKEN}",
    re.IGNORECASE,
)

# Attestation sheets print BOTH a roll number and an enrollment number for the
# same student. They are tried in this order and the first form that hits on a
# page wins for that page, so one student never becomes two records.
_ROLL_PATTERNS = (_ROLL_LABEL_RE, _ENROLL_LABEL_RE)

# Bare-column layouts: rolls listed with no label at all, one per line,
# optionally preceded by a serial number. Only used when a page yielded no
# labelled roll, so it cannot fight the labelled forms above.
_BARE_ROLL_RE = re.compile(r"^\s*(?:\d{1,3}[.)]?\s+)?(\d{5,12})\s*$")

# Status text on an attestation row or in the page header (§14.1).
_STATUS_RE = re.compile(
    r"\b(regular|reg|ex[\s\-]?student|ex|atkt|at\s*kt|back\s*log|backlog|"
    r"supplementary|suppl?|private|pvt|external|non[\s\-]?collegiate)\b",
    re.IGNORECASE,
)

# A labelled status must be read from the VALUE, not the label. The real sheets
# print "Regular/Backlog : ATKT", where a bare keyword scan hits the "Regular"
# in the label and reports every backlog candidate as regular.
_STATUS_LABEL_RE = re.compile(
    r"(?:Regular\s*/\s*Backlog|Candidate\s*Type|Student\s*Type|Status)"
    r"\s*[:\-]\s*([^\n\r]{1,40})",
    re.IGNORECASE,
)

# Name text following a roll on the same row: letters, spaces, dots.
_NAME_RE = re.compile(r"^[\s:\-]*([A-Za-z][A-Za-z.\s]{2,80}?)(?=\s{2,}|\s*$|\s+[A-Z]{2,6}\d{3,4}\b)")

# One-student-per-page attestation sheets put the name on its own labelled
# line instead of on the roll row. Father's/Mother's/Guardian's names sit on
# identically-shaped lines directly below, so they are excluded explicitly.
_NAME_LABEL_RE = re.compile(
    r"^[ \t]*Name[ \t]*[:\-][ \t]*([^\n\r]{2,120})$", re.IGNORECASE | re.MULTILINE
)
_RELATION_RE = re.compile(r"(father|mother|guardian|husband)", re.IGNORECASE)


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

    # Pass 1 — locate every roll number in the document first, so they can be
    # excluded from subject detection (P0-2). A roll found anywhere in a
    # document is never a subject code in that same document.
    page_hits: list[list[_RollHit]] = [_scan_page_rolls(t) for t in page_texts]
    all_rolls = {hit.roll for hits in page_hits for hit in hits}

    # Pass 2 — subjects, with the roll numbers excluded.
    all_subjects: dict[str, str] = extract_all_subjects(full_text, exclude=all_rolls)

    merged: dict[str, set[str]] = {}
    details: dict[str, _RollHit] = {}

    for page_text, hits in zip(page_texts, page_hits):
        if not page_text.strip():
            continue

        page_subjects = extract_all_subjects(page_text, exclude=all_rolls)
        page_codes = set(page_subjects)

        for hit in hits:
            # Codes on the student's own line win; a line with none inherits the
            # page's codes, which is the one-student-per-page attestation shape.
            line_codes = set(
                extract_all_subjects(hit.line, exclude=all_rolls)
            )
            codes = line_codes or page_codes
            if codes:
                merged.setdefault(hit.roll, set()).update(codes)
            else:
                merged.setdefault(hit.roll, set())
            # Keep the first non-empty name/status seen for a roll.
            existing = details.get(hit.roll)
            if existing is None or (not existing.name and hit.name):
                details[hit.roll] = hit

        # Promote any named subjects found on this page to the global map
        for code, name in page_subjects.items():
            if name and (code not in all_subjects or not all_subjects[code]):
                all_subjects[code] = name

    students: list[StudentRecord] = []
    for roll in merged:
        hit = details.get(roll)
        raw_status = hit.status if hit else None
        status, _recognised = normalize_status(raw_status)
        students.append(
            StudentRecord(
                roll_number=roll,
                subjects=sorted(merged[roll]),
                name=clean_student_name(hit.name if hit else None),
                status=status,
                admission_year=derive_admission_year(roll),
                status_explicit=bool(raw_status and raw_status.strip()),
            )
        )

    # Prefer subjects that have names; fall back to nameless codes if none do
    named = {k: v for k, v in all_subjects.items() if v}
    final_subjects = named if named else all_subjects

    return students, final_subjects, text_sample, len(page_texts)


class _RollHit(NamedTuple):
    roll: str
    line: str
    name: str | None
    status: str | None


def _scan_page_rolls(page_text: str) -> list[_RollHit]:
    """Every roll number on a page, with the line it came from.

    P0-1 — scans line by line with finditer, so all students on a page are
    found. Falls back to the bare-column layout only when the page carries no
    labelled roll at all.
    """
    if not page_text.strip():
        return []

    lines = page_text.split("\n")
    page_status = _find_status(page_text)
    page_name = _find_labelled_name(page_text)

    for pattern in _ROLL_PATTERNS:
        hits: list[_RollHit] = []
        for line in lines:
            for m in pattern.finditer(line):
                hits.append(
                    _RollHit(
                        roll=m.group(1).strip(),
                        line=line,
                        name=_find_name(line[m.end():]),
                        status=_find_status(line) or page_status,
                    )
                )
        if hits:
            # A page-level "Name :" line identifies the student only when the
            # page describes exactly one; on a 40-student roll list it would
            # give all 40 the same name.
            if len(hits) == 1 and page_name and not hits[0].name:
                hits = [hits[0]._replace(name=page_name)]
            return hits

    hits = []

    for line in lines:
        m = _BARE_ROLL_RE.match(line)
        if m:
            hits.append(
                _RollHit(
                    roll=m.group(1).strip(),
                    line=line,
                    name=None,
                    status=page_status,
                )
            )
    return hits


def _find_labelled_name(page_text: str) -> str | None:
    """The student's own 'Name :' line, ignoring parents' and guardians'."""
    for m in _NAME_LABEL_RE.finditer(page_text):
        line_start = page_text.rfind("\n", 0, m.start()) + 1
        if _RELATION_RE.search(page_text[line_start:m.start(1)]):
            continue
        candidate = m.group(1).strip()
        if candidate:
            return candidate
    return None


def _find_status(text: str) -> str | None:
    """A labelled status wins over a bare keyword anywhere in the text."""
    label = _STATUS_LABEL_RE.search(text)
    if label:
        value = label.group(1).strip()
        inner = _STATUS_RE.search(value)
        if inner:
            return inner.group(1)

    m = _STATUS_RE.search(text)
    return m.group(1) if m else None


def _find_name(text: str) -> str | None:
    m = _NAME_RE.match(text)
    if not m:
        return None
    candidate = m.group(1).strip()
    # A status word alone is not a name.
    if _STATUS_RE.fullmatch(candidate):
        return None
    return candidate or None


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

            # Release pdfplumber's per-page caches. Without this, the
            # char-level object graph for every page stays alive until the
            # whole document is done, so memory grows linearly with page
            # count: a real 168-page attestation sheet peaked at ~600 MB,
            # which the 512 MB free-tier container OOM-kills mid-job (the
            # request then 502s and the ephemeral DB is wiped on restart).
            # Flushing per page drops the same document to ~12 MB.
            page.flush_cache()
            page.get_textmap.cache_clear()

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
