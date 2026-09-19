"""Shared Excel-generation safety guard and styling helpers (P0-5).

Excel and LibreOffice treat any cell value beginning with `=`, `+`, `-` or
`@` as a FORMULA, and openpyxl writes such strings into the cell's <f>
element rather than as a literal value. That means any roll number, subject
code/name, or AI-derived exam name/course/semester that happens to start
with one of those characters becomes a LIVE, EXECUTING FORMULA the moment
the delivered workbook is opened — a classic CSV/Excel-injection attack, and
one this generator had zero defense against before this module existed. A
leading tab or carriage return triggers the same interpretation in some
Excel versions, so those are covered too.

The standard fix is a leading apostrophe: Excel and LibreOffice both treat
`'=SUM(...)` as "force this cell to literal text", displaying `=SUM(...)`
verbatim and never evaluating it.

Every future output generator (seating chart, docket, centre summary, ...)
writes user- or AI-derived values into cells and needs this exact guard —
hence a shared module rather than a helper private to excel_generator.py.
"""

from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins

# A leading tab/CR is included because some Excel versions apply the same
# "this looks like a formula" heuristic to leading whitespace control chars,
# not just the four documented formula-trigger characters.
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")

_BORDER_COLOR = "B0B0B0"


def safe_value(value):
    """Return `value` unchanged, UNLESS it's a string Excel would treat as a
    formula — in which case prefix it with `'` to force literal text.

    Only strings are ever at risk: ints, floats, None, datetimes etc. can
    never be interpreted as a formula by openpyxl, so they pass through
    untouched. This is the one place in the codebase that decides "is this
    value safe to write into a spreadsheet cell" — every sink should route
    through it (directly, or via WorkbookBuilder.safe_cell below).
    """
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGER_CHARS):
        return "'" + value
    return value


class WorkbookBuilder:
    """Styling helpers + two deliberately different cell-writing methods,
    shared across every Excel output generator.

    Two methods, not one, so the choice is visible and explicit at every
    call site instead of silently applied or silently skipped:

    - safe_cell(...)     ALWAYS sanitizes via safe_value(). Use for anything
                          that ultimately traces back to a user upload or an
                          AI response — roll numbers, subject codes/names,
                          course/semester/exam name, notes, anything else
                          extracted or AI-labelled.
    - formula_cell(...)  NEVER sanitizes. Use ONLY for a formula the
                          generator itself built from internally-computed
                          column letters/row numbers (COUNTA, SUM totals).
                          Routing one of those through safe_cell() would
                          quote-prefix the workbook's own totals into inert
                          text — formula_cell() exists so that mistake isn't
                          possible by accident, only by explicitly reaching
                          for the wrong method.
    """

    BORDER_COLOR = _BORDER_COLOR

    @staticmethod
    def hex_color(color: str) -> str:
        return color.lstrip("#")

    @classmethod
    def thin_border(cls) -> Border:
        side = Side(style="thin", color=cls.BORDER_COLOR)
        return Border(left=side, right=side, top=side, bottom=side)

    @staticmethod
    def fill(color_hex: str) -> PatternFill:
        return PatternFill("solid", fgColor=color_hex)

    @staticmethod
    def safe_cell(ws, row: int, column: int, value):
        """Write `value` through the formula-injection guard. Style
        attributes (.font, .fill, .alignment, .border) are set by the
        caller on the returned cell, exactly as with a plain ws.cell()."""
        return ws.cell(row=row, column=column, value=safe_value(value))

    @staticmethod
    def formula_cell(ws, row: int, column: int, formula: str):
        """Write a generator-built formula UNSANITIZED. `formula` must be
        built ONLY from column letters/row numbers this module computed
        itself — never from user- or AI-derived text."""
        return ws.cell(row=row, column=column, value=formula)

    @staticmethod
    def apply_a4_print_setup(
        ws,
        last_col: int,
        last_row: int,
        *,
        orientation: str = "portrait",
        title_rows: str | None = None,
    ) -> None:
        """A4 page setup shared by every output generator that expects to be
        printed (P11; every Gate F generator — seating chart, docket,
        attendance sheet — needs the same thing). Fits the sheet's actual
        content to the page width rather than leaving Excel's default US
        Letter/no-scaling, which cuts columns off mid-print on an A4 printer.

        `title_rows` is an openpyxl print_title_rows string (e.g. "1:2") to
        repeat the title/header rows on every printed page of a long roster.
        """
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.orientation = orientation
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0  # 0 = as many pages tall as needed
        ws.page_margins = PageMargins(left=0.4, right=0.4, top=0.5, bottom=0.5)
        ws.print_area = f"A1:{get_column_letter(last_col)}{last_row}"
        if title_rows:
            ws.print_title_rows = title_rows
