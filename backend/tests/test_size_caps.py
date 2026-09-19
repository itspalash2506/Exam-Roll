"""Row/col/page caps and the zip-bomb pre-flight guard (P1-11, P1-12,
DECISIONS.md 2026-09-20) — a 50 MB upload can still declare an unbounded
row/page count inside its own format; these bound the actual parse work."""

import io
import zipfile

import openpyxl
import pytest
from pypdf import PdfWriter

from app.config import get_settings
from app.services.extractors import excel_extractor as xx
from app.services.extractors import pdf_extractor as px


def _make_xlsx(n_rows: int) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["roll no", "MBAN301", "MBAN302"])
    for i in range(n_rows):
        ws.append([str(10000 + i), "x", ""])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_pdf(n_pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(n_pages):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ── XLSX row cap ─────────────────────────────────────────────────────────────

def test_excel_row_cap_truncates_and_reports(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_rows_per_sheet", 5)
    xlsx = _make_xlsx(n_rows=20)

    students, subjects, sample, row_count, truncated = xx.extract_from_excel_with_stats(
        xlsx, "big.xlsx"
    )

    assert truncated is True
    # Cap counts the header row too: 5 rows read - 1 header = 4 data rows.
    assert row_count == 4


def test_excel_row_cap_not_hit_under_the_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_rows_per_sheet", 100)
    xlsx = _make_xlsx(n_rows=5)

    _, _, _, row_count, truncated = xx.extract_from_excel_with_stats(xlsx, "small.xlsx")

    assert truncated is False
    assert row_count == 5


def test_excel_col_cap_truncates_columns():
    ws_rows = [tuple(range(10)), tuple(range(10, 20))]

    class _FakeWs:
        def iter_rows(self, values_only=True):
            yield from ws_rows

    rows, truncated = xx._read_rows(_FakeWs(), max_rows=100, max_cols=3)

    assert truncated is False
    assert all(len(r) == 3 for r in rows)


# ── XLSX zip-bomb pre-flight ─────────────────────────────────────────────────

def test_excel_rejects_highly_compressible_archive():
    """A real xlsx compresses shared strings modestly; a payload that expands
    120x+ its compressed size is rejected before openpyxl ever opens it."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb.xml", b"0" * (20 * 1024 * 1024))
    payload = buf.getvalue()

    with pytest.raises(RuntimeError, match="rejected"):
        xx._reject_zip_bomb(payload, "bomb.xlsx")


def test_excel_accepts_normal_archive():
    xlsx = _make_xlsx(n_rows=5)
    xx._reject_zip_bomb(xlsx, "normal.xlsx")  # must not raise


# ── PDF page cap ─────────────────────────────────────────────────────────────

def test_pdf_page_cap_truncates_and_reports(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_pdf_pages", 3)
    pdf_bytes = _make_pdf(n_pages=6)

    students, subjects, sample, page_count, truncated = px.extract_from_pdf_with_stats(
        pdf_bytes, "big.pdf"
    )

    assert truncated is True
    assert page_count == 3


def test_pdf_page_cap_not_hit_under_the_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_pdf_pages", 100)
    pdf_bytes = _make_pdf(n_pages=3)

    _, _, _, page_count, truncated = px.extract_from_pdf_with_stats(pdf_bytes, "small.pdf")

    assert truncated is False
    assert page_count == 3
