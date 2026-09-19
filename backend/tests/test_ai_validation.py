"""AI output validation (P0-10, DECISIONS.md 2026-09-19).

Covers: validation.py's three functions directly, and the two places they
plug into the pipeline — extractor.py's roll-number rejection, and
processor.py's apply_ai_subject_labels (the fix for the AI being able to
invent a subject code rule-based extraction never found).
"""

from unittest.mock import patch

from app.schemas.schemas import SubjectEntry
from app.services.ai.validation import (
    validate_roll_number,
    validate_subject_code,
    validate_text_field,
)
from app.services.pipeline.processor import apply_ai_subject_labels


# ── validate_roll_number ────────────────────────────────────────────────────

def test_validate_roll_number_accepts_normal_rolls():
    for roll in ("10001", "A2023001", "2024CS001", "22131345"):
        cleaned, rejected = validate_roll_number(roll)
        assert rejected is False
        assert cleaned == roll


def test_validate_roll_number_rejects_empty():
    cleaned, rejected = validate_roll_number("")
    assert rejected is True
    assert cleaned is None
    cleaned, rejected = validate_roll_number(None)
    assert rejected is True


def test_validate_roll_number_rejects_oversized():
    # Over 15 chars is outside the shape every extractor in this codebase
    # already expects (pdf_extractor._TOKEN).
    huge = "1" * 50
    cleaned, rejected = validate_roll_number(huge)
    assert rejected is True
    assert cleaned is None


def test_validate_roll_number_rejects_control_characters():
    for bad in ("1000\t1", "1000\r1", "1000\n1", "10\x0001"):
        cleaned, rejected = validate_roll_number(bad)
        assert rejected is True, f"{bad!r} should have been rejected"
        assert cleaned is None


def test_validate_roll_number_rejects_no_digit():
    # Must contain at least one digit — a pure-alpha value is never a roll.
    cleaned, rejected = validate_roll_number("ABCDEF")
    assert rejected is True


def test_validate_roll_number_strips_whitespace():
    cleaned, rejected = validate_roll_number("  10001  ")
    assert rejected is False
    assert cleaned == "10001"


# ── validate_subject_code ───────────────────────────────────────────────────

def test_validate_subject_code_accepts_alpha_and_numeric_shapes():
    for code in ("MBAN301", "CS401", "210236"):
        cleaned, rejected = validate_subject_code(code)
        assert rejected is False
        assert cleaned == code


def test_validate_subject_code_rejects_malformed():
    for bad in ("", None, "=HYPERLINK(...)", "X", "1"):
        cleaned, rejected = validate_subject_code(bad)
        assert rejected is True
        assert cleaned is None


def test_validate_subject_code_uppercases():
    cleaned, rejected = validate_subject_code("mban301")
    assert rejected is False
    assert cleaned == "MBAN301"


# ── validate_text_field ─────────────────────────────────────────────────────

def test_validate_text_field_passes_short_values():
    cleaned, truncated = validate_text_field("B.Com", 200)
    assert cleaned == "B.Com"
    assert truncated is False


def test_validate_text_field_truncates_oversized():
    huge = "x" * 500
    cleaned, truncated = validate_text_field(huge, 200)
    assert truncated is True
    assert cleaned == huge[:200]
    assert len(cleaned) == 200


def test_validate_text_field_empty_passes_through_as_none():
    cleaned, truncated = validate_text_field("", 200)
    assert cleaned is None
    assert truncated is False
    cleaned, truncated = validate_text_field(None, 200)
    assert cleaned is None
    assert truncated is False
    cleaned, truncated = validate_text_field("   ", 200)
    assert cleaned is None
    assert truncated is False


# ── extractor.py: malformed rolls are rejected and counted ────────────────

def test_extract_students_ai_rejects_malformed_rolls():
    from app.services.ai.extractor import extract_students_ai

    fake_response = (
        '[{"roll_number": "10001", "subjects": ["MBAN301"]},'
        ' {"roll_number": "' + "9" * 40 + '", "subjects": ["MBAN301"]},'
        ' {"roll_number": "", "subjects": ["MBAN301"]}]'
    )
    with patch(
        "app.services.ai.extractor.get_groq_client"
    ) as mock_get_client:
        mock_get_client.return_value.complete.return_value = fake_response
        students, rejected_count = extract_students_ai(
            "irrelevant text",
            "attestation_sheet",
            [SubjectEntry(code="MBAN301", name="Business Mathematics")],
        )

    assert rejected_count == 2  # the oversized roll and the empty roll
    assert len(students) == 1
    assert students[0].roll_number == "10001"


# ── processor.py: AI may label, never invent, a subject code ──────────────

def test_apply_ai_subject_labels_never_invents_a_code():
    merged_subjects = {"MBAN301": "Business Mathematics", "MBAN302": ""}
    ai_subjects = [
        SubjectEntry(code="MBAN302", name="Accountancy"),  # labels a known code
        SubjectEntry(code="MBAN999", name="Hallucinated Subject"),  # invented
    ]

    merged, invented = apply_ai_subject_labels(merged_subjects, ai_subjects)

    assert merged["MBAN302"] == "Accountancy"  # known code was labelled
    assert "MBAN999" not in merged  # invented code never entered the map
    assert invented == {"MBAN999"}


def test_apply_ai_subject_labels_empty_ai_list_is_a_noop():
    merged_subjects = {"MBAN301": "Business Mathematics"}
    merged, invented = apply_ai_subject_labels(merged_subjects, [])
    assert merged == merged_subjects
    assert invented == set()


def test_apply_ai_subject_labels_does_not_overwrite_with_empty_name():
    merged_subjects = {"MBAN301": "Business Mathematics"}
    ai_subjects = [SubjectEntry(code="MBAN301", name="")]
    merged, invented = apply_ai_subject_labels(merged_subjects, ai_subjects)
    assert merged["MBAN301"] == "Business Mathematics"  # not blanked out
    assert invented == set()
