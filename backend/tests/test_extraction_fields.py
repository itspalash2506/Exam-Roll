"""
Tests for the §14 extraction extensions: per-student status/name/admission year,
per-paper codes, and the §14.4 subject-conflict rule.

FUTURE_UNIFIED.md §14.5 lists five tests. Four are here. The fifth —
"two uploads of the same college's sheet → second run reports 'N already
enrolled', zero new Student rows" — needed the `students`/`enrollments`
tables from migration `0002_exam_model`; now that it exists, that test (plus
the cross-job version of the §14.4 conflict rule, which needs a real
SubjectOffering row to conflict against) lives in test_exam_model.py. The
determinism test at the bottom of this file still stands — it covers the
property the re-upload test relies on staying true.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import app.services.extractors.pdf_extractor as px
from app.schemas.schemas import StudentRecord, StudentStatus
from app.services.pipeline.processor import (
    merge_subject_maps,
    summarize_status_warnings,
)
from app.utils.student_utils import derive_admission_year, normalize_status

GOLDEN_DIR = Path(__file__).parent / "golden"


def _extract(pages):
    with patch.object(px, "_extract_page_texts", return_value=pages):
        return px.extract_from_pdf_with_stats(b"", "x.pdf")


# ── §14.5 · status vocabulary ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Regular", StudentStatus.REGULAR),
        ("REGULAR", StudentStatus.REGULAR),
        ("reg", StudentStatus.REGULAR),
        ("Ex", StudentStatus.EX),
        ("Ex-Student", StudentStatus.EX),
        ("ex student", StudentStatus.EX),
        ("ATKT", StudentStatus.ATKT),
        ("At KT", StudentStatus.ATKT),
        ("Backlog", StudentStatus.ATKT),
        ("Supplementary", StudentStatus.ATKT),
        ("Private", StudentStatus.PRIVATE),
        ("PVT", StudentStatus.PRIVATE),
        ("External", StudentStatus.PRIVATE),
    ],
)
def test_status_vocabulary_maps_to_enum(raw, expected):
    status, recognised = normalize_status(raw)
    assert status is expected
    assert recognised is True


def test_status_with_trailing_qualifier_still_maps():
    """'ATKT (Sem II)' and 'Regular Candidate' are the category plus noise."""
    assert normalize_status("ATKT (Sem II)")[0] is StudentStatus.ATKT
    assert normalize_status("Regular Candidate")[0] is StudentStatus.REGULAR


def test_unknown_status_becomes_other_and_is_reported():
    status, recognised = normalize_status("Provisional-Repeater")
    assert status is StudentStatus.OTHER
    assert recognised is False

    students = [
        StudentRecord(roll_number="10001", subjects=["CS401"], status=status),
        StudentRecord(roll_number="10002", subjects=["CS401"], status=status),
    ]
    warnings = summarize_status_warnings(students)
    assert any("2 student(s)" in w and "unrecognised status" in w for w in warnings)


# ── §14.5 · missing status is never silent ───────────────────────────────────

def test_no_status_on_a_three_student_page_defaults_and_warns():
    """Three students, no status text → 3 regular AND a warning naming the count."""
    page = (
        "MBAN301 - Business Mathematics\n"
        "Roll No: 10001  Priya S\nRoll No: 10002  Arjun K\nRoll No: 10003  Meera R\n"
    )
    students, _, _, _ = _extract([page])

    assert len(students) == 3
    assert all(s.status is StudentStatus.REGULAR for s in students)
    assert all(s.status_explicit is False for s in students)

    warnings = summarize_status_warnings(students)
    assert len(warnings) == 1
    assert "3 student(s)" in warnings[0]
    assert "Regular" in warnings[0]


def test_explicit_status_does_not_warn():
    page = (
        "MBAN301 - Business Mathematics\n"
        "Roll No: 10001  Priya S  Regular\n"
        "Roll No: 10002  Arjun K  ATKT\n"
    )
    students, _, _, _ = _extract([page])

    by_roll = {s.roll_number: s for s in students}
    assert by_roll["10001"].status is StudentStatus.REGULAR
    assert by_roll["10002"].status is StudentStatus.ATKT
    assert all(s.status_explicit for s in students)
    assert summarize_status_warnings(students) == []


# ── §14.1 · name and admission year ──────────────────────────────────────────

def test_name_is_captured_and_bounded():
    page = "MBAN301 - Business Mathematics\nRoll No: 24136599  Shivani Mishra\n"
    students, _, _, _ = _extract([page])
    assert students[0].name == "Shivani Mishra"


def test_missing_name_is_empty_and_does_not_warn():
    """§14.1 — names are optional on outputs (Q11), so absence is not a warning."""
    students, _, _, _ = _extract(["MBAN301 - Maths\nRoll No: 10001\n"])
    assert students[0].name == ""
    assert "name" not in " ".join(summarize_status_warnings(students)).lower()


@pytest.mark.parametrize(
    "roll,expected",
    [
        ("24136599", 2024),
        ("23100001", 2023),
        ("15000001", 2015),
        ("99123456", None),   # outside 15..current year — not an admission year
        ("14000001", None),   # before the floor
        ("1234567", None),    # not 8 digits
        ("ABCD1234", None),   # not numeric
    ],
)
def test_admission_year_derivation(roll, expected):
    assert derive_admission_year(roll) == expected


# ── §14.5 · subject conflict, nothing auto-picked ────────────────────────────

def test_same_code_different_name_records_conflict_and_picks_neither():
    merged, warnings, conflicts = merge_subject_maps([
        {"MBAN301": "Paper I"},
        {"MBAN301": "Paper II"},
    ])

    assert merged["MBAN301"] == ""
    assert [c.code for c in conflicts] == ["MBAN301"]
    assert conflicts[0].names == ["Paper I", "Paper II"]
    assert "Paper I" in warnings[0] and "Paper II" in warnings[0]


def test_identical_names_across_files_are_not_a_conflict():
    merged, warnings, conflicts = merge_subject_maps([
        {"MBAN301": "Business Mathematics"},
        {"MBAN301": "Business Mathematics"},
    ])
    assert merged["MBAN301"] == "Business Mathematics"
    assert conflicts == []
    assert warnings == []


# ── §14.5 · golden file ──────────────────────────────────────────────────────

def _golden_cases():
    return sorted(GOLDEN_DIR.glob("*.pages.txt"))


@pytest.mark.parametrize("pages_file", _golden_cases(), ids=lambda p: p.stem)
def test_golden_file(pages_file):
    """Page texts in, exact counts/statuses/codes out.

    One synthetic case is committed now; real anonymised sheets per course
    (M.Com, M.A., M.Sc., M.S.W., B.B.LLB) are added in P12.
    """
    expected = json.loads(
        pages_file.with_suffix("").with_suffix(".expected.json").read_text("utf-8")
    )
    pages = pages_file.read_text("utf-8").split("\n---PAGE---\n")

    students, subjects, _, page_count = _extract(pages)

    assert page_count == expected["page_count"]
    assert len(students) == expected["student_count"]
    assert sorted(subjects) == expected["subject_codes"]

    status_counts: dict[str, int] = {}
    for s in students:
        status_counts[str(s.status)] = status_counts.get(str(s.status), 0) + 1
    assert status_counts == expected["status_counts"]

    assert sorted(s.roll_number for s in students) == expected["roll_numbers"]

    # P0-2 guard, asserted on every golden case.
    assert not ({s.roll_number for s in students} & set(subjects))


# ── Determinism (stands in for the deferred re-upload test) ──────────────────

def test_extraction_is_deterministic_across_runs():
    """Same input → byte-identical output.

    The rewrite builds students out of sets and dicts; if iteration order leaked
    into the result, two uploads of one file would disagree and the re-upload
    reconciliation in P09 would report phantom changes.
    """
    pages = [
        "MBAN301 - Business Mathematics  MBAN302 - Accountancy\n"
        "Roll No: 10003  Meera R  ATKT\n"
        "Roll No: 10001  Priya S  Regular\n"
        "Roll No: 10002  Arjun K\n"
    ]
    first = _extract(pages)[0]
    for _ in range(3):
        again = _extract(pages)[0]
        assert [s.model_dump() for s in again] == [s.model_dump() for s in first]
