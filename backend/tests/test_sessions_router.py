"""HTTP-level tests for /api/v1/sessions (F02), including the clash check
that runs when a session's paper list is saved (§15.2 step 4)."""

import pytest
from sqlalchemy import select

from app.models.db_models import SubjectOffering
from tests.test_exam_model import _create_college, _create_exam, _org_id, _upload


async def _offering_id(test_session_factory, org_id, exam_code):
    async with test_session_factory() as session:
        result = await session.execute(
            select(SubjectOffering).where(
                SubjectOffering.org_id == org_id, SubjectOffering.exam_code == exam_code
            )
        )
        return result.scalar_one().id


@pytest.mark.asyncio
async def test_create_session_and_duplicate_rejected(client):
    res = await client.post(
        "/api/v1/sessions", json={"date": "2026-09-15", "shift": "Morning"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["date"] == "2026-09-15"

    res = await client.post(
        "/api/v1/sessions", json={"date": "2026-09-15", "shift": "Morning"}
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_set_papers_with_no_clash(client, test_session_factory, make_pdf_pages):
    exam_id = await _create_exam(client, title="No Clash Exam")
    college_id = await _create_college(client, name="No Clash College")
    org_id = await _org_id(client)
    pages = [
        "MBAN301 - Business Mathematics\nRoll No: 70001  Regular\n",
        "MBAN302 - Accountancy\nRoll No: 70002  Regular\n",
    ]
    # Two separate one-student pages -> two students, one paper each -> no clash.
    with make_pdf_pages(pages):
        files = [("files", ("no_clash.pdf", b"%PDF-1.4 dummy", "application/pdf"))]
        res = await client.post(
            "/api/v1/upload",
            files=files,
            data={"exam_id": exam_id, "college_id": college_id},
        )
    assert res.status_code == 200, res.text

    offering_301 = await _offering_id(test_session_factory, org_id, "MBAN301")
    offering_302 = await _offering_id(test_session_factory, org_id, "MBAN302")

    res = await client.post("/api/v1/sessions", json={"date": "2026-09-16", "shift": "Morning"})
    session_id = res.json()["id"]

    res = await client.put(
        f"/api/v1/sessions/{session_id}/papers",
        json={"offering_ids": [offering_301, offering_302]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["clashes"] == []


@pytest.mark.asyncio
async def test_set_papers_detects_and_acknowledges_clash(
    client, test_session_factory, make_pdf_pages
):
    exam_id = await _create_exam(client, title="Clash Exam")
    college_id = await _create_college(client, name="Clash College")
    org_id = await _org_id(client)
    # One student enrolled in BOTH papers -> a real timetable clash if both
    # papers land in the same session.
    pages = ["MBAN301 - Business Mathematics  MBAN302 - Accountancy\nRoll No: 80001  Regular\n"]
    with make_pdf_pages(pages):
        files = [("files", ("clash.pdf", b"%PDF-1.4 dummy", "application/pdf"))]
        res = await client.post(
            "/api/v1/upload",
            files=files,
            data={"exam_id": exam_id, "college_id": college_id},
        )
    assert res.status_code == 200, res.text

    offering_301 = await _offering_id(test_session_factory, org_id, "MBAN301")
    offering_302 = await _offering_id(test_session_factory, org_id, "MBAN302")

    res = await client.post("/api/v1/sessions", json={"date": "2026-09-17", "shift": "Morning"})
    session_id = res.json()["id"]

    res = await client.put(
        f"/api/v1/sessions/{session_id}/papers",
        json={"offering_ids": [offering_301, offering_302]},
    )
    assert res.status_code == 200, res.text
    clashes = res.json()["clashes"]
    assert len(clashes) == 1
    assert clashes[0]["roll_number"] == "80001"
    assert set(clashes[0]["exam_codes"]) == {"MBAN301", "MBAN302"}
    assert clashes[0]["acknowledged"] is False

    student_id = clashes[0]["student_id"]
    res = await client.post(
        f"/api/v1/sessions/{session_id}/clashes/acknowledge",
        json={"student_id": student_id},
    )
    assert res.status_code == 200
    assert res.json()["clashes"][0]["acknowledged"] is True

    # Re-saving the identical paper set must not un-acknowledge it.
    res = await client.put(
        f"/api/v1/sessions/{session_id}/papers",
        json={"offering_ids": [offering_301, offering_302]},
    )
    assert res.json()["clashes"][0]["acknowledged"] is True


@pytest.mark.asyncio
async def test_set_papers_rejects_unknown_offering_id(client):
    res = await client.post("/api/v1/sessions", json={"date": "2026-09-18", "shift": "Evening"})
    session_id = res.json()["id"]

    res = await client.put(
        f"/api/v1/sessions/{session_id}/papers",
        json={"offering_ids": ["does-not-exist"]},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_sessions_are_isolated_per_org(anon_client, org_a, org_b):
    res = await anon_client.post(
        "/api/v1/sessions", json={"date": "2026-09-19", "shift": "Morning"}, cookies=org_a.cookies
    )
    session_id = res.json()["id"]

    res = await anon_client.get(f"/api/v1/sessions/{session_id}", cookies=org_b.cookies)
    assert res.status_code == 404
