import re
from app.schemas.schemas import StudentRecord, SubjectEntry

# Matches Indian college subject codes: 2-6 uppercase letters + 3-4 digits (e.g. MBAN301, CS401), or 5-6 digit numeric codes
_CODE_RE = re.compile(r"\b([A-Z]{2,6}\d{3,4}|\d{5,6})\b")

# Matches "CODE - Name" or "CODE: Name" on a single line
_PAIR_RE = re.compile(r"\b([A-Z]{2,6}\d{3,4}|\d{5,6})\s*[-:]\s*([^\n\r]+)", re.MULTILINE)

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


def extract_all_subjects(text: str) -> dict[str, str]:
    """Return {code: name} for all subject codes found in text.

    Named subjects come from 'CODE - Name' / 'CODE: Name' patterns.
    Lone codes are included with an empty name.
    """
    result: dict[str, str] = {}

    # First pass: paired codes with names
    for m in _PAIR_RE.finditer(text):
        code = m.group(1).strip()
        raw_name = m.group(2).strip()

        if code.isdigit():
            # Check context around the match to filter out PINs, phone numbers, etc.
            start_idx = max(0, m.start() - 20)
            context = text[start_idx:m.start()].lower()
            if "pin" in context or "phone" in context or "mobile" in context or "tel" in context:
                continue

        # Trim trailing garbage (secondary code, excess punctuation, tab-separated columns)
        raw_name = re.split(r"\s{2,}|\t", raw_name)[0].strip()
        raw_name = re.sub(r"[\s,;.]+$", "", raw_name).strip()
        if len(raw_name) > 2:
            result[code] = normalize_subject_name(raw_name)

    # Second pass: lone codes not yet seen
    for m in _CODE_RE.finditer(text):
        code = m.group(1).strip()
        if code not in result:
            if code.isdigit():
                # Check context around the match to filter out PINs, phone numbers, etc.
                start_idx = max(0, m.start() - 20)
                context = text[start_idx:m.start()].lower()
                if "pin" in context or "phone" in context or "mobile" in context or "tel" in context:
                    continue
            result[code] = ""

    return result


def normalize_subject_name(name: str) -> str:
    """Title-case, strip extra whitespace, remove unusual special chars."""
    name = _SPECIAL_RE.sub("", name)
    name = _MULTI_SPACE_RE.sub(" ", name).strip()
    lower = name.lower()
    for alias, canonical in SUBJECT_ALIASES.items():
        if lower == alias or lower.startswith(alias + " "):
            return canonical
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
        int(chunk) if chunk.isdigit() else chunk
        for chunk in re.split(r"(\d+)", roll)
    )


def sort_roll_numbers(rolls: list[str]) -> list[str]:
    """Return a NEW list of roll numbers sorted ascending.

    Purely numeric lists sort by integer value; anything else uses a natural
    (alphanumeric-aware) sort. Stable, side-effect free — the input list is
    never mutated, so stored extraction order stays intact for traceability.
    """
    if all(roll.isdigit() for roll in rolls):
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
