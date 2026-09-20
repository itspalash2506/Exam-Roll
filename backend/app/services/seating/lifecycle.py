"""Seating plan lifecycle (FUTURE_UNIFIED.md §15.5).

`draft` → clerk edits (move / swap / lock / block a seat + re-run) →
`published` by a controller → any later change is `version + 1`, and the
plan it came from becomes `superseded`.

This is the ONLY layer in `services/seating/` that touches the database.
`allocator.py` and `validator.py` stay pure so they can be property-tested
exhaustively; everything here is the boring part — load the roster, run the
pure functions, write the rows back, and refuse the operations §15.5 says
must be refused.

Two rules worth stating because they are easy to get wrong later:

1. **A published plan is frozen.** Every edit endpoint refuses on anything
   but a draft. Attendance rows will reference the plan in force at the
   session's start (§15.5); a plan that could change under them would make
   the attendance record unverifiable.
2. **A hand edit locks the seat it touches.** `move` and `swap` set
   `locked = True` on the seats they move. Without that, the very next
   "re-run with locks" would silently undo a clerk's deliberate correction
   — the same silent-default failure class as P0-1, with a candidate in the
   wrong room as the outcome.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import (
    Course,
    Enrollment,
    ExamSession,
    Room,
    SeatAssignment,
    SeatingPlan,
    SeatingPlanRoom,
    SessionPaper,
    Student,
    SubjectOffering,
    User,
)
from app.services.seating.allocator import allocate, normalize_strategy
from app.services.seating.types import (
    AllocationResult,
    Assignment,
    PlanData,
    RoomSpec,
    RosterEntry,
    StaleLock,
    Violation,
)
from app.services.seating.validator import validate

logger = logging.getLogger(__name__)

# ── Who may publish ─────────────────────────────────────────────────────────
# Q9, answered 2026-09-20 (FUTURE_UNIFIED.md §23.1): "Only the
# superintendent (`controller`) may publish." PROMPTS.md's F04 text predates
# this codebase's real session auth and talks about "a pilot-key user with
# role=controller chosen at key entry"; that mechanism does not exist here.
#
# Chosen: widen `User.role`'s accepted values to include "controller" and
# gate publish on this set. No migration is needed — `role` is a plain
# String(20) column — and `admin` is treated as a superset because the only
# account `scripts/create_admin.py` can create today is an admin, so a
# stricter rule would make publishing impossible on a fresh pilot install.
# Gate M owns real role enforcement everywhere else (§16.4); this is the one
# place a role is checked, and it is checked because publishing is the
# irreversible step that freezes the plan and opens attendance.
PUBLISH_ROLES = ("admin", "controller")


class SeatingError(Exception):
    """A lifecycle rule was broken. Carries the HTTP status the router
    should use, so the rule and its status live in one place instead of
    being re-decided per endpoint."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Loading ─────────────────────────────────────────────────────────────────


async def build_roster(db: AsyncSession, org_id: str, session_id: str) -> list[RosterEntry]:
    """`Enrollment ⋈ SessionPaper ⋈ Student` (§15.2 step 3).

    A student enrolled in two of the session's papers legitimately appears
    twice — that is a clash, detected when the paper list is saved, and
    publishing is refused until it is acknowledged (see `publish`).
    """
    rows = (
        await db.execute(
            select(Enrollment, Student, SubjectOffering)
            .join(SessionPaper, SessionPaper.offering_id == Enrollment.offering_id)
            .join(Student, Student.id == Enrollment.student_id)
            .join(SubjectOffering, SubjectOffering.id == Enrollment.offering_id)
            .where(
                SessionPaper.session_id == session_id,
                Enrollment.org_id == org_id,
            )
        )
    ).all()

    course_ids = {o.course_id for _e, _s, o in rows if o.course_id}
    course_names: dict[str, str] = {}
    if course_ids:
        for course in (
            await db.execute(select(Course).where(Course.id.in_(course_ids)))
        ).scalars():
            course_names[course.id] = course.name

    roster = [
        RosterEntry(
            student_id=student.id,
            offering_id=offering.id,
            roll_number=student.roll_number,
            roll_sort_key=student.roll_sort_key,
            exam_code=offering.exam_code,
            # A per-paper override beats the student's general status —
            # a candidate can be ATKT in one paper and regular in another.
            status=enrollment.status_override or student.status or "regular",
            exam_id=offering.exam_id,
            course_id=offering.course_id,
            course_name=course_names.get(offering.course_id or ""),
        )
        for enrollment, student, offering in rows
    ]
    roster.sort(key=lambda e: (e.roll_sort_key, e.roll_number, e.offering_id))
    return roster


async def plan_room_specs(db: AsyncSession, plan_id: str) -> list[RoomSpec]:
    rows = (
        await db.execute(
            select(SeatingPlanRoom, Room)
            .join(Room, Room.id == SeatingPlanRoom.room_id)
            .where(SeatingPlanRoom.plan_id == plan_id)
            .order_by(SeatingPlanRoom.order_index, SeatingPlanRoom.room_id)
        )
    ).all()
    return [
        RoomSpec(
            room_id=room.id,
            seat_columns=list(room.seat_columns or []),
            blocked_seats=list(room.blocked_seats or []),
            seats_per_bench=room.seats_per_bench or 1,
            order_index=plan_room.order_index,
            exam_id=plan_room.exam_id,
            name=room.name,
        )
        for plan_room, room in rows
    ]


async def plan_assignments(db: AsyncSession, plan_id: str) -> list[SeatAssignment]:
    return list(
        (
            await db.execute(
                select(SeatAssignment)
                .where(SeatAssignment.plan_id == plan_id)
                .order_by(
                    SeatAssignment.room_id,
                    SeatAssignment.col_index,
                    SeatAssignment.seat_index,
                    SeatAssignment.bench_pos,
                )
            )
        ).scalars()
    )


def to_assignment(row: SeatAssignment) -> Assignment:
    return Assignment(
        room_id=row.room_id,
        col_index=row.col_index,
        seat_index=row.seat_index,
        bench_pos=row.bench_pos,
        student_id=row.student_id,
        offering_id=row.offering_id,
        locked=bool(row.locked),
    )


async def get_plan(db: AsyncSession, org_id: str, plan_id: str) -> SeatingPlan:
    plan = (
        await db.execute(
            select(SeatingPlan).where(
                SeatingPlan.id == plan_id, SeatingPlan.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    if plan is None:
        # 404, never 403 — a 403 would confirm the plan exists and turn this
        # into an existence oracle for another tenant's data.
        raise SeatingError(404, "Seating plan not found")
    return plan


async def load_plan_data(
    db: AsyncSession, org_id: str, plan: SeatingPlan
) -> tuple[PlanData, list[RosterEntry], list[Assignment]]:
    """Everything the validator needs, read back from the rows themselves.

    `unseated` is DERIVED here (roster minus seated) rather than stored: a
    stored copy could drift out of step with the assignment rows after a
    hand edit, and the one number nobody may be wrong about is who has no
    seat.
    """
    roster = await build_roster(db, org_id, plan.session_id)
    rooms = await plan_room_specs(db, plan.id)
    assignments = [to_assignment(r) for r in await plan_assignments(db, plan.id)]
    seated = {a.candidate for a in assignments}
    unseated = [e for e in roster if e.key not in seated]
    data = PlanData(
        assignments=assignments,
        rooms=rooms,
        roster=roster,
        locks=[a for a in assignments if a.locked],
        unseated=unseated,
        strategy=plan.strategy or {},
    )
    return data, roster, assignments


# ── Writing ─────────────────────────────────────────────────────────────────


async def _replace_assignments(
    db: AsyncSession, plan: SeatingPlan, result: AllocationResult
) -> None:
    await db.execute(delete(SeatAssignment).where(SeatAssignment.plan_id == plan.id))
    await db.flush()
    for a in result.assignments:
        db.add(
            SeatAssignment(
                org_id=plan.org_id,
                plan_id=plan.id,
                room_id=a.room_id,
                col_index=a.col_index,
                seat_index=a.seat_index,
                bench_pos=a.bench_pos,
                student_id=a.student_id,
                offering_id=a.offering_id,
                locked=a.locked,
            )
        )
    plan.strategy = dict(result.strategy)
    plan.seed = int(result.strategy.get("seed", 0))
    plan.gaps = [
        {
            "room_id": g.room_id,
            "col_index": g.col_index,
            "seat_index": g.seat_index,
            "bench_pos": g.bench_pos,
            "reason": g.reason,
        }
        for g in result.gaps
    ]
    await db.flush()


def _require_draft(plan: SeatingPlan) -> None:
    if plan.status != "draft":
        raise SeatingError(
            409,
            f"this plan is {plan.status}; create version {plan.version + 1} "
            "to change it (§15.5 — a published plan is frozen)",
        )


async def _resolve_rooms(
    db: AsyncSession, org_id: str, rooms: Sequence[Mapping[str, Any]]
) -> list[tuple[str, str | None]]:
    if not rooms:
        raise SeatingError(422, "a seating plan needs at least one room")
    resolved: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for spec in rooms:
        room_id = spec.get("room_id")
        if not room_id:
            raise SeatingError(422, "every room entry needs a room_id")
        if room_id in seen:
            raise SeatingError(422, f"room {room_id} is listed twice")
        seen.add(room_id)
        room = (
            await db.execute(
                select(Room).where(Room.id == room_id, Room.org_id == org_id)
            )
        ).scalar_one_or_none()
        if room is None:
            raise SeatingError(404, f"Room {room_id} not found")
        if not room.is_active:
            raise SeatingError(
                422, f"room {room.name!r} is deactivated and cannot be used in a plan"
            )
        resolved.append((room_id, spec.get("exam_id")))
    return resolved


# ── Operations ──────────────────────────────────────────────────────────────


async def create_draft(
    db: AsyncSession,
    org_id: str,
    session_id: str,
    rooms: Sequence[Mapping[str, Any]],
    strategy: Mapping[str, Any] | None,
    user_id: str | None,
) -> tuple[SeatingPlan, AllocationResult]:
    """Version 1 of a session's plan. Refuses if the session already has one
    — a second entry point for "make me a plan" is how two plans for one
    session end up both looking authoritative. Later versions come from
    `new_version`, which supersedes its predecessor explicitly."""
    session = (
        await db.execute(
            select(ExamSession).where(
                ExamSession.id == session_id, ExamSession.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise SeatingError(404, "Session not found")

    existing = (
        await db.execute(
            select(SeatingPlan).where(SeatingPlan.session_id == session_id)
        )
    ).scalars().first()
    if existing is not None:
        raise SeatingError(
            409,
            "this session already has a seating plan; use "
            f"POST /api/v1/plans/{existing.id}/new-version to make another",
        )

    resolved = await _resolve_rooms(db, org_id, rooms)
    plan = SeatingPlan(
        org_id=org_id,
        session_id=session_id,
        version=1,
        status="draft",
        strategy={},
        seed=0,
        gaps=[],
        created_by=user_id,
    )
    db.add(plan)
    await db.flush()
    for order_index, (room_id, exam_id) in enumerate(resolved):
        db.add(
            SeatingPlanRoom(
                org_id=org_id,
                plan_id=plan.id,
                room_id=room_id,
                order_index=order_index,
                exam_id=exam_id,
            )
        )
    await db.flush()

    result = await _run_allocator(db, org_id, plan, strategy, locks=())
    await _replace_assignments(db, plan, result)
    await db.commit()
    return plan, result


async def _run_allocator(
    db: AsyncSession,
    org_id: str,
    plan: SeatingPlan,
    strategy: Mapping[str, Any] | None,
    locks: Sequence[Assignment],
) -> AllocationResult:
    roster = await build_roster(db, org_id, plan.session_id)
    rooms = await plan_room_specs(db, plan.id)
    try:
        return allocate(roster, rooms, strategy, locks)
    except ValueError as exc:
        # Structurally invalid input (a malformed room, an unknown strategy
        # value). Not "it did not all fit" — that is a normal result.
        raise SeatingError(422, str(exc)) from exc


async def rerun(
    db: AsyncSession,
    org_id: str,
    plan: SeatingPlan,
    strategy: Mapping[str, Any] | None = None,
) -> AllocationResult:
    """Re-allocate, keeping every locked seat exactly where it is (§15.5).

    This is also the "block a seat" path: the clerk edits the room (PATCH
    /api/v1/rooms/{id}), then re-runs. A lock on a bench that has since been
    blocked cannot be honoured; it comes back in `stale_locks` rather than
    being applied to a seat that no longer exists.
    """
    _require_draft(plan)
    rows = await plan_assignments(db, plan.id)
    locks = [to_assignment(r) for r in rows if r.locked]
    merged = dict(plan.strategy or {})
    merged.update(strategy or {})
    result = await _run_allocator(db, org_id, plan, merged, locks)
    await _replace_assignments(db, plan, result)
    await db.commit()
    return result


async def move(
    db: AsyncSession,
    org_id: str,
    plan: SeatingPlan,
    student_id: str,
    offering_id: str,
    room_id: str,
    col_index: int,
    seat_index: int,
    bench_pos: int,
) -> None:
    """Move one candidate to an empty, real, unblocked seat.

    The target is checked against the room's own geometry here rather than
    left to the validator: a move onto a seat that does not exist is a
    caller error to refuse, not a plan state to record and report.
    """
    _require_draft(plan)
    rows = await plan_assignments(db, plan.id)
    row = next(
        (r for r in rows if r.student_id == student_id and r.offering_id == offering_id),
        None,
    )
    if row is None:
        raise SeatingError(404, "that candidate is not seated in this plan")
    _check_target_seat(
        await plan_room_specs(db, plan.id), rows, room_id, col_index, seat_index,
        bench_pos, ignore=row,
    )
    row.room_id = room_id
    row.col_index = col_index
    row.seat_index = seat_index
    row.bench_pos = bench_pos
    # See the module docstring: a hand-placed candidate is locked, or the
    # next re-run silently undoes the decision.
    row.locked = True
    await db.commit()


async def swap(
    db: AsyncSession,
    org_id: str,
    plan: SeatingPlan,
    seat_a: Mapping[str, Any],
    seat_b: Mapping[str, Any],
) -> None:
    """Exchange the occupants of two seats. Both must be occupied."""
    _require_draft(plan)
    rows = await plan_assignments(db, plan.id)

    def find(spec: Mapping[str, Any]) -> SeatAssignment:
        match = next(
            (
                r
                for r in rows
                if r.room_id == spec.get("room_id")
                and r.col_index == spec.get("col_index")
                and r.seat_index == spec.get("seat_index")
                and r.bench_pos == spec.get("bench_pos", 1)
            ),
            None,
        )
        if match is None:
            raise SeatingError(
                404,
                "no candidate is seated at "
                f"{spec.get('room_id')} col {spec.get('col_index')} seat "
                f"{spec.get('seat_index')} pos {spec.get('bench_pos', 1)}",
            )
        return match

    first, second = find(seat_a), find(seat_b)
    if first.id == second.id:
        raise SeatingError(422, "cannot swap a seat with itself")

    # Delete both rows, then insert the swapped pair. Updating them in place
    # looks simpler and is wrong: SQLAlchemy batches the two UPDATEs into one
    # executemany, and halfway through it BOTH rows hold the same
    # (plan, student, offering) — UNIQUE(plan_id, student_id, offering_id)
    # fires on the intermediate state, not the final one. Found by
    # test_swap_exchanges_two_occupants_and_locks_both, which failed with
    # exactly that IntegrityError.
    seats = [
        (first.room_id, first.col_index, first.seat_index, first.bench_pos),
        (second.room_id, second.col_index, second.seat_index, second.bench_pos),
    ]
    occupants = [
        (second.student_id, second.offering_id),
        (first.student_id, first.offering_id),
    ]
    await db.delete(first)
    await db.delete(second)
    await db.flush()
    for (room_id, col_index, seat_index, bench_pos), (student_id, offering_id) in zip(
        seats, occupants
    ):
        db.add(
            SeatAssignment(
                org_id=plan.org_id,
                plan_id=plan.id,
                room_id=room_id,
                col_index=col_index,
                seat_index=seat_index,
                bench_pos=bench_pos,
                student_id=student_id,
                offering_id=offering_id,
                # A hand swap is a decision; see the module docstring.
                locked=True,
            )
        )
    await db.commit()


async def set_lock(
    db: AsyncSession,
    org_id: str,
    plan: SeatingPlan,
    room_id: str,
    col_index: int,
    seat_index: int,
    bench_pos: int,
    locked: bool,
) -> None:
    _require_draft(plan)
    rows = await plan_assignments(db, plan.id)
    row = next(
        (
            r
            for r in rows
            if r.room_id == room_id
            and r.col_index == col_index
            and r.seat_index == seat_index
            and r.bench_pos == bench_pos
        ),
        None,
    )
    if row is None:
        raise SeatingError(404, "no candidate is seated at that seat")
    row.locked = locked
    await db.commit()


def _check_target_seat(
    rooms: Sequence[RoomSpec],
    rows: Sequence[SeatAssignment],
    room_id: str,
    col_index: int,
    seat_index: int,
    bench_pos: int,
    ignore: SeatAssignment | None = None,
) -> None:
    room = next((r for r in rooms if r.room_id == room_id), None)
    if room is None:
        raise SeatingError(404, f"Room {room_id} is not part of this plan")
    counts = [int(c.get("seats", 0)) for c in (room.seat_columns or [])]
    if not (1 <= col_index <= len(counts)) or not (
        1 <= seat_index <= counts[col_index - 1]
    ):
        raise SeatingError(
            422,
            f"room {room.name or room_id} has no col {col_index} seat {seat_index}",
        )
    if not (1 <= bench_pos <= (room.seats_per_bench or 1)):
        raise SeatingError(
            422,
            f"bench position {bench_pos} does not exist on a bench seating "
            f"{room.seats_per_bench or 1}",
        )
    blocked = {
        (b.get("col"), b.get("seat")) for b in (room.blocked_seats or [])
    }
    if (col_index, seat_index) in blocked:
        raise SeatingError(
            422, f"col {col_index} seat {seat_index} of {room.name or room_id} is blocked"
        )
    occupant = next(
        (
            r
            for r in rows
            if r.room_id == room_id
            and r.col_index == col_index
            and r.seat_index == seat_index
            and r.bench_pos == bench_pos
            and (ignore is None or r.id != ignore.id)
        ),
        None,
    )
    if occupant is not None:
        raise SeatingError(409, "that seat is already taken — swap instead of moving")


async def publish(
    db: AsyncSession, org_id: str, plan: SeatingPlan, user: User
) -> None:
    """Freeze the plan (§15.5). Refused unless everything is right.

    §15.4: "Publishing is refused while `unseated` is non-empty or any
    violation exists." The 409 names the roll numbers, because "one student
    has no seat" without saying who is not actionable at 9am on exam day.
    """
    if user.role not in PUBLISH_ROLES:
        raise SeatingError(
            403,
            "only a controller may publish a seating plan "
            "(FUTURE_UNIFIED.md §23.1 Q9)",
        )
    if plan.status == "published":
        raise SeatingError(409, "this plan is already published")
    _require_draft(plan)

    session = (
        await db.execute(
            select(ExamSession).where(ExamSession.id == plan.session_id)
        )
    ).scalar_one()
    unacknowledged = [
        c.get("roll_number", "?")
        for c in (session.clashes or [])
        if not c.get("acknowledged")
    ]
    if unacknowledged:
        raise SeatingError(
            409,
            "this session has unacknowledged timetable clashes: "
            + ", ".join(sorted(unacknowledged)),
        )

    data, _roster, _assignments = await load_plan_data(db, org_id, plan)
    if data.unseated:
        rolls = ", ".join(sorted(e.roll_number for e in data.unseated))
        raise SeatingError(
            409, f"{len(data.unseated)} candidate(s) have no seat: {rolls}"
        )
    violations = validate(data)
    if violations:
        raise SeatingError(
            409,
            f"{len(violations)} validation violation(s) must be resolved first: "
            + "; ".join(v.message for v in violations[:5]),
        )

    plan.status = "published"
    plan.published_by = user.id
    plan.published_at = _utcnow()
    await db.commit()


async def new_version(
    db: AsyncSession,
    org_id: str,
    plan: SeatingPlan,
    rooms: Sequence[Mapping[str, Any]] | None,
    strategy: Mapping[str, Any] | None,
    user_id: str | None,
) -> tuple[SeatingPlan, AllocationResult]:
    """Copy the locks forward into `version + 1` and supersede this plan.

    §15.5: regenerating after publish must be explicit, never implicit. The
    old plan's rows are left exactly as they were — attendance taken against
    version 1 must still resolve to version 1's seats.
    """
    highest = (
        await db.execute(
            select(SeatingPlan)
            .where(SeatingPlan.session_id == plan.session_id)
            .order_by(SeatingPlan.version.desc())
        )
    ).scalars().first()
    next_version = (highest.version if highest else plan.version) + 1

    source_rooms = await plan_room_specs(db, plan.id)
    if rooms is None:
        resolved = [(r.room_id, r.exam_id) for r in source_rooms]
    else:
        resolved = await _resolve_rooms(db, org_id, rooms)

    successor = SeatingPlan(
        org_id=org_id,
        session_id=plan.session_id,
        version=next_version,
        status="draft",
        strategy={},
        seed=0,
        gaps=[],
        created_by=user_id,
    )
    db.add(successor)
    await db.flush()
    for order_index, (room_id, exam_id) in enumerate(resolved):
        db.add(
            SeatingPlanRoom(
                org_id=org_id,
                plan_id=successor.id,
                room_id=room_id,
                order_index=order_index,
                exam_id=exam_id,
            )
        )
    await db.flush()

    locks = [
        to_assignment(r) for r in await plan_assignments(db, plan.id) if r.locked
    ]
    merged = dict(plan.strategy or {})
    merged.update(strategy or {})
    result = await _run_allocator(db, org_id, successor, merged, locks)
    await _replace_assignments(db, successor, result)

    plan.status = "superseded"
    await db.commit()
    return successor, result


# ── Read model ──────────────────────────────────────────────────────────────


async def describe(
    db: AsyncSession, org_id: str, plan: SeatingPlan, stale_locks: Sequence[StaleLock] = ()
) -> dict[str, Any]:
    """The plan as the API returns it: rows, rooms, violations, unseated.

    Violations are recomputed on every read rather than cached. They are
    cheap, and a cached violation list is a list that can say "no problems"
    about a plan somebody has since edited.
    """
    data, roster, assignments = await load_plan_data(db, org_id, plan)
    violations: list[Violation] = validate(data)
    roll_by_key = {e.key: e.roll_number for e in roster}
    code_by_key = {e.key: e.exam_code for e in roster}
    return {
        "plan": plan,
        "rooms": data.rooms,
        "assignments": assignments,
        "roll_by_key": roll_by_key,
        "code_by_key": code_by_key,
        "unseated": list(data.unseated),
        "violations": violations,
        "roster_size": len(roster),
        "stale_locks": list(stale_locks),
    }


def resolved_strategy(strategy: Mapping[str, Any] | None) -> dict[str, Any]:
    """Public helper for callers that want §15.3's defaults without running
    an allocation (the strategy drawer's initial state, for instance)."""
    return normalize_strategy(strategy, ())
