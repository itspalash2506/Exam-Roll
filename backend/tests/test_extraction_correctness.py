"""
Regression tests for extraction correctness — written BEFORE the fix (P03).

These pin the two critical data-loss/corruption defects from the 2026-08-31 audit:

  P0-1  pdf_extractor keeps only the FIRST roll number per page (re.search stops
        at match one), so every student after the first on a page is silently
        dropped — and the survivor is credited with every subject code anywhere
        on the page.  FUTURE.md §P0-1.

  P0-2  5-6 digit roll numbers also match the subject-code pattern, so they are
        extracted as roll numbers AND classified as subjects, becoming columns
        in the delivered workbook.  FUTURE.md §P0-2.

Tests that fail against today's code are marked `xfail(strict=True)`: CI stays
green, but the suite records the defect and will fail loudly the moment a fix
lands without this file being updated (strict xfail turns an unexpected PASS
into a failure).

The page fixtures are taken verbatim from FUTURE.md §P0-1 and §P0-2.
"""
from unittest.mock import patch

import pytest

import app.services.extractors.pdf_extractor as px
from app.services.extractors.excel_extractor import _is_subject_code
from app.utils.subject_utils import extract_all_subjects


# ── Page fixtures (verbatim from FUTURE.md) ──────────────────────────────────

# P0-1: three students on ONE page, one named subject.
MULTI_STUDENT_PAGE = (
    "MBAN301 - Business Mathematics\n"
    "Roll No: 10001  Priya S\nRoll No: 10002  Arjun K\nRoll No: 10003  Meera R\n"
)

# P0-2: bare subject codes (no "CODE - Name" pair), so the `named` fallback in
# pdf_extractor cannot mask roll numbers leaking into the subject map.
BARE_CODE_PAGE = (
    "Attestation Sheet\nMBAN301   MBAN302\n"
    "Roll No: 10001\nRoll No: 10002\nRoll No: 10003\n"
)

# Roll numbers listed in a column with no "Roll No:" label at all.
BARE_COLUMN_PAGE = (
    "MBAN301 - Business Mathematics\n"
    "Sl. No.   Roll Number   Signature\n"
    "1   10001\n2   10002\n3   10003\n4   10004\n"
)

# The current production shape: one student per page, three pages.
ONE_PER_PAGE_PAGES = [
    "Roll No: 10001  MBAN301 Business Mathematics  MBAN302 Accountancy",
    "Roll No: 10002  MBAN301 Business Mathematics  MBAN303 Economics",
    "Roll No: 10003  MBAN302 Accountancy  MBAN303 Economics",
]

# A 40-page document that legitimately yields exactly one student: the roll
# appears on page 1 only, the other 39 pages are headers and signature blocks.
# The yield is 1-of-40 both before and after the P0-1 fix, so the honesty
# warning is expected in either case.
LOW_YIELD_PAGES = [
    "ATTESTATION SHEET\nMBAN301 - Business Mathematics\nRoll No: 10001  Priya S"
] + [
    "ATTESTATION SHEET (continued)\nMBAN301 - Business Mathematics\n"
    "Signature of Invigilator ____________\n"
] * 39


def _extract(pages):
    """Run the PDF extractor over pre-rendered page texts."""
    with patch.object(px, "_extract_page_texts", return_value=pages):
        return px.extract_from_pdf_with_stats(b"", "x.pdf")


# ── P0-1 · every student on a page must be extracted ─────────────────────────

@pytest.mark.xfail(
    strict=True,
    reason="P0-1 not fixed yet: re.search() keeps only the first roll per page",
)
def test_multiple_students_on_one_page_are_all_extracted():
    students, subjects, _, _ = _extract([MULTI_STUDENT_PAGE])

    assert {s.roll_number for s in students} == {"10001", "10002", "10003"}, (
        "P0-1: students after the first on a page are silently discarded"
    )
    assert set(subjects) == {"MBAN301"}


@pytest.mark.xfail(
    strict=True,
    reason="P0-1 not fixed yet: no bare-roll fallback for unlabelled columns",
)
def test_bare_column_roll_layout():
    """Rolls listed one per line with no 'Roll No:' prefix must still be found."""
    students, _, _, _ = _extract([BARE_COLUMN_PAGE])

    assert {s.roll_number for s in students} == {"10001", "10002", "10003", "10004"}, (
        "P0-1: a bare roll-number column yields no students at all today"
    )


# ── P0-2 · roll numbers must never be classified as subject codes ────────────

@pytest.mark.xfail(
    strict=True,
    reason=r"P0-2 not fixed yet: \d{5,6} matches roll numbers as subject codes",
)
def test_roll_numbers_never_become_subject_codes():
    students, subjects, _, _ = _extract([BARE_CODE_PAGE])

    # Asserted first so the recorded failure pins P0-2 (corruption) rather than
    # P0-1 (the student count, which is wrong on this fixture too).
    assert set(subjects) == {"MBAN301", "MBAN302"}, (
        f"P0-2: roll numbers leaked into the subject map: {sorted(subjects)}"
    )
    for s in students:
        assert s.roll_number not in s.subjects, (
            f"P0-2: student {s.roll_number} was enrolled in their own roll number"
        )
    assert len(students) == 3


@pytest.mark.xfail(
    strict=True,
    reason=r"P0-2 not fixed yet: excel_extractor._is_subject_code accepts \d{5,6}",
)
def test_xlsx_header_202401_is_not_a_subject():
    """A session/batch header cell like '202401' must not become a column."""
    assert _is_subject_code("MBAN301") is True  # real codes keep working
    assert _is_subject_code("202401") is False, (
        "P0-2: the session header '202401' is treated as a subject code"
    )


# ── P0-1 honesty check · low extraction yield must warn ──────────────────────

@pytest.mark.xfail(
    strict=True,
    reason="P0-1 not fixed yet: no low-yield warning, so data loss stays silent",
)
@pytest.mark.asyncio
async def test_low_yield_warning(client):
    """A 40-page document yielding 1 student must tell the user, not complete green."""
    with patch.object(px, "_extract_page_texts", return_value=LOW_YIELD_PAGES):
        files = [("files", ("low_yield.pdf", b"%PDF-1.4 dummy", "application/pdf"))]
        res = await client.post("/api/v1/upload", files=files)
        assert res.status_code == 200
        job_id = res.json()["job_id"]

    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert job["total_students"] == 1

    warnings = job["warnings"]
    low_yield = [w for w in warnings if "40" in w and "student" in w.lower()]
    assert low_yield, (
        "P0-1: 1 student across 40 pages completed with no warning at all "
        f"(warnings={warnings!r})"
    )


# ── Behaviour that must keep working ─────────────────────────────────────────

def test_one_student_per_page_still_works():
    """The current attestation shape — the one layout P0-1 does not break."""
    students, subjects, sample, pages = _extract(ONE_PER_PAGE_PAGES)

    assert pages == 3
    assert {s.roll_number for s in students} == {"10001", "10002", "10003"}
    assert sample

    # Each student keeps the codes printed on their own page.
    by_roll = {s.roll_number: set(s.subjects) for s in students}
    assert {"MBAN301", "MBAN302"} <= by_roll["10001"]
    assert {"MBAN301", "MBAN303"} <= by_roll["10002"]
    assert {"MBAN302", "MBAN303"} <= by_roll["10003"]
    assert {"MBAN301", "MBAN302", "MBAN303"} <= set(subjects)


def test_pin_and_phone_numbers_are_not_subject_codes():
    """Existing behaviour (2026-07-07): labelled PINs/phones are not subjects."""
    text = (
        "MBAN301 - Business Mathematics\n"
        "Address: Jabalpur PIN-482001\n"
        "Correspondence pin: 482002\n"
        "Phone: 982233 Mobile 912345 tel 445566\n"
    )
    subjects = extract_all_subjects(text)

    assert "MBAN301" in subjects
    for junk in ["482001", "482002", "982233", "912345", "445566"]:
        assert junk not in subjects, f"{junk} was classified as a subject code"


def test_labelled_numeric_subject_code_is_still_detected():
    """Guard for the P0-2 fix: numeric codes with positive evidence must survive."""
    paired = extract_all_subjects("210236 - Organisational Behaviour\n")
    assert "210236" in paired
    assert paired["210236"] == "Organisational Behaviour"

    labelled = extract_all_subjects("Subject Code: 210242 Financial Management\n")
    assert "210242" in labelled
