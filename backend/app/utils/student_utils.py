"""Per-student field derivation for attestation sheets (FUTURE.md §14.1).

Status and admission year are captured at extraction time because doing it
later means re-uploading every attestation sheet.
"""
import re
from datetime import date

from app.schemas.schemas import StudentStatus

# Spellings seen on real attestation sheets, mapped to the enum. Keys are
# compared after lowercasing and collapsing punctuation/whitespace, so
# "Ex-Student", "ex student" and "EX  STUDENT" all land on the same entry.
STATUS_ALIASES: dict[str, StudentStatus] = {
    "regular": StudentStatus.REGULAR,
    "reg": StudentStatus.REGULAR,
    "rglr": StudentStatus.REGULAR,
    "fresh": StudentStatus.REGULAR,
    "ex": StudentStatus.EX,
    "ex student": StudentStatus.EX,
    "exstudent": StudentStatus.EX,
    "former": StudentStatus.EX,
    "atkt": StudentStatus.ATKT,
    "at kt": StudentStatus.ATKT,
    "allowed to keep term": StudentStatus.ATKT,
    "back": StudentStatus.ATKT,
    "backlog": StudentStatus.ATKT,
    "supplementary": StudentStatus.ATKT,
    "supply": StudentStatus.ATKT,
    "suppl": StudentStatus.ATKT,
    "private": StudentStatus.PRIVATE,
    "pvt": StudentStatus.PRIVATE,
    "external": StudentStatus.PRIVATE,
    "non collegiate": StudentStatus.PRIVATE,
}

_PUNCT_RE = re.compile(r"[^a-z0-9]+")

# The earliest admission year a roll prefix may encode. Rolls are 8 digits with
# a 2-digit year prefix, so "15" means 2015; anything outside 15..current year
# is a coincidence (a marks column, a PIN fragment), not an admission year.
_MIN_ADMISSION_YY = 15

_NAME_MAX = 120
_UNPRINTABLE_RE = re.compile(r"[^\x20-\x7E -￿]")


def normalize_status(raw: str | None) -> tuple[StudentStatus, bool]:
    """Map a sheet's status text to the enum.

    Returns (status, recognised). `recognised` is False when the text was
    present but unknown — the caller warns with a count rather than defaulting
    silently. Absent text returns (REGULAR, True) and is counted separately by
    the caller, which warns about defaulted students as §14.1 requires.
    """
    if raw is None or not raw.strip():
        return StudentStatus.REGULAR, True

    key = _PUNCT_RE.sub(" ", raw.strip().lower()).strip()
    if key in STATUS_ALIASES:
        return STATUS_ALIASES[key], True

    # "Regular Candidate", "ATKT (Sem II)" — the category is the leading token
    # run; try progressively shorter prefixes before giving up.
    parts = key.split()
    for end in range(len(parts), 0, -1):
        prefix = " ".join(parts[:end])
        if prefix in STATUS_ALIASES:
            return STATUS_ALIASES[prefix], True

    return StudentStatus.OTHER, False


def derive_admission_year(roll: str) -> int | None:
    """Admission year from an 8-digit roll's first two digits, or None.

    Guarded by a plausibility range: without it a roll like '99123456' would
    claim admission year 2099.
    """
    if len(roll) != 8 or not roll.isdecimal():
        return None

    yy = int(roll[:2])
    current_yy = date.today().year % 100
    if yy < _MIN_ADMISSION_YY or yy > current_yy:
        return None
    return 2000 + yy


def clean_student_name(raw: str | None) -> str:
    """Printable, <=120 chars. Missing names are '' with no warning (Q11)."""
    if not raw:
        return ""
    name = _UNPRINTABLE_RE.sub(" ", raw)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:_NAME_MAX]
