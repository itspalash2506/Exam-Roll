"""Student.roll_sort_key (§18, FUTURE_UNIFIED.md; DECISIONS.md 2026-09-19).

A DIFFERENT thing from subject_utils._natural_sort_key, which returns a
Python tuple for in-process `sorted(key=...)` calls — that tuple can't be
stored in a column or used in a SQL `ORDER BY`. This module produces a flat,
storable STRING with the same "digits compare by value" property, computed
once at insert so every future query can `ORDER BY roll_sort_key` and get a
numerically-correct order without re-deriving it — the single cause the
project's own history names for "output is not ascending" complaints (mixed
text/number roll storage in the source workbook this schema replaces).
"""

import re

# Digit runs get zero-padded to this width before comparison, so "9" sorts
# before "10" (lexicographic string comparison alone would put "10" first).
# 12 digits comfortably covers every roll format actually seen (8-digit
# year-prefixed university rolls, shorter legacy formats) with headroom.
_DIGIT_PAD_WIDTH = 12

_CHUNK_RE = re.compile(r"(\d+)")


def roll_sort_key(roll: str) -> str:
    """Return a flat string such that ordinary lexicographic ORDER BY on it
    matches a natural (numeric-aware) sort of the original roll numbers.

    Each digit run is zero-padded to _DIGIT_PAD_WIDTH and each non-digit run
    is lowercased, then everything is concatenated — no separator needed,
    since alternating digit/non-digit chunks from re.split already can't be
    ambiguous about where one chunk ends and the next begins.
    """
    parts = []
    for chunk in _CHUNK_RE.split(roll):
        if chunk.isdecimal():
            parts.append(chunk.zfill(_DIGIT_PAD_WIDTH))
        else:
            parts.append(chunk.lower())
    return "".join(parts)
