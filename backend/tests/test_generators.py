import pytest
from app.services.generators.excel_generator import generate_excel


def test_generate_excel_per_subject():
    rows = [
        {"roll_no": "001", "subject": "Mathematics"},
        {"roll_no": "002", "subject": "Mathematics"},
        {"roll_no": "003", "subject": "Physics"},
    ]
    wb = generate_excel(rows, output_type="per_subject")
    assert "Mathematics" in wb.sheetnames
    assert "Physics" in wb.sheetnames


def test_generate_excel_single_sheet():
    rows = [{"roll_no": "001", "subject": "Chemistry"}]
    wb = generate_excel(rows, output_type="single")
    assert "All Data" in wb.sheetnames
