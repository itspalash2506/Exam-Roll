"""Seating plan API (FUTURE_UNIFIED.md §15.5, PROMPTS.md F04 item 5).

Server-authoritative by design (§15.6): every edit is a request, and the
response is the whole re-validated plan. There is no client-side allocation
logic anywhere, so a stale browser tab cannot produce a chart the server
never agreed to.

The plan itself is created under the session that owns it
(`POST /sessions/{id}/plans`) and everything afterwards is addressed by plan
id, which is why this router declares its paths in full rather than taking a
prefix — the two halves belong to one resource.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user, require_org
from app.database import get_db
from app.models.db_models import SeatingPlan, User
from app.services.seating import lifecycle
from app.services.seating.lifecycle import SeatingError
from app.services.seating.validator import violation_dicts

logger = logging.getLogger(__name__)
router = APIRouter(tags=["plans"], dependencies=[Depends(require_org)])


# ── Request models ──────────────────────────────────────────────────────────


class PlanRoomRequest(BaseModel):
    room_id: str
    # NULL = this room takes any paper in the session (§15.2 step 5).
    exam_id: str | None = None


class CreatePlanRequest(BaseModel):
    rooms: list[PlanRoomRequest]
    # Any subset of §15.3's keys; the rest come from the defaults, and the
    # RESOLVED result is what gets stored on the plan.
    strategy: dict | None = None


class SeatRef(BaseModel):
    room_id: str
    col_index: int
    seat_index: int
    bench_pos: int = 1


class MoveRequest(BaseModel):
    student_id: str
    offering_id: str
    to: SeatRef


class SwapRequest(BaseModel):
    seat_a: SeatRef
    seat_b: SeatRef


class LockRequest(BaseModel):
    seat: SeatRef
    locked: bool = True


class RerunRequest(BaseModel):
    strategy: dict | None = None


class NewVersionRequest(BaseModel):
    # Omit to carry the current plan's room list forward unchanged.
    rooms: list[PlanRoomRequest] | None = None
    strategy: dict | None = None


# ── Response models ─────────────────────────────────────────────────────────


class AssignmentOut(BaseModel):
    room_id: str
    col_index: int
    seat_index: int
    bench_pos: int
    student_id: str
    offering_id: str
    roll_number: str | None = None
    exam_code: str | None = None
    locked: bool


class PlanRoomOut(BaseModel):
    room_id: str
    name: str
    order_index: int
    exam_id: str | None = None
    seat_columns: list[dict]
    blocked_seats: list[dict]
    seats_per_bench: int


class UnseatedOut(BaseModel):
    student_id: str
    offering_id: str
    roll_number: str
    exam_code: str


class StaleLockOut(BaseModel):
    room_id: str
    col_index: int
    seat_index: int
    bench_pos: int
    student_id: str
    offering_id: str
    reason: str


class PlanOut(BaseModel):
    id: str
    session_id: str
    version: int
    status: str
    strategy: dict
    seed: int
    gaps: list[dict]
    published_at: str | None = None
    roster_size: int
    rooms: list[PlanRoomOut]
    assignments: list[AssignmentOut]
    unseated: list[UnseatedOut]
    violations: list[dict]
    # Locks the last allocation could not honour — a seat that has since
    # been blocked, a room dropped from the plan, a candidate no longer on
    # the roster. Surfaced, never silently swallowed.
    stale_locks: list[StaleLockOut] = []


def _to_out(described: dict) -> PlanOut:
    plan: SeatingPlan = described["plan"]
    rolls = described["roll_by_key"]
    codes = described["code_by_key"]
    return PlanOut(
        id=plan.id,
        session_id=plan.session_id,
        version=plan.version,
        status=plan.status,
        strategy=dict(plan.strategy or {}),
        seed=plan.seed,
        gaps=list(plan.gaps or []),
        published_at=plan.published_at.isoformat() if plan.published_at else None,
        roster_size=described["roster_size"],
        rooms=[
            PlanRoomOut(
                room_id=r.room_id,
                name=r.name,
                order_index=r.order_index,
                exam_id=r.exam_id,
                seat_columns=[dict(c) for c in r.seat_columns],
                blocked_seats=[dict(b) for b in r.blocked_seats],
                seats_per_bench=r.seats_per_bench,
            )
            for r in described["rooms"]
        ],
        assignments=[
            AssignmentOut(
                room_id=a.room_id,
                col_index=a.col_index,
                seat_index=a.seat_index,
                bench_pos=a.bench_pos,
                student_id=a.student_id,
                offering_id=a.offering_id,
                roll_number=rolls.get(a.candidate),
                exam_code=codes.get(a.candidate),
                locked=a.locked,
            )
            for a in described["assignments"]
        ],
        unseated=[
            UnseatedOut(
                student_id=e.student_id,
                offering_id=e.offering_id,
                roll_number=e.roll_number,
                exam_code=e.exam_code,
            )
            for e in described["unseated"]
        ],
        violations=violation_dicts(described["violations"]),
        stale_locks=[
            StaleLockOut(
                room_id=s.assignment.room_id,
                col_index=s.assignment.col_index,
                seat_index=s.assignment.seat_index,
                bench_pos=s.assignment.bench_pos,
                student_id=s.assignment.student_id,
                offering_id=s.assignment.offering_id,
                reason=s.reason,
            )
            for s in described["stale_locks"]
        ],
    )


async def _plan_or_404(plan_id: str, org_id: str, db: AsyncSession) -> SeatingPlan:
    try:
        return await lifecycle.get_plan(db, org_id, plan_id)
    except SeatingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


async def _respond(db: AsyncSession, org_id: str, plan: SeatingPlan, stale=()) -> PlanOut:
    return _to_out(await lifecycle.describe(db, org_id, plan, stale))


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/sessions/{session_id}/plans", response_model=list[PlanOut])
async def list_session_plans(
    session_id: str,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    plans = (
        await db.execute(
            select(SeatingPlan)
            .where(SeatingPlan.session_id == session_id, SeatingPlan.org_id == org_id)
            .order_by(SeatingPlan.version)
        )
    ).scalars().all()
    return [await _respond(db, org_id, p) for p in plans]


@router.post("/sessions/{session_id}/plans", response_model=PlanOut)
async def create_plan(
    session_id: str,
    req: CreatePlanRequest,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    try:
        plan, result = await lifecycle.create_draft(
            db, org_id, session_id,
            [r.model_dump() for r in req.rooms], req.strategy, user.id,
        )
    except SeatingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return await _respond(db, org_id, plan, result.stale_locks)


@router.get("/plans/{plan_id}", response_model=PlanOut)
async def read_plan(
    plan_id: str,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    return await _respond(db, org_id, await _plan_or_404(plan_id, org_id, db))


@router.post("/plans/{plan_id}/move", response_model=PlanOut)
async def move_candidate(
    plan_id: str,
    req: MoveRequest,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    plan = await _plan_or_404(plan_id, org_id, db)
    try:
        await lifecycle.move(
            db, org_id, plan, req.student_id, req.offering_id,
            req.to.room_id, req.to.col_index, req.to.seat_index, req.to.bench_pos,
        )
    except SeatingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return await _respond(db, org_id, plan)


@router.post("/plans/{plan_id}/swap", response_model=PlanOut)
async def swap_seats(
    plan_id: str,
    req: SwapRequest,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    plan = await _plan_or_404(plan_id, org_id, db)
    try:
        await lifecycle.swap(
            db, org_id, plan, req.seat_a.model_dump(), req.seat_b.model_dump()
        )
    except SeatingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return await _respond(db, org_id, plan)


@router.post("/plans/{plan_id}/lock", response_model=PlanOut)
async def lock_seat(
    plan_id: str,
    req: LockRequest,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    plan = await _plan_or_404(plan_id, org_id, db)
    try:
        await lifecycle.set_lock(
            db, org_id, plan, req.seat.room_id, req.seat.col_index,
            req.seat.seat_index, req.seat.bench_pos, req.locked,
        )
    except SeatingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return await _respond(db, org_id, plan)


@router.post("/plans/{plan_id}/rerun", response_model=PlanOut)
async def rerun_plan(
    plan_id: str,
    req: RerunRequest | None = None,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    plan = await _plan_or_404(plan_id, org_id, db)
    try:
        result = await lifecycle.rerun(db, org_id, plan, (req.strategy if req else None))
    except SeatingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return await _respond(db, org_id, plan, result.stale_locks)


@router.post("/plans/{plan_id}/publish", response_model=PlanOut)
async def publish_plan(
    plan_id: str,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    """Freeze the plan. 409 if anyone is unseated (naming the rolls) or any
    validator violation stands; 403 unless the caller may publish."""
    plan = await _plan_or_404(plan_id, org_id, db)
    try:
        await lifecycle.publish(db, org_id, plan, user)
    except SeatingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return await _respond(db, org_id, plan)


@router.post("/plans/{plan_id}/new-version", response_model=PlanOut)
async def create_new_version(
    plan_id: str,
    req: NewVersionRequest | None = None,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    plan = await _plan_or_404(plan_id, org_id, db)
    try:
        successor, result = await lifecycle.new_version(
            db, org_id, plan,
            ([r.model_dump() for r in req.rooms] if req and req.rooms else None),
            (req.strategy if req else None),
            user.id,
        )
    except SeatingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return await _respond(db, org_id, successor, result.stale_locks)
