"""GET /api/v1/exams/{id}/offerings — backs the F03 session setup papers
multi-select (grouped by exam + course, with real enrolment counts)."""

import pytest

from tests.test_exam_model import _create_college, _create_exam, _upload


@pytest.mark.asyncio
async def test_list_offerings_with_enrollment_counts(client, make_pdf_pages):
    exam_id = await _create_exam(client, title="Offerings Exam")
    college_id = await _create_college(client, name="Offerings College")
    pages = [
        "MBAN301 - Business Mathematics  MBAN302 - Accountancy\nRoll No: 90001  Regular\n",
        "MBAN301 - Business Mathematics\nRoll No: 90002  Regular\n",
    ]
    with make_pdf_pages(pages):
        files = [("files", ("offerings.pdf", b"%PDF-1.4 dummy", "application/pdf"))]
        res = await client.post(
            "/api/v1/upload",
            files=files,
            data={"exam_id": exam_id, "college_id": college_id},
        )
    assert res.status_code == 200, res.text

    res = await client.get(f"/api/v1/exams/{exam_id}/offerings")
    assert res.status_code == 200, res.text
    offerings = {o["exam_code"]: o for o in res.json()}
    assert offerings["MBAN301"]["enrollment_count"] == 2
    assert offerings["MBAN302"]["enrollment_count"] == 1


@pytest.mark.asyncio
async def test_offerings_404_for_unknown_exam(client):
    res = await client.get("/api/v1/exams/does-not-exist/offerings")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_offerings_are_isolated_per_org(anon_client, org_a, org_b):
    res = await anon_client.post(
        "/api/v1/exams", json={"title": "Org A Exam"}, cookies=org_a.cookies
    )
    exam_id = res.json()["id"]

    res = await anon_client.get(f"/api/v1/exams/{exam_id}/offerings", cookies=org_b.cookies)
    assert res.status_code == 404
