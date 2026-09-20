"""HTTP + lifecycle tests for the seating plan API (F04 item 5, §15.5).

The allocator's own correctness is property-tested in
`test_seating_allocator.py`; what is checked here is the part a pure
function cannot be: the plan rows that get written, the operations §15.5
says must be refused, and F04's literal "Done when" — publishing a plan
with one unseated student returns 409 naming the roll.
"""

import pytest
from sqlalchemy import select, update

from app.models.db_models import (
    Enrollment,
    Exam,
    SeatAssignment,
    SeatingPlan,
    Student,
    SubjectOffering,
    User,
)
from app.utils.roll_sort import roll_sort_key
from tests.test_exam_model import _org_id


async def _seed_paper(session_factory, org_id, rolls, *, exam_code="K-3678",
                      title="P.G. Sem 4", statuses=None):
    """Insert one exam, one paper and its enrolled candidates directly.

    Going through /api/v1/upload would work but makes every seating test
    depend on the PDF extractor; the seating layer's input is the
    Enrollment/Student rows, so those are what the fixture builds.
    """
    statuses = statuses or {}
    async with session_factory() as session:
        exam = Exam(org_id=org_id, title=title)
        session.add(exam)
        await session.flush()
        offering = SubjectOffering(
            org_id=org_id, exam_id=exam.id, exam_code=exam_code,
            subject_name="Advertising & Sales Management",
        )
        session.add(offering)
        await session.flush()
        for roll in rolls:
            student = Student(
                org_id=org_id, roll_number=roll, roll_sort_key=roll_sort_key(roll),
                status=statuses.get(roll, "regular"),
            )
            session.add(student)
            await session.flush()
            session.add(
                Enrollment(org_id=org_id, student_id=student.id, offering_id=offering.id)
            )
        await session.commit()
        return exam.id, offering.id


async def _set_role(session_factory, org_id, role):
    """The conftest user is created with the default role ("member").
    Publishing is controller-only (Q9), so a test that publishes says so."""
    async with session_factory() as session:
        await session.execute(
            update(User).where(User.org_id == org_id).values(role=role)
        )
        await session.commit()


async def _make_room(client, name, columns, seats, **kw):
    payload = {
        "name": name,
        "seat_columns": [{"label": f"Row {i + 1}", "seats": seats} for i in range(columns)],
        "blocked_seats": kw.pop("blocked_seats", []),
        "seats_per_bench": kw.pop("seats_per_bench", 1),
    }
    payload.update(kw)
    res = await client.post("/api/v1/rooms", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _make_session(client, offering_ids, *, date="2026-09-15", shift="Morning"):
    res = await client.post("/api/v1/sessions", json={"date": date, "shift": shift})
    assert res.status_code == 200, res.text
    session_id = res.json()["id"]
    res = await client.put(
        f"/api/v1/sessions/{session_id}/papers", json={"offering_ids": offering_ids}
    )
    assert res.status_code == 200, res.text
    return session_id


async def _create_plan(client, session_id, room_ids, strategy=None):
    body = {"rooms": [{"room_id": rid} for rid in room_ids]}
    if strategy is not None:
        body["strategy"] = strategy
    return await client.post(f"/api/v1/sessions/{session_id}/plans", json=body)


# ── Creating a draft ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_draft_seats_the_whole_roster(client, test_session_factory):
    org_id = await _org_id(client)
    rolls = [str(24109300 + i) for i in range(1, 11)]
    _exam_id, offering_id = await _seed_paper(test_session_factory, org_id, rolls)
    session_id = await _make_session(client, [offering_id])
    room_id = await _make_room(client, "Room No 1", columns=2, seats=6)

    res = await _create_plan(client, session_id, [room_id])
    assert res.status_code == 200, res.text
    plan = res.json()
    assert plan["version"] == 1
    assert plan["status"] == "draft"
    assert plan["roster_size"] == 10
    assert len(plan["assignments"]) == 10
    assert plan["unseated"] == []
    assert plan["violations"] == []
    # §15.3's defaults, resolved and stored on the plan.
    assert plan["strategy"]["fill_order"] == "column_major"
    assert plan["strategy"]["adjacency"] == "none"
    assert plan["seed"] == 0
    # Column-major, roll ascending: column 1 holds the first six rolls.
    column_one = [
        a["roll_number"] for a in plan["assignments"] if a["col_index"] == 1
    ]
    assert column_one == rolls[:6]

    # The rows really are in the database, not just in the response.
    async with test_session_factory() as session:
        stored = (
            await session.execute(
                select(SeatAssignment).where(SeatAssignment.plan_id == plan["id"])
            )
        ).scalars().all()
    assert len(stored) == 10
    assert all(row.org_id == org_id for row in stored)


@pytest.mark.asyncio
async def test_a_session_gets_one_plan_and_then_versions(client, test_session_factory):
    org_id = await _org_id(client)
    _e, offering_id = await _seed_paper(test_session_factory, org_id, ["101", "102"])
    session_id = await _make_session(client, [offering_id], date="2026-09-16")
    room_id = await _make_room(client, "R", columns=1, seats=4)

    assert (await _create_plan(client, session_id, [room_id])).status_code == 200
    second = await _create_plan(client, session_id, [room_id])
    assert second.status_code == 409
    assert "new-version" in second.json()["detail"]


@pytest.mark.asyncio
async def test_plan_creation_rejects_an_unknown_or_foreign_room(client, test_session_factory):
    org_id = await _org_id(client)
    _e, offering_id = await _seed_paper(test_session_factory, org_id, ["101"])
    session_id = await _make_session(client, [offering_id], date="2026-09-17")
    res = await _create_plan(client, session_id, ["no-such-room"])
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_plan_creation_rejects_an_unknown_strategy_value(client, test_session_factory):
    org_id = await _org_id(client)
    _e, offering_id = await _seed_paper(test_session_factory, org_id, ["101"])
    session_id = await _make_session(client, [offering_id], date="2026-09-18")
    room_id = await _make_room(client, "R", columns=1, seats=2)
    res = await _create_plan(client, session_id, [room_id], {"fill_order": "diagonal"})
    assert res.status_code == 422


# ── Editing ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_move_locks_the_seat_and_rerun_preserves_it(client, test_session_factory):
    """§15.5's edit → re-run loop. A hand move sets `locked`, because a
    re-run that silently discarded a clerk's correction is the failure class
    this codebase keeps paying for."""
    org_id = await _org_id(client)
    rolls = [str(500 + i) for i in range(4)]
    _e, offering_id = await _seed_paper(test_session_factory, org_id, rolls)
    session_id = await _make_session(client, [offering_id], date="2026-09-19")
    room_id = await _make_room(client, "R", columns=2, seats=3)
    plan = (await _create_plan(client, session_id, [room_id])).json()
    plan_id = plan["id"]

    first = plan["assignments"][0]
    assert first["locked"] is False
    res = await client.post(
        f"/api/v1/plans/{plan_id}/move",
        json={
            "student_id": first["student_id"],
            "offering_id": first["offering_id"],
            "to": {"room_id": room_id, "col_index": 2, "seat_index": 3, "bench_pos": 1},
        },
    )
    assert res.status_code == 200, res.text
    moved = next(
        a for a in res.json()["assignments"]
        if a["student_id"] == first["student_id"]
    )
    assert (moved["col_index"], moved["seat_index"]) == (2, 3)
    assert moved["locked"] is True

    res = await client.post(f"/api/v1/plans/{plan_id}/rerun", json={})
    assert res.status_code == 200, res.text
    after = next(
        a for a in res.json()["assignments"]
        if a["student_id"] == first["student_id"]
    )
    assert (after["col_index"], after["seat_index"]) == (2, 3)
    assert res.json()["violations"] == []


@pytest.mark.asyncio
async def test_move_onto_an_occupied_or_impossible_seat_is_refused(
    client, test_session_factory
):
    org_id = await _org_id(client)
    _e, offering_id = await _seed_paper(test_session_factory, org_id, ["601", "602"])
    session_id = await _make_session(client, [offering_id], date="2026-09-20")
    room_id = await _make_room(
        client, "R", columns=1, seats=3, blocked_seats=[{"col": 1, "seat": 3}]
    )
    plan = (await _create_plan(client, session_id, [room_id])).json()
    first, second = plan["assignments"][0], plan["assignments"][1]

    occupied = await client.post(
        f"/api/v1/plans/{plan['id']}/move",
        json={
            "student_id": first["student_id"], "offering_id": first["offering_id"],
            "to": {"room_id": room_id, "col_index": second["col_index"],
                   "seat_index": second["seat_index"], "bench_pos": 1},
        },
    )
    assert occupied.status_code == 409

    blocked = await client.post(
        f"/api/v1/plans/{plan['id']}/move",
        json={
            "student_id": first["student_id"], "offering_id": first["offering_id"],
            "to": {"room_id": room_id, "col_index": 1, "seat_index": 3, "bench_pos": 1},
        },
    )
    assert blocked.status_code == 422
    assert "blocked" in blocked.json()["detail"]

    nowhere = await client.post(
        f"/api/v1/plans/{plan['id']}/move",
        json={
            "student_id": first["student_id"], "offering_id": first["offering_id"],
            "to": {"room_id": room_id, "col_index": 9, "seat_index": 9, "bench_pos": 1},
        },
    )
    assert nowhere.status_code == 422


@pytest.mark.asyncio
async def test_swap_exchanges_two_occupants_and_locks_both(client, test_session_factory):
    org_id = await _org_id(client)
    _e, offering_id = await _seed_paper(test_session_factory, org_id, ["701", "702"])
    session_id = await _make_session(client, [offering_id], date="2026-09-21")
    room_id = await _make_room(client, "R", columns=1, seats=2)
    plan = (await _create_plan(client, session_id, [room_id])).json()
    a, b = plan["assignments"][0], plan["assignments"][1]

    res = await client.post(
        f"/api/v1/plans/{plan['id']}/swap",
        json={
            "seat_a": {"room_id": room_id, "col_index": a["col_index"],
                       "seat_index": a["seat_index"], "bench_pos": 1},
            "seat_b": {"room_id": room_id, "col_index": b["col_index"],
                       "seat_index": b["seat_index"], "bench_pos": 1},
        },
    )
    assert res.status_code == 200, res.text
    after = {(x["col_index"], x["seat_index"]): x for x in res.json()["assignments"]}
    assert after[(a["col_index"], a["seat_index"])]["roll_number"] == b["roll_number"]
    assert after[(b["col_index"], b["seat_index"])]["roll_number"] == a["roll_number"]
    assert all(x["locked"] for x in res.json()["assignments"])
    assert res.json()["violations"] == []


@pytest.mark.asyncio
async def test_lock_and_unlock_a_seat(client, test_session_factory):
    org_id = await _org_id(client)
    _e, offering_id = await _seed_paper(test_session_factory, org_id, ["801"])
    session_id = await _make_session(client, [offering_id], date="2026-09-22")
    room_id = await _make_room(client, "R", columns=1, seats=2)
    plan = (await _create_plan(client, session_id, [room_id])).json()
    seat = {"room_id": room_id, "col_index": 1, "seat_index": 1, "bench_pos": 1}

    res = await client.post(f"/api/v1/plans/{plan['id']}/lock",
                            json={"seat": seat, "locked": True})
    assert res.status_code == 200
    assert res.json()["assignments"][0]["locked"] is True

    res = await client.post(f"/api/v1/plans/{plan['id']}/lock",
                            json={"seat": seat, "locked": False})
    assert res.json()["assignments"][0]["locked"] is False

    empty = await client.post(
        f"/api/v1/plans/{plan['id']}/lock",
        json={"seat": {**seat, "seat_index": 2}, "locked": True},
    )
    assert empty.status_code == 404


@pytest.mark.asyncio
async def test_blocking_a_seat_then_rerunning_reports_the_stale_lock(
    client, test_session_factory
):
    """§15.5's "block a seat → re-run preserving locks", at the edge the
    spec leaves open: the blocked bench is the locked one."""
    org_id = await _org_id(client)
    _e, offering_id = await _seed_paper(test_session_factory, org_id, ["901"])
    session_id = await _make_session(client, [offering_id], date="2026-09-23")
    room_id = await _make_room(client, "R", columns=1, seats=2)
    plan = (await _create_plan(client, session_id, [room_id])).json()
    await client.post(
        f"/api/v1/plans/{plan['id']}/lock",
        json={"seat": {"room_id": room_id, "col_index": 1, "seat_index": 1,
                       "bench_pos": 1}, "locked": True},
    )
    res = await client.patch(
        f"/api/v1/rooms/{room_id}", json={"blocked_seats": [{"col": 1, "seat": 1}]}
    )
    assert res.status_code == 200, res.text

    res = await client.post(f"/api/v1/plans/{plan['id']}/rerun", json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert [s["reason"] for s in body["stale_locks"]] == ["bench has since been blocked"]
    assert [(a["col_index"], a["seat_index"]) for a in body["assignments"]] == [(1, 2)]
    assert body["violations"] == []


# ── Publishing ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publishing_with_an_unseated_student_returns_409_naming_the_roll(
    client, test_session_factory
):
    """F04's literal "Done when": one candidate short of a seat, and the
    refusal says WHICH candidate. "One student has no seat" is not
    actionable at 9am on exam day."""
    org_id = await _org_id(client)
    await _set_role(test_session_factory, org_id, "controller")
    rolls = ["24109301", "24109302", "24109304"]
    _e, offering_id = await _seed_paper(test_session_factory, org_id, rolls)
    session_id = await _make_session(client, [offering_id], date="2026-09-24")
    room_id = await _make_room(client, "Small Room", columns=1, seats=2)
    plan = (await _create_plan(client, session_id, [room_id])).json()
    assert [u["roll_number"] for u in plan["unseated"]] == ["24109304"]

    res = await client.post(f"/api/v1/plans/{plan['id']}/publish")
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert "24109304" in detail
    assert "1 candidate(s) have no seat" in detail


@pytest.mark.asyncio
async def test_publish_freezes_the_plan_and_refuses_later_edits(
    client, test_session_factory
):
    org_id = await _org_id(client)
    await _set_role(test_session_factory, org_id, "controller")
    _e, offering_id = await _seed_paper(test_session_factory, org_id, ["1001", "1002"])
    session_id = await _make_session(client, [offering_id], date="2026-09-25")
    room_id = await _make_room(client, "R", columns=1, seats=4)
    plan = (await _create_plan(client, session_id, [room_id])).json()

    res = await client.post(f"/api/v1/plans/{plan['id']}/publish")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "published"
    assert res.json()["published_at"] is not None

    for path, body in (
        ("rerun", {}),
        ("lock", {"seat": {"room_id": room_id, "col_index": 1, "seat_index": 1,
                           "bench_pos": 1}, "locked": True}),
    ):
        res = await client.post(f"/api/v1/plans/{plan['id']}/{path}", json=body)
        assert res.status_code == 409, path
        assert "published" in res.json()["detail"]

    again = await client.post(f"/api/v1/plans/{plan['id']}/publish")
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_publishing_needs_the_controller_role(client, test_session_factory):
    """Q9 (§23.1, 2026-09-20): only the superintendent may publish. The
    conftest user is a plain member."""
    org_id = await _org_id(client)
    _e, offering_id = await _seed_paper(test_session_factory, org_id, ["1101"])
    session_id = await _make_session(client, [offering_id], date="2026-09-26")
    room_id = await _make_room(client, "R", columns=1, seats=2)
    plan = (await _create_plan(client, session_id, [room_id])).json()

    res = await client.post(f"/api/v1/plans/{plan['id']}/publish")
    assert res.status_code == 403
    assert "controller" in res.json()["detail"]

    await _set_role(test_session_factory, org_id, "admin")
    res = await client.post(f"/api/v1/plans/{plan['id']}/publish")
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_publishing_is_refused_while_a_clash_is_unacknowledged(
    client, test_session_factory
):
    """The storage shape for clashes was decided in F02 with F04 named as
    the gate that enforces them (see ExamSession.clashes' comment)."""
    org_id = await _org_id(client)
    await _set_role(test_session_factory, org_id, "controller")
    _e, first = await _seed_paper(test_session_factory, org_id, ["1201"], exam_code="K-1")
    # Enrol the same student in a second paper of the same session.
    async with test_session_factory() as session:
        student = (
            await session.execute(
                select(Student).where(Student.roll_number == "1201",
                                      Student.org_id == org_id)
            )
        ).scalar_one()
        exam_id = (
            await session.execute(
                select(SubjectOffering.exam_id).where(SubjectOffering.id == first)
            )
        ).scalar_one()
        second = SubjectOffering(
            org_id=org_id, exam_id=exam_id, exam_code="K-2", subject_name="Other"
        )
        session.add(second)
        await session.flush()
        session.add(
            Enrollment(org_id=org_id, student_id=student.id, offering_id=second.id)
        )
        second_id = second.id
        await session.commit()

    session_id = await _make_session(client, [first, second_id], date="2026-09-27")
    room_id = await _make_room(client, "R", columns=1, seats=4)
    plan = (await _create_plan(client, session_id, [room_id])).json()
    assert plan["unseated"] == []

    res = await client.post(f"/api/v1/plans/{plan['id']}/publish")
    assert res.status_code == 409
    assert "unacknowledged" in res.json()["detail"]

    student_id = plan["assignments"][0]["student_id"]
    await client.post(
        f"/api/v1/sessions/{session_id}/clashes/acknowledge",
        json={"student_id": student_id},
    )
    res = await client.post(f"/api/v1/plans/{plan['id']}/publish")
    assert res.status_code == 200, res.text


# ── Versioning ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_version_copies_locks_and_supersedes_the_old_plan(
    client, test_session_factory
):
    org_id = await _org_id(client)
    await _set_role(test_session_factory, org_id, "controller")
    rolls = [str(1300 + i) for i in range(4)]
    _e, offering_id = await _seed_paper(test_session_factory, org_id, rolls)
    session_id = await _make_session(client, [offering_id], date="2026-09-28")
    room_id = await _make_room(client, "R", columns=2, seats=3)
    plan = (await _create_plan(client, session_id, [room_id])).json()
    plan_id = plan["id"]

    # Lock somebody somewhere the allocator would not have put them.
    first = plan["assignments"][0]
    await client.post(
        f"/api/v1/plans/{plan_id}/move",
        json={"student_id": first["student_id"], "offering_id": first["offering_id"],
              "to": {"room_id": room_id, "col_index": 2, "seat_index": 3,
                     "bench_pos": 1}},
    )
    await client.post(f"/api/v1/plans/{plan_id}/publish")

    res = await client.post(f"/api/v1/plans/{plan_id}/new-version", json={})
    assert res.status_code == 200, res.text
    successor = res.json()
    assert successor["version"] == 2
    assert successor["status"] == "draft"
    assert successor["id"] != plan_id
    carried = next(
        a for a in successor["assignments"] if a["student_id"] == first["student_id"]
    )
    assert (carried["col_index"], carried["seat_index"]) == (2, 3)
    assert carried["locked"] is True
    assert successor["violations"] == []

    # Version 1's own rows are untouched — attendance taken against it must
    # still resolve to its seats (§15.5).
    old = (await client.get(f"/api/v1/plans/{plan_id}")).json()
    assert old["status"] == "superseded"
    assert len(old["assignments"]) == 4

    listed = (await client.get(f"/api/v1/sessions/{session_id}/plans")).json()
    assert [p["version"] for p in listed] == [1, 2]


@pytest.mark.asyncio
async def test_new_version_can_change_the_room_list(client, test_session_factory):
    org_id = await _org_id(client)
    rolls = [str(1400 + i) for i in range(6)]
    _e, offering_id = await _seed_paper(test_session_factory, org_id, rolls)
    session_id = await _make_session(client, [offering_id], date="2026-09-29")
    small = await _make_room(client, "Small", columns=1, seats=2)
    big = await _make_room(client, "Big", columns=2, seats=4)
    plan = (await _create_plan(client, session_id, [small])).json()
    assert len(plan["unseated"]) == 4

    res = await client.post(
        f"/api/v1/plans/{plan['id']}/new-version",
        json={"rooms": [{"room_id": small}, {"room_id": big}]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["unseated"] == []
    assert {r["room_id"] for r in res.json()["rooms"]} == {small, big}


# ── Tenancy ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plans_are_isolated_per_org(anon_client, org_a, org_b, test_session_factory):
    """A cross-org read is 404, never 403 — a 403 confirms the plan exists
    and turns the endpoint into an existence oracle."""
    _e, offering_id = await _seed_paper(test_session_factory, org_a.org_id, ["1501"])
    res = await anon_client.post(
        "/api/v1/sessions", json={"date": "2026-09-30", "shift": "Morning"},
        cookies=org_a.cookies,
    )
    session_id = res.json()["id"]
    await anon_client.put(
        f"/api/v1/sessions/{session_id}/papers", json={"offering_ids": [offering_id]},
        cookies=org_a.cookies,
    )
    res = await anon_client.post(
        "/api/v1/rooms",
        json={"name": "R", "seat_columns": [{"label": "Row 1", "seats": 2}]},
        cookies=org_a.cookies,
    )
    room_id = res.json()["id"]
    res = await anon_client.post(
        f"/api/v1/sessions/{session_id}/plans",
        json={"rooms": [{"room_id": room_id}]}, cookies=org_a.cookies,
    )
    assert res.status_code == 200, res.text
    plan_id = res.json()["id"]

    for method, path in (
        ("GET", f"/api/v1/plans/{plan_id}"),
        ("POST", f"/api/v1/plans/{plan_id}/publish"),
        ("POST", f"/api/v1/plans/{plan_id}/rerun"),
    ):
        res = await anon_client.request(
            method, path, json={} if method == "POST" else None, cookies=org_b.cookies
        )
        assert res.status_code == 404, path


@pytest.mark.asyncio
async def test_plan_endpoints_require_a_session_cookie(anon_client):
    res = await anon_client.get("/api/v1/plans/anything")
    assert res.status_code == 401


# ── Determinism, end to end ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rerun_of_an_untouched_plan_reproduces_it_exactly(
    client, test_session_factory
):
    """Invariant (b) through the whole stack, not just the pure function:
    the same roster, rooms, strategy and seed give the same chart."""
    org_id = await _org_id(client)
    rolls = [str(1600 + i) for i in range(9)]
    _e, offering_id = await _seed_paper(test_session_factory, org_id, rolls)
    session_id = await _make_session(client, [offering_id], date="2026-10-01")
    room_id = await _make_room(client, "R", columns=3, seats=4)
    before = (await _create_plan(client, session_id, [room_id])).json()

    after = (
        await client.post(f"/api/v1/plans/{before['id']}/rerun", json={})
    ).json()
    assert plan_seats(after) == plan_seats(before)
    assert after["strategy"] == before["strategy"]


def plan_seats(plan):
    return [
        (a["room_id"], a["col_index"], a["seat_index"], a["bench_pos"], a["roll_number"])
        for a in plan["assignments"]
    ]


@pytest.mark.asyncio
async def test_a_room_used_by_a_plan_cannot_be_deleted(client, test_session_factory):
    """§15.1: a room in use is deactivated, never deleted. Resolves the
    `TODO(F04)` that `rooms.py` has been carrying since F02 — the condition
    it was waiting for (SeatingPlanRoom) is this migration."""
    org_id = await _org_id(client)
    _e, offering_id = await _seed_paper(test_session_factory, org_id, ["1801"])
    session_id = await _make_session(client, [offering_id], date="2026-10-03")
    used = await _make_room(client, "In Use", columns=1, seats=2)
    spare = await _make_room(client, "Spare", columns=1, seats=2)
    assert (await _create_plan(client, session_id, [used])).status_code == 200

    res = await client.delete(f"/api/v1/rooms/{used}")
    assert res.status_code == 409
    assert "deactivate" in res.json()["detail"]
    # An unused room still deletes normally.
    assert (await client.delete(f"/api/v1/rooms/{spare}")).status_code == 204


@pytest.mark.asyncio
async def test_plan_versions_are_unique_per_session(client, test_session_factory):
    org_id = await _org_id(client)
    _e, offering_id = await _seed_paper(test_session_factory, org_id, ["1701"])
    session_id = await _make_session(client, [offering_id], date="2026-10-02")
    room_id = await _make_room(client, "R", columns=1, seats=2)
    plan = (await _create_plan(client, session_id, [room_id])).json()
    await client.post(f"/api/v1/plans/{plan['id']}/new-version", json={})
    async with test_session_factory() as session:
        versions = (
            await session.execute(
                select(SeatingPlan.version).where(SeatingPlan.session_id == session_id)
            )
        ).scalars().all()
    assert sorted(versions) == [1, 2]
