"""Room capacity and room validation (WS-H, FUTURE_UNIFIED.md §15.1).

Model/schema level only — there is no rooms router yet. What is being
pinned here is the one number every later seating feature is built on: how
many candidates a non-rectangular room actually holds. §21 ranks the
allocator's correctness fourth in the project, and the allocator cannot be
more correct than the capacity it is handed.

The reference room is real: `ROOM - 5 LIBRARY HALL` in the pilot centre's
workbook (§12.1) — columns of 3, 13, 13 and 4 benches, two benches marked
`x`, one candidate per bench → 31.
"""

import datetime

import pytest
import sqlalchemy.exc
from pydantic import ValidationError
from sqlalchemy import select

from app.models.db_models import ExamSession, Organization, Room
from app.schemas.schemas import RoomCreate
from app.utils.room_capacity import room_capacity

# The four columns of LIBRARY HALL, and the two seats marked `x`.
LIBRARY_HALL_COLUMNS = [
    {"label": "Row 1", "seats": 3},
    {"label": "Row 2", "seats": 13},
    {"label": "Row 3", "seats": 13},
    {"label": "Row 4", "seats": 4},
]
LIBRARY_HALL_BLOCKED = [{"col": 2, "seat": 13}, {"col": 3, "seat": 13}]
LIBRARY_HALL_CAPACITY = 31  # (3 + 13 + 13 + 4) - 2 = 31


def _library_hall(**overrides) -> dict:
    payload = {
        "name": "LIBRARY HALL",
        "building": "Main Block",
        "seat_columns": [dict(c) for c in LIBRARY_HALL_COLUMNS],
        "blocked_seats": [dict(b) for b in LIBRARY_HALL_BLOCKED],
        "seats_per_bench": 1,
    }
    payload.update(overrides)
    return payload


# ── Capacity ────────────────────────────────────────────────────────────────

def test_library_hall_capacity_is_31():
    room = Room(
        org_id="org-1",
        name="LIBRARY HALL",
        seat_columns=LIBRARY_HALL_COLUMNS,
        blocked_seats=LIBRARY_HALL_BLOCKED,
        seats_per_bench=1,
    )
    assert sum(c["seats"] for c in LIBRARY_HALL_COLUMNS) == 33
    assert room.capacity == LIBRARY_HALL_CAPACITY


def test_capacity_scales_with_seats_per_bench():
    # Blocking removes a whole BENCH, so the multiplication comes last:
    # (33 - 2) * n, never 33 * n - 2.
    for per_bench, expected in ((1, 31), (2, 62), (3, 93)):
        room = Room(
            org_id="org-1",
            name="LIBRARY HALL",
            seat_columns=LIBRARY_HALL_COLUMNS,
            blocked_seats=LIBRARY_HALL_BLOCKED,
            seats_per_bench=per_bench,
        )
        assert room.capacity == expected


def test_capacity_with_no_blocked_seats():
    room = Room(
        org_id="org-1",
        name="Room No 1",
        seat_columns=[{"label": f"Row {i}", "seats": 6} for i in range(1, 6)],
        blocked_seats=[],
        seats_per_bench=1,
    )
    assert room.capacity == 30


def test_capacity_of_an_unsaved_room_with_json_defaults_unapplied():
    # A Room() constructed in Python has None in its JSON columns until the
    # ORM applies the column defaults at INSERT. Capacity must be 0 there,
    # not an AttributeError in a list view.
    assert Room(org_id="org-1", name="Empty").capacity == 0


def test_capacity_ignores_a_repeated_blocked_seat():
    # The schema refuses to save a duplicate, but if one reaches the DB by
    # another route it must not subtract twice — capacity has to equal the
    # number of seats the allocator will actually skip.
    assert room_capacity(
        LIBRARY_HALL_COLUMNS,
        LIBRARY_HALL_BLOCKED + [{"col": 2, "seat": 13}],
        1,
    ) == LIBRARY_HALL_CAPACITY


def test_capacity_ignores_a_blocked_seat_that_does_not_exist():
    # Same reasoning in the other direction: a phantom seat must not shrink
    # capacity below the seats the room really has.
    assert room_capacity(
        LIBRARY_HALL_COLUMNS,
        LIBRARY_HALL_BLOCKED + [{"col": 9, "seat": 1}],
        1,
    ) == LIBRARY_HALL_CAPACITY


def test_blocked_seat_indices_are_one_based():
    # Column 1 seat 1 is a real seat and is blockable; column 0 / seat 0 are
    # not seats at all. This is the convention the allocator must share.
    one_column = [{"label": "Row 1", "seats": 2}]
    assert room_capacity(one_column, [{"col": 1, "seat": 1}], 1) == 1
    assert room_capacity(one_column, [{"col": 0, "seat": 0}], 1) == 2
    # Seat 2 is the last real seat of a 2-seat column; seat 3 is not.
    assert room_capacity(one_column, [{"col": 1, "seat": 2}], 1) == 1
    assert room_capacity(one_column, [{"col": 1, "seat": 3}], 1) == 2


# ── Validation ──────────────────────────────────────────────────────────────

def test_valid_library_hall_payload_is_accepted():
    room = RoomCreate(**_library_hall())
    assert room.capacity == LIBRARY_HALL_CAPACITY
    assert [c.seats for c in room.seat_columns] == [3, 13, 13, 4]
    assert room.is_active is True
    assert room.sort_priority == 0


def test_empty_seat_columns_rejected():
    with pytest.raises(ValidationError, match="seat_columns must not be empty"):
        RoomCreate(**_library_hall(seat_columns=[]))


def test_column_with_zero_seats_rejected():
    with pytest.raises(ValidationError, match="at least 1 seat"):
        RoomCreate(**_library_hall(
            seat_columns=[{"label": "Row 1", "seats": 6}, {"label": "Row 2", "seats": 0}]
        ))


def test_blocked_seat_in_a_nonexistent_column_rejected():
    with pytest.raises(ValidationError) as exc:
        RoomCreate(**_library_hall(blocked_seats=[{"col": 5, "seat": 1}]))
    message = str(exc.value)
    assert "col 5, seat 1" in message
    assert "does not have" in message


def test_blocked_seat_past_the_end_of_a_column_rejected():
    # Column 1 has 3 seats; seat 4 is one past the end — the off-by-one this
    # whole indexing convention exists to make unambiguous.
    with pytest.raises(ValidationError) as exc:
        RoomCreate(**_library_hall(blocked_seats=[{"col": 1, "seat": 4}]))
    assert "col 1, seat 4" in str(exc.value)
    # …while seat 3 of the same column is fine.
    assert RoomCreate(**_library_hall(blocked_seats=[{"col": 1, "seat": 3}])).capacity == 32


def test_duplicate_blocked_seat_rejected():
    with pytest.raises(ValidationError, match="more than once"):
        RoomCreate(**_library_hall(
            blocked_seats=[{"col": 2, "seat": 1}, {"col": 2, "seat": 1}]
        ))


@pytest.mark.parametrize("bad", [0, 4, -1])
def test_seats_per_bench_outside_the_allowed_set_rejected(bad):
    with pytest.raises(ValidationError, match="seats_per_bench must be one of"):
        RoomCreate(**_library_hall(seats_per_bench=bad))


@pytest.mark.parametrize("good", [1, 2, 3])
def test_seats_per_bench_allowed_values_accepted(good):
    assert RoomCreate(**_library_hall(seats_per_bench=good)).capacity == 31 * good


# ── Persistence ─────────────────────────────────────────────────────────────

async def _new_org(session_factory, name: str) -> str:
    async with session_factory() as session:
        org = Organization(name=name)
        session.add(org)
        await session.commit()
        return org.id


async def test_room_survives_a_database_round_trip(test_session_factory):
    """The JSON columns must come back as native Python lists of dicts, or
    `capacity` would be doing arithmetic over a string. SQLAlchemy's generic
    JSON type handles this identically on SQLite (json.loads over TEXT) and
    Postgres — this pins the half the test suite can actually run."""
    org_id = await _new_org(test_session_factory, "Room Round Trip Org")
    payload = RoomCreate(**_library_hall())

    async with test_session_factory() as session:
        session.add(Room(
            org_id=org_id,
            name=payload.name,
            building=payload.building,
            seat_columns=[c.model_dump() for c in payload.seat_columns],
            blocked_seats=[b.model_dump() for b in payload.blocked_seats],
            seats_per_bench=payload.seats_per_bench,
        ))
        await session.commit()

    async with test_session_factory() as session:
        loaded = (await session.execute(
            select(Room).where(Room.org_id == org_id)
        )).scalar_one()

    assert isinstance(loaded.seat_columns, list)
    assert loaded.seat_columns[0] == {"label": "Row 1", "seats": 3}
    assert loaded.blocked_seats == LIBRARY_HALL_BLOCKED
    assert loaded.capacity == LIBRARY_HALL_CAPACITY == payload.capacity
    # Column defaults applied at INSERT, not construction.
    assert loaded.is_active is True
    assert loaded.sort_priority == 0


async def test_one_session_per_org_date_shift(test_session_factory):
    """UNIQUE(org_id, date, shift) — §13.2. A centre has one morning sitting
    on a given day; two would split one roster across two plans."""
    org_id = await _new_org(test_session_factory, "Session Uniqueness Org")
    day = datetime.date(2026, 9, 15)

    async with test_session_factory() as session:
        session.add(ExamSession(org_id=org_id, date=day, shift="Morning"))
        await session.commit()

    # Same day, different shift: fine.
    async with test_session_factory() as session:
        session.add(ExamSession(org_id=org_id, date=day, shift="Afternoon"))
        await session.commit()

    async with test_session_factory() as session:
        session.add(ExamSession(org_id=org_id, date=day, shift="Morning"))
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            await session.commit()

    # Another org's morning of the same day is a different session entirely.
    other_org = await _new_org(test_session_factory, "Other Centre")
    async with test_session_factory() as session:
        session.add(ExamSession(org_id=other_org, date=day, shift="Morning"))
        await session.commit()
