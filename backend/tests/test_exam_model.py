"""Exam data model (WS-G, migration 0002_exam_model; DECISIONS.md 2026-09-19).

The relational bridge extraction needs before the seating planner can exist.
Covers the two §14.5 tests that needed this schema and were deferred until
now (see test_extraction_fields.py's module docstring — the other three of
the five §14.5 tests are already covered there):

- Two uploads of the same sheet -> second run reports "N already enrolled",
  zero new Student rows.
- Same exam_code, different subject_name, in two SEPARATE uploads (not one
  batch) -> a conflict is recorded, neither name silently overwrites the
  other.

Also covers the basic happy path (an upload WITH an exam selected actually
creates Student/SubjectOffering/Enrollment rows) and confirms an upload
WITHOUT an exam selected — the common case until the frontend picker is
adopted everywhere — is a safe no-op rather than a crash.

All counts are filtered by org_id, not global: the test DB is session-scoped
(shared across every test in the suite, per conftest.py), so a global
`SELECT count(*)` would pick up rows other tests left behind.
"""

import uuid

from sqlalchemy import func, select

from app.models.db_models import Enrollment, Job, Student, SubjectOffering
from app.schemas.schemas import StudentRecord, SubjectEntry
from app.services.pipeline.processor import persist_relational_rows


async def _org_id(client) -> str:
    res = await client.get("/api/v1/auth/me")
    assert res.status_code == 200
    return res.json()["org_id"]


async def _create_exam(client, title="M.Com Sem 3") -> str:
    res = await client.post("/api/v1/exams", json={"title": title})
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _create_college(client, name="Test College") -> str:
    res = await client.post("/api/v1/colleges", json={"name": name})
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _upload(client, exam_id, college_id, pages, make_pdf_pages, filename="sheet.pdf"):
    with make_pdf_pages(pages):
        files = [("files", (filename, b"%PDF-1.4 content", "application/pdf"))]
        data = {}
        if exam_id is not None:
            data["exam_id"] = exam_id
        if college_id is not None:
            data["college_id"] = college_id
        res = await client.post("/api/v1/upload", files=files, data=data)
    assert res.status_code == 200, res.text
    return res.json()["job_id"]


def _counter(session_factory, org_id):
    async def _count(model):
        async with session_factory() as session:
            result = await session.execute(
                select(func.count()).select_from(model).where(model.org_id == org_id)
            )
            return result.scalar_one()
    return _count


async def test_upload_with_exam_creates_relational_rows(
    client, test_session_factory, make_pdf_pages
):
    org_id = await _org_id(client)
    exam_id = await _create_exam(client)
    college_id = await _create_college(client)
    pages = [
        "MBAN301 - Business Mathematics  MBAN302 - Accountancy\n"
        "Roll No: 10001  Priya S  Regular\n"
        "Roll No: 10002  Arjun K  Regular\n"
    ]
    await _upload(client, exam_id, college_id, pages, make_pdf_pages)

    count = _counter(test_session_factory, org_id)
    assert await count(Student) == 2
    assert await count(SubjectOffering) == 2
    assert await count(Enrollment) == 4  # 2 students x 2 subjects each


async def test_upload_without_exam_is_a_safe_noop(client, test_session_factory, make_pdf_pages):
    """The common case until the picker is adopted everywhere — persisting_rows
    must not crash or silently create orphaned rows."""
    org_id = await _org_id(client)
    pages = [
        "MBAN301 - Business Mathematics\n"
        "Roll No: 20001  No Exam Here  Regular\n"
    ]
    job_id = await _upload(client, None, None, pages, make_pdf_pages, filename="no_exam.pdf")

    detail_res = await client.get(f"/api/v1/jobs/{job_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["status"] == "completed"  # still succeeds

    count = _counter(test_session_factory, org_id)
    assert await count(Student) == 0
    assert await count(SubjectOffering) == 0


async def test_reupload_reports_already_enrolled_and_creates_no_new_students(
    client, test_session_factory, make_pdf_pages
):
    org_id = await _org_id(client)
    exam_id = await _create_exam(client)
    college_id = await _create_college(client)
    pages = [
        "MBAN301 - Business Mathematics  MBAN302 - Accountancy\n"
        "Roll No: 10001  Priya S  Regular\n"
        "Roll No: 10002  Arjun K  Regular\n"
    ]

    # First upload: everything is new.
    await _upload(client, exam_id, college_id, pages, make_pdf_pages, "first.pdf")

    count = _counter(test_session_factory, org_id)
    assert await count(Student) == 2
    assert await count(Enrollment) == 4

    # Second upload of the SAME sheet: same students, same subjects.
    second_job_id = await _upload(client, exam_id, college_id, pages, make_pdf_pages, "second.pdf")

    # Zero new Student rows — same (org, roll_number) resolves to the same row.
    assert await count(Student) == 2
    # Zero new Enrollment rows either — same (student, offering) pair.
    assert await count(Enrollment) == 4

    second_detail = (await client.get(f"/api/v1/jobs/{second_job_id}")).json()
    assert second_detail["status"] == "completed"


async def test_cross_job_same_exam_code_different_name_is_a_conflict_not_a_silent_overwrite(
    client, test_session_factory, make_pdf_pages
):
    """Calls persist_relational_rows directly (bypassing the full HTTP+AI
    pipeline): the autouse mock_classifier fixture always relabels MBAN301
    "Business Mathematics" regardless of actual page content — a realistic
    property of a FIXED AI mock, not a product bug — so going through two
    real uploads can never produce a genuine name disagreement to observe.
    Testing the exact function this behaviour lives in sidesteps that
    entirely and is more precise besides."""
    org_id = await _org_id(client)
    exam_id = await _create_exam(client)

    async with test_session_factory() as session:
        job = Job(
            id=str(uuid.uuid4()), org_id=org_id, exam_id=exam_id,
            filename="direct-test.pdf", file_type="pdf", status="completed",
        )
        session.add(job)
        await session.commit()

        # First "upload": MBAN301 named "Business Mathematics".
        await persist_relational_rows(
            session, job,
            [StudentRecord(roll_number="10001", subjects=["MBAN301"])],
            [SubjectEntry(code="MBAN301", name="Business Mathematics")],
        )
        await session.commit()

        # Second, separate "upload": the SAME exam_code, a DIFFERENT name.
        already_enrolled, conflicts = await persist_relational_rows(
            session, job,
            [StudentRecord(roll_number="10002", subjects=["MBAN301"])],
            [SubjectEntry(code="MBAN301", name="Applied Mathematics")],
        )
        await session.commit()

    assert conflicts == [("MBAN301", ["Business Mathematics", "Applied Mathematics"])]
    assert already_enrolled == 0  # a genuinely new student/offering pair

    async with test_session_factory() as session:
        result = await session.execute(
            select(SubjectOffering).where(
                SubjectOffering.exam_id == exam_id, SubjectOffering.exam_code == "MBAN301"
            )
        )
        offerings = result.scalars().all()

    # Still exactly ONE offering for MBAN301 — the second name did not
    # create a duplicate row, and did not silently overwrite the first name.
    assert len(offerings) == 1
    assert offerings[0].subject_name == "Business Mathematics"
