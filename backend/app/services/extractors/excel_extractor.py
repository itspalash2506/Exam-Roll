import re
import logging
import zipfile
from io import BytesIO

import openpyxl

from app.config import get_settings
from app.schemas.schemas import StudentRecord
from app.utils.student_utils import derive_admission_year
from app.utils.subject_utils import extract_all_subjects, normalize_subject_name

logger = logging.getLogger(__name__)

_CODE_RE = re.compile(r"\b([A-Z]{2,6}\d{3,4}|\d{5,6})\b")

# A .xlsx is a ZIP archive; the declared uncompressed size in its central
# directory is attacker-controlled, so this is a cheap first filter, not the
# whole defence — the row/col cap in _read_rows is what actually bounds
# memory once openpyxl starts reading (P1-11, DECISIONS.md 2026-09-20).
_MAX_ZIP_RATIO = 120
_MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


def _reject_zip_bomb(file_bytes: bytes, filename: str) -> None:
    try:
        with zipfile.ZipFile(BytesIO(file_bytes)) as zf:
            total = sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"Cannot open Excel file '{filename}': {exc}") from exc
    if total > _MAX_UNCOMPRESSED_BYTES or total > len(file_bytes) * _MAX_ZIP_RATIO:
        raise RuntimeError(
            f"'{filename}': archive expands to {total / 1024**2:.0f} MB — rejected"
        )

# Column header names that indicate the roll number column
_ROLL_HEADER_NAMES = frozenset(
    {"roll no", "rollno", "roll number", "roll_no", "enrollment", "enrolment", "roll"}
)


def extract_from_excel(
    file_bytes: bytes, filename: str
) -> tuple[list[StudentRecord], dict[str, str], str]:
    """Extract students, subjects, and a text sample from an Excel file.

    Auto-detects one of two layouts:
      Format A — Matrix: header row contains subject codes as columns, rows are students
      Format B — Flat list: a column holds comma/space-separated paper codes per student

    Returns:
        students    — list of StudentRecord
        subjects    — {code: name} dict
        text_sample — first ~3000 chars of row data as text, for AI classifier
    """
    students, subjects, text_sample, _row_count, _truncated = extract_from_excel_with_stats(
        file_bytes, filename
    )
    return students, subjects, text_sample


def _read_rows(ws, max_rows: int, max_cols: int) -> tuple[list[tuple], bool]:
    """Stream rows, honouring the caps that make read_only=True worth using.

    Materialising every row into a list (the previous behaviour) defeated
    read_only entirely: a ~2 MB upload can declare 1M+ rows, and openpyxl
    would hold all of them at once regardless of the flag. Returns
    (rows, truncated) — a truncated read is reported to the user rather than
    silently producing a partial roster (P1-11, DECISIONS.md 2026-09-20).
    """
    rows: list[tuple] = []
    truncated = False
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i >= max_rows:
            truncated = True
            break
        if any(cell is not None for cell in row):
            rows.append(row[:max_cols])
    return rows, truncated


def extract_from_excel_with_stats(
    file_bytes: bytes, filename: str
) -> tuple[list[StudentRecord], dict[str, str], str, int, bool]:
    """Same extraction as extract_from_excel, plus the real data-row count
    for progress reporting and whether the sheet was truncated by the row cap."""
    settings = get_settings()
    _reject_zip_bomb(file_bytes, filename)

    try:
        wb = openpyxl.load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as exc:
        raise RuntimeError(f"Cannot open Excel file '{filename}': {exc}") from exc

    try:
        ws = _choose_sheet(wb)
        all_rows, truncated = _read_rows(
            ws, settings.max_rows_per_sheet, settings.max_cols_per_sheet
        )
    finally:
        wb.close()

    if truncated:
        logger.warning(
            "'%s': sheet exceeds %d rows — only the first rows were read",
            filename, settings.max_rows_per_sheet,
        )

    if not all_rows:
        return [], {}, "", 0, truncated

    header_row = [str(c).strip() if c is not None else "" for c in all_rows[0]]
    data_rows = all_rows[1:]

    # Detect format by checking how many subject codes appear in the header
    header_codes = [h for h in header_row if _is_subject_code(h)]

    if len(header_codes) >= 2:
        students, subjects = _extract_format_a(header_row, data_rows, header_codes)
        logger.debug("Excel '%s' detected as Format A (matrix), %d codes in header", filename, len(header_codes))
    else:
        students, subjects = _extract_format_b(header_row, data_rows, filename)
        logger.debug("Excel '%s' detected as Format B (flat list)", filename)

    # Build text sample from the first few rows
    text_lines = ["\t".join(header_row)]
    for row in data_rows[:10]:
        text_lines.append("\t".join(str(c) if c is not None else "" for c in row))
    text_sample = "\n".join(text_lines)[:3000]

    return students, subjects, text_sample, len(data_rows), truncated


# ── Format A: matrix / Split Subjects layout ─────────────────────────────────

def _extract_format_a(
    header_row: list[str],
    data_rows: list[tuple],
    header_codes: list[str],
) -> tuple[list[StudentRecord], dict[str, str]]:
    roll_col = _find_roll_col(header_row)

    # If no named roll column, pick the first column that holds numeric values
    if roll_col is None:
        for row in data_rows[:5]:
            for i, cell in enumerate(row):
                if cell is not None and str(cell).strip().isdigit():
                    roll_col = i
                    break
            if roll_col is not None:
                break
        roll_col = roll_col if roll_col is not None else 0

    # Map column index → subject code for every code column
    code_at: dict[int, str] = {
        idx: col
        for idx, col in enumerate(header_row)
        if _is_subject_code(col)
    }

    students: list[StudentRecord] = []
    for row in data_rows:
        if not row or all(c is None for c in row):
            continue

        roll = _cell_str(row, roll_col)
        if not roll or roll.lower() in {"none", "roll no", "roll number", "s.no", "sno"}:
            continue

        enrolled = [
            code
            for idx, code in code_at.items()
            if idx < len(row) and _truthy(row[idx])
        ]
        if enrolled:
            students.append(
                StudentRecord(
                    roll_number=roll,
                    subjects=sorted(enrolled),
                    admission_year=derive_admission_year(roll),
                    # Spreadsheet layouts carry no status column; the `regular`
                    # default is therefore never explicit and must be warned on.
                    status_explicit=False,
                )
            )

    # Subject map: codes are known from the header; names are empty (no name row present)
    subjects: dict[str, str] = {code: "" for code in header_codes}
    return students, subjects


# ── Format B: flat list layout ───────────────────────────────────────────────

def _extract_format_b(
    header_row: list[str],
    data_rows: list[tuple],
    filename: str,
) -> tuple[list[StudentRecord], dict[str, str]]:
    roll_col = _find_roll_col(header_row)
    if roll_col is None:
        # Heuristic: first column with numeric-looking values in top rows
        roll_col = _infer_roll_col(data_rows) or 1

    paper_col = _find_paper_col(header_row, data_rows)
    if paper_col is None:
        logger.warning("No paper code column found in '%s'; no students extracted", filename)
        return [], {}

    students: list[StudentRecord] = []
    all_subjects: dict[str, str] = {}

    for row in data_rows:
        if not row or all(c is None for c in row):
            continue

        roll = _cell_str(row, roll_col)
        if not roll or not roll.replace("-", "").replace("/", "").strip():
            continue
        # Skip header-like values repeated in data rows
        if roll.lower() in {"none", "roll no", "roll number", "s.no", "sno", "serial no"}:
            continue

        cell_text = _cell_str(row, paper_col) if paper_col < len(row) else ""
        # P0-2 — the student's own roll must never be read back as one of their
        # subject codes, which happens whenever the paper cell repeats it.
        codes = [c for c in _CODE_RE.findall(cell_text) if c != roll]
        if not codes:
            continue

        students.append(
            StudentRecord(
                roll_number=roll,
                subjects=sorted(set(codes)),
                admission_year=derive_admission_year(roll),
                status_explicit=False,
            )
        )

        # Extract subject names from cell text if present
        cell_subjects = extract_all_subjects(cell_text, exclude={roll})
        for code, name in cell_subjects.items():
            if name:
                all_subjects.setdefault(code, name)
            else:
                all_subjects.setdefault(code, "")

    all_rolls = {s.roll_number for s in students}
    for roll in all_rolls:
        all_subjects.pop(roll, None)

    return students, all_subjects


# ── Sheet / column helpers ────────────────────────────────────────────────────

def _choose_sheet(wb: openpyxl.Workbook):
    """Prefer 'Split Subjects' → 'Sheet1' → first sheet."""
    lower_to_orig = {n.lower(): n for n in wb.sheetnames}
    for preferred in ("split subjects", "sheet1"):
        if preferred in lower_to_orig:
            return wb[lower_to_orig[preferred]]
    return wb[wb.sheetnames[0]]


def _find_roll_col(header_row: list[str]) -> int | None:
    for i, h in enumerate(header_row):
        if h.lower().strip() in _ROLL_HEADER_NAMES:
            return i
    return None


def _infer_roll_col(data_rows: list[tuple]) -> int | None:
    """Return the index of the first column that holds numeric values in early rows."""
    for row in data_rows[:5]:
        for i, cell in enumerate(row):
            if cell is not None and str(cell).strip().isdigit():
                return i
    return None


def _find_paper_col(header_row: list[str], data_rows: list[tuple]) -> int | None:
    """Return the column index whose cells contain multiple subject codes."""
    for col_idx in range(len(header_row)):
        for row in data_rows[:15]:
            if col_idx >= len(row) or row[col_idx] is None:
                continue
            codes = _CODE_RE.findall(str(row[col_idx]))
            if len(codes) >= 2:
                return col_idx
    return None


def _is_subject_code(val: str) -> bool:
    """True for an unambiguous alphanumeric subject code.

    P0-2 — a bare 5-6 digit value is indistinguishable from a roll number or a
    session header, so `202401` in a header row became a subject column. Numeric
    codes now need positive evidence, which a lone header cell cannot provide;
    they still reach the subject map through `CODE - Name` pairs and explicit
    subject/paper/course labels in `extract_all_subjects`.
    """
    return bool(re.fullmatch(r"[A-Z]{2,6}\d{3,4}", val.strip()))


def _truthy(val) -> bool:
    """Return True if val represents an enrolled / selected cell (1, 'yes', 'x', etc.)."""
    if val is None:
        return False
    s = str(val).strip().lower()
    return s not in {"", "0", "none", "no", "false", "-"}


def _cell_str(row: tuple, col: int) -> str:
    if col >= len(row) or row[col] is None:
        return ""
    return str(row[col]).strip()
