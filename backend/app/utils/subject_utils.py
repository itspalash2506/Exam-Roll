import re
from app.schemas.schemas import StudentRecord, SubjectEntry

# P0-2 — a 5-6 digit roll number matches the same shape as a numeric subject
# code, so a single pattern cannot tell them apart. Alphanumeric codes are
# unambiguous and always accepted; purely numeric codes need positive evidence.
_ALPHA_CODE_RE = re.compile(r"\b([A-Z]{2,6}\d{3,4})\b")

# Positive evidence #1: an explicit subject/paper/course label.
_NUMERIC_CODE_RE = re.compile(
    r"(?:subject|paper|course)\s*(?:code)?\s*[:\-]?\s*(\d{5,6})\b", re.IGNORECASE
)

# Kept for detect_subject_code_pattern and the excel extractor's cell scan,
# where a numeric code is only ever accepted via _PAIR_RE or an explicit label.
_CODE_RE = re.compile(r"\b([A-Z]{2,6}\d{3,4}|\d{5,6})\b")

# Matches "CODE - Name" or "CODE: Name" on a single line. P2-22 — the name is
# non-greedy and stops at the next code, so "MBAN301 - Maths MBAN302 - Physics"
# yields two pairs instead of one swallowing the other.
#
# The separator uses [ \t] rather than \s: \s matches a newline, so a line
# ending in a dash ("PH: 47175-") bound itself to the whole of the next line
# and turned a phone number into a named subject.
_PAIR_RE = re.compile(
    r"\b([A-Z]{2,6}\d{3,4}|\d{5,6})[ \t]*[-:][ \t]*(.+?)(?=\s+(?:[A-Z]{2,6}\d{3,4})\b|$)",
    re.MULTILINE,
)

# Numeric matches preceded by one of these labels are addresses or contact
# numbers, never subject codes. "ph" covers the "PH: 47175" form on letterheads.
_LABEL_CONTEXT_RE = re.compile(
    r"(?:pin|ph|phone|mob(?:ile)?|tel)\b[^a-z0-9]{0,4}$", re.IGNORECASE
)

_SPECIAL_RE = re.compile(r"[^\w\s&/()\-,.]")
_MULTI_SPACE_RE = re.compile(r"\s+")

SUBJECT_ALIASES: dict[str, str] = {
    "maths": "Mathematics",
    "math": "Mathematics",
    "phy": "Physics",
    "phys": "Physics",
    "chem": "Chemistry",
    "bio": "Biology",
    "eng": "English",
    "cs": "Computer Science",
    "comp sci": "Computer Science",
    "it": "Information Technology",
    "eco": "Economics",
    "hist": "History",
    "geo": "Geography",
    "pol sci": "Political Science",
    "account": "Accountancy",
    "accountancy": "Accountancy",
    "stat": "Statistics",
}


def detect_subject_code_pattern(text: str) -> str:
    """Return a regex pattern for the most common subject code prefix in text.

    Finds all codes matching [A-Z]{2,6}\\d{3,4}, groups by letter prefix,
    and returns the prefix pattern that appears at least twice.
    """
    codes = [c for c in _CODE_RE.findall(text) if not c.isdigit()]
    if len(codes) < 2:
        return r"[A-Z]{2,6}\d{3,4}"

    prefix_counts: dict[str, int] = {}
    for code in codes:
        m = re.match(r"([A-Z]+)", code)
        if m:
            p = m.group(1)
            prefix_counts[p] = prefix_counts.get(p, 0) + 1

    frequent = {p: c for p, c in prefix_counts.items() if c >= 2}
    if not frequent:
        return r"[A-Z]{2,6}\d{3,4}"

    top = max(frequent, key=lambda p: frequent[p])
    return rf"{re.escape(top)}\d+"


def _is_address_number(text: str, start: int) -> bool:
    """True when a numeric match is preceded by a PIN/phone/mobile/tel label."""
    return bool(_LABEL_CONTEXT_RE.search(text[max(0, start - 20):start]))


def extract_all_subjects(
    text: str, exclude: set[str] | None = None
) -> dict[str, str]:
    """Return {code: name} for all subject codes found in text.

    `exclude` holds roll numbers seen in the same document. A roll number found
    in a document is never a subject code in that same document (P0-2) — without
    this, 5-6 digit rolls become columns in the delivered workbook.

    Named subjects come from 'CODE - Name' / 'CODE: Name' patterns. Lone
    alphanumeric codes are included with an empty name; a lone *numeric* code is
    only accepted with an explicit subject/paper/course label, because it is
    otherwise indistinguishable from a roll number.
    """
    exclude = exclude or set()
    result: dict[str, str] = {}

    # First pass: paired codes with names. A "CODE - Name" pair is itself
    # positive evidence, so numeric codes are accepted here without a label.
    for m in _PAIR_RE.finditer(text):
        code = m.group(1).strip()
        raw_name = m.group(2).strip()

        if code in exclude:
            continue
        if code.isdecimal() and _is_address_number(text, m.start()):
            continue

        # Trim trailing garbage (excess punctuation, tab-separated columns)
        raw_name = re.split(r"\s{2,}|\t", raw_name)[0].strip()
        raw_name = re.sub(r"[\s,;.]+$", "", raw_name).strip()
        if len(raw_name) > 2:
            result[code] = normalize_subject_name(raw_name)

    # Second pass: lone alphanumeric codes not yet seen.
    for m in _ALPHA_CODE_RE.finditer(text):
        code = m.group(1).strip()
        if code not in result and code not in exclude:
            result[code] = ""

    # Third pass: lone numeric codes, label-gated.
    for m in _NUMERIC_CODE_RE.finditer(text):
        code = m.group(1).strip()
        if code not in result and code not in exclude:
            result[code] = ""

    return result


def normalize_subject_name(name: str) -> str:
    """Title-case, strip extra whitespace, remove unusual special chars."""
    name = _SPECIAL_RE.sub("", name)
    name = _MULTI_SPACE_RE.sub(" ", name).strip()
    lower = name.lower()

    # P2-21 — expand the abbreviation but KEEP the remainder. Returning the
    # canonical name alone renamed "Eng Drawing" to "English" in the delivered
    # workbook. Longest alias first, so the result no longer depends on dict
    # insertion order when two aliases both prefix-match.
    for alias in sorted(SUBJECT_ALIASES, key=len, reverse=True):
        canonical = SUBJECT_ALIASES[alias]
        if lower == alias:
            return canonical
        if lower.startswith(alias + " "):
            rest = name[len(alias):].strip()
            return f"{canonical} {rest.title()}".strip()

    return name.title()


def sort_subjects(subjects: dict[str, str]) -> list[SubjectEntry]:
    """Sort subjects by numeric suffix of their code (MBAN301 before MBAN302)."""

    def _key(entry: SubjectEntry) -> tuple:
        prefix_m = re.match(r"([A-Z]+)", entry.code)
        digits_m = re.search(r"(\d+)", entry.code)
        return (
            prefix_m.group(1) if prefix_m else "",
            int(digits_m.group(1)) if digits_m else 0,
        )

    entries = [SubjectEntry(code=code, name=name) for code, name in subjects.items()]
    return sorted(entries, key=_key)


def _natural_sort_key(roll: str) -> tuple:
    """Split a roll number into alternating text/digit chunks so embedded
    numbers compare by value (R22...4 before R22...20).

    re.split with a capturing digit group always yields non-digit chunks at
    even indices and digit chunks at odd ones, so tuple comparison never pits
    an int against a str at the same position.
    """
    return tuple(
        int(chunk) if chunk.isdecimal() else chunk
        for chunk in re.split(r"(\d+)", roll)
    )


def sort_roll_numbers(rolls: list[str]) -> list[str]:
    """Return a NEW list of roll numbers sorted ascending.

    Purely numeric lists sort by integer value; anything else uses a natural
    (alphanumeric-aware) sort. Stable, side-effect free — the input list is
    never mutated, so stored extraction order stays intact for traceability.
    """
    # P2-23 — isdigit() is True for superscripts ("12³4") but int() raises on
    # them; isdecimal() is exactly the "safe for int()" predicate.
    if all(roll.isdecimal() for roll in rolls):
        return sorted(rolls, key=int)
    return sorted(rolls, key=_natural_sort_key)


def build_subject_roll_map(
    students: list[StudentRecord],
    subjects: list[SubjectEntry],
) -> dict[str, list[str]]:
    """Return {subject_code: [roll_numbers]} for Excel generation.

    Each subject's roll list is sorted ascending at build time (output only —
    the extraction order persisted in the DB is untouched).
    """
    roll_map: dict[str, list[str]] = {s.code: [] for s in subjects}
    for student in students:
        for code in student.subjects:
            if code in roll_map:
                roll_map[code].append(student.roll_number)
    return {code: sort_roll_numbers(rolls) for code, rolls in roll_map.items()}
