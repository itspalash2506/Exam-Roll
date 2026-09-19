"""AI output validation (P0-10, DECISIONS.md 2026-09-19).

Every field the Groq classifier/extractor returns is free-form text the
model generated. It has been through no schema enforcement beyond "this key
exists" — nothing checks it looks like a real roll number or subject code,
or that it's a reasonable length. Before this module, none of that was
checked: a malformed or oversized field flowed straight into the DB (where a
Postgres column-width limit will now hard-reject it, see DECISIONS.md) and
into excel_generator.py cells (where workbook_builder.py's safe_cell()
guards against FORMULA injection, but never checked the field was sane in
the first place — a value can be perfectly formula-safe and still garbage).

Every function here follows this codebase's established pattern: never
silently default or silently drop a bad value — reject it and return enough
for the caller to accumulate a count and warn, exactly like the existing
"N students had an unrecognised status" pattern in processor.py's
summarize_status_warnings. A caller that ignores the rejection count has
made the same mistake P0-1 was: a check that silently keeps only the good
data and says nothing about what it threw away.
"""

import re

from app.utils.subject_utils import _CODE_RE

# Same shape as pdf_extractor._TOKEN — the one definition in this codebase of
# "what a roll number looks like": alphanumeric, containing at least one
# digit, 4-15 characters. Reused as an anchored full-match pattern rather
# than re-derived, so the two definitions can never drift apart. Rejects
# anything containing whitespace or control characters by construction,
# since [A-Za-z0-9] never matches either.
_ROLL_TOKEN_RE = re.compile(r"^(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{4,15}$")


def validate_roll_number(raw: str | None) -> tuple[str | None, bool]:
    """Returns (cleaned_roll, rejected).

    A roll number is REJECTED — not silently dropped, not truncated, not
    coerced — if it's empty or doesn't match the alphanumeric-with-a-digit
    shape every extractor in this codebase already expects. The caller is
    responsible for counting rejections and warning; this function only
    decides pass/reject.
    """
    if not raw:
        return None, True
    candidate = raw.strip()
    if not _ROLL_TOKEN_RE.match(candidate):
        return None, True
    return candidate, False


def validate_subject_code(raw: str | None) -> tuple[str | None, bool]:
    """Returns (cleaned_code, rejected).

    Reuses subject_utils._CODE_RE — the one definition in this codebase of
    "what a subject code shape looks like" (alphanumeric like MBAN301, or a
    5-6 digit purely-numeric code) — rather than a new pattern. This is a
    SHAPE check only: whether a value the AI already labelled `code` looks
    like a plausible code at all. It is not the safeguard against the AI
    inventing a code rule-based extraction never found — that's a separate,
    stronger rule enforced in processor.py's matching stage (the AI may only
    label a code already present, never add a new one).
    """
    if not raw:
        return None, True
    candidate = raw.strip().upper()
    if not _CODE_RE.fullmatch(candidate):
        return None, True
    return candidate, False


def validate_text_field(
    raw: str | None, max_length: int
) -> tuple[str | None, bool]:
    """Returns (cleaned, was_truncated).

    Unlike roll numbers and subject codes, a free-text field (course name,
    semester, exam name, notes) has no fixed shape to reject against — the
    only real constraint is length, chiefly because Postgres will hard-reject
    an oversized value at the DB column boundary where SQLite silently
    accepted it (DECISIONS.md, 2026-09-19). So this TRUNCATES rather than
    rejects: a shortened value is still useful, an empty one is not.

    Empty/whitespace-only input passes through as None, untruncated.
    """
    if not raw:
        return None, False
    candidate = raw.strip()
    if not candidate:
        return None, False
    if len(candidate) > max_length:
        return candidate[:max_length], True
    return candidate, False
