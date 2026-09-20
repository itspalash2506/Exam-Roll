import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_org
from app.database import get_db
from app.models.db_models import Room, SeatingPlan, SeatingPlanRoom
from app.schemas.schemas import BlockedSeatSpec, RoomCreate, SeatColumnSpec

logger = logging.getLogger(__name__)
# Backs the room library (§15.1) — CRUD plus the "generate N identical
# rooms" dialog. Deleting a room used by a seating plan is refused with 409
# (deactivate instead) now that SeatingPlanRoom exists — see delete_room.
router = APIRouter(prefix="/rooms", tags=["rooms"], dependencies=[Depends(require_org)])


class RoomUpdate(BaseModel):
    """Same shape as RoomCreate, every field optional — a PATCH merges onto
    the room's current values, then the MERGED result is re-validated
    through RoomCreate's own validators (see update_room below), so the DB
    can never end up holding a room whose blocked_seats disagree with its
    seat_columns just because a caller only meant to rename it."""

    name: str | None = None
    building: str | None = None
    is_active: bool | None = None
    sort_priority: int | None = None
    seat_columns: list[SeatColumnSpec] | None = None
    blocked_seats: list[BlockedSeatSpec] | None = None
    seats_per_bench: int | None = None
    notes: str | None = None


class RoomOut(BaseModel):
    id: str
    name: str
    building: str | None = None
    is_active: bool
    sort_priority: int
    seat_columns: list[SeatColumnSpec]
    blocked_seats: list[BlockedSeatSpec]
    seats_per_bench: int
    notes: str | None = None
    capacity: int


class GenerateRoomsRequest(BaseModel):
    count: int
    columns: int
    seats_per_column: int
    seats_per_bench: int = 1
    name_pattern: str = "Room No {n}"


def _to_out(room: Room) -> RoomOut:
    return RoomOut(
        id=room.id,
        name=room.name,
        building=room.building,
        is_active=room.is_active,
        sort_priority=room.sort_priority,
        seat_columns=room.seat_columns,
        blocked_seats=room.blocked_seats,
        seats_per_bench=room.seats_per_bench,
        notes=room.notes,
        capacity=room.capacity,
    )


async def _get_room(room_id: str, org_id: str, db: AsyncSession) -> Room:
    result = await db.execute(
        select(Room).where(Room.id == room_id, Room.org_id == org_id)
    )
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.get("", response_model=list[RoomOut])
async def list_rooms(org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Room).where(Room.org_id == org_id).order_by(Room.sort_priority, Room.name)
    )
    return [_to_out(r) for r in result.scalars().all()]


@router.post("", response_model=RoomOut)
async def create_room(
    req: RoomCreate, org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)
):
    room = Room(
        org_id=org_id,
        name=req.name,
        building=req.building,
        is_active=req.is_active,
        sort_priority=req.sort_priority,
        seat_columns=[c.model_dump() for c in req.seat_columns],
        blocked_seats=[b.model_dump() for b in req.blocked_seats],
        seats_per_bench=req.seats_per_bench,
        notes=req.notes,
    )
    db.add(room)
    await db.commit()
    return _to_out(room)


@router.post("/generate", response_model=list[RoomOut])
async def generate_rooms(
    req: GenerateRoomsRequest,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    """§15.1 Option 1 — N identical rooms, one uniform column layout each.
    Every room created this way is still a normal Room afterward and can be
    hand-edited into Option 2's per-room custom shape (add/remove a column,
    block seats) without any special-casing on the read side."""
    if req.count < 1:
        raise HTTPException(status_code=422, detail="count must be at least 1")
    if "{n}" not in req.name_pattern:
        raise HTTPException(status_code=422, detail="name_pattern must contain '{n}'")

    # Route every room through RoomCreate's own validation (seat count >= 1,
    # bench size known) rather than constructing Room rows directly — one
    # validation path, not two that could silently drift apart.
    try:
        template = RoomCreate(
            name=req.name_pattern.format(n=1),
            seat_columns=[
                SeatColumnSpec(label=f"Col {i + 1}", seats=req.seats_per_column)
                for i in range(req.columns)
            ],
            seats_per_bench=req.seats_per_bench,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    rooms = []
    for n in range(1, req.count + 1):
        room = Room(
            org_id=org_id,
            name=req.name_pattern.format(n=n),
            is_active=True,
            sort_priority=n,
            seat_columns=[c.model_dump() for c in template.seat_columns],
            blocked_seats=[],
            seats_per_bench=template.seats_per_bench,
        )
        db.add(room)
        rooms.append(room)
    await db.commit()
    return [_to_out(r) for r in rooms]


@router.get("/{room_id}", response_model=RoomOut)
async def get_room(
    room_id: str, org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)
):
    return _to_out(await _get_room(room_id, org_id, db))


@router.patch("/{room_id}", response_model=RoomOut)
async def update_room(
    room_id: str,
    req: RoomUpdate,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    room = await _get_room(room_id, org_id, db)
    updates = req.model_dump(exclude_unset=True)

    merged = dict(
        name=room.name,
        building=room.building,
        is_active=room.is_active,
        sort_priority=room.sort_priority,
        seat_columns=room.seat_columns,
        blocked_seats=room.blocked_seats,
        seats_per_bench=room.seats_per_bench,
        notes=room.notes,
    )
    merged.update(updates)

    try:
        validated = RoomCreate(**merged)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    room.name = validated.name
    room.building = validated.building
    room.is_active = validated.is_active
    room.sort_priority = validated.sort_priority
    room.seat_columns = [c.model_dump() for c in validated.seat_columns]
    room.blocked_seats = [b.model_dump() for b in validated.blocked_seats]
    room.seats_per_bench = validated.seats_per_bench
    room.notes = validated.notes
    await db.commit()
    return _to_out(room)


@router.delete("/{room_id}", status_code=204)
async def delete_room(
    room_id: str, org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)
):
    room = await _get_room(room_id, org_id, db)
    # F04 resolved this router's TODO: SeatingPlanRoom now exists, so a room
    # CAN be referenced by a plan. §15.1 — a room in use is deactivated,
    # never deleted. Checked here rather than left to the FK's ON DELETE
    # RESTRICT for two reasons: SQLite does not enforce foreign keys unless
    # the pragma is on (so the delete would silently orphan the plan's
    # seats), and on Postgres it would surface as a 500 instead of a
    # message saying what to do instead.
    used_by = (
        await db.execute(
            select(SeatingPlan.version)
            .join(SeatingPlanRoom, SeatingPlanRoom.plan_id == SeatingPlan.id)
            .where(SeatingPlanRoom.room_id == room_id)
            .order_by(SeatingPlan.version)
        )
    ).scalars().all()
    if used_by:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{room.name} is used by {len(used_by)} seating plan(s) and "
                "cannot be deleted — deactivate it instead"
            ),
        )
    await db.delete(room)
    await db.commit()
