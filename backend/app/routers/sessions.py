import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_org
from app.database import get_db
from app.models.db_models import Enrollment, ExamSession, SessionPaper, Student, SubjectOffering

logger = logging.getLogger(__name__)
# Session setup (§15.2) — a centre day-shift, the papers sitting in it, and
# the clash check that runs whenever the paper set is saved.
router = APIRouter(prefix="/sessions", tags=["sessions"], dependencies=[Depends(require_org)])


class SessionCreate(BaseModel):
    date: str  # ISO date, e.g. "2026-09-15"
    shift: str
    start_time: str | None = None  # "HH:MM"
    end_time: str | None = None
    label: str | None = None


class ClashEntry(BaseModel):
    student_id: str
    roll_number: str
    exam_codes: list[str]
    acknowledged: bool = False


class SessionOut(BaseModel):
    id: str
    date: str
    shift: str
    start_time: str | None = None
    end_time: str | None = None
    label: str | None = None
    offering_ids: list[str] = []
    clashes: list[ClashEntry] = []


class SetPapersRequest(BaseModel):
    offering_ids: list[str]


class AcknowledgeClashRequest(BaseModel):
    student_id: str


def _to_out(session: ExamSession, offering_ids: list[str]) -> SessionOut:
    return SessionOut(
        id=session.id,
        date=session.date.isoformat(),
        shift=session.shift,
        start_time=session.start_time.isoformat() if session.start_time else None,
        end_time=session.end_time.isoformat() if session.end_time else None,
        label=session.label,
        offering_ids=offering_ids,
        clashes=[ClashEntry(**c) for c in (session.clashes or [])],
    )


async def _get_session(session_id: str, org_id: str, db: AsyncSession) -> ExamSession:
    result = await db.execute(
        select(ExamSession).where(ExamSession.id == session_id, ExamSession.org_id == org_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def _offering_ids_for(session_id: str, db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(SessionPaper.offering_id).where(SessionPaper.session_id == session_id)
    )
    return [row[0] for row in result.all()]


@router.get("", response_model=list[SessionOut])
async def list_sessions(org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ExamSession).where(ExamSession.org_id == org_id).order_by(ExamSession.date, ExamSession.shift)
    )
    sessions = result.scalars().all()
    out = []
    for s in sessions:
        out.append(_to_out(s, await _offering_ids_for(s.id, db)))
    return out


@router.post("", response_model=SessionOut)
async def create_session(
    req: SessionCreate, org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)
):
    import datetime as _dt

    try:
        date_val = _dt.date.fromisoformat(req.date)
        start_val = _dt.time.fromisoformat(req.start_time) if req.start_time else None
        end_val = _dt.time.fromisoformat(req.end_time) if req.end_time else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date/time: {exc}") from exc

    session = ExamSession(
        org_id=org_id, date=date_val, shift=req.shift,
        start_time=start_val, end_time=end_val, label=req.label,
    )
    db.add(session)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A session already exists for {req.date} · {req.shift}",
        ) from exc
    return _to_out(session, [])


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str, org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)
):
    session = await _get_session(session_id, org_id, db)
    return _to_out(session, await _offering_ids_for(session_id, db))


async def _compute_clashes(
    session_org_id: str, offering_ids: list[str], db: AsyncSession
) -> list[dict]:
    """A student enrolled in >=2 of this session's papers is a real
    timetable clash — they cannot sit two papers in the same slot (§15.2
    step 4). Query Enrollment directly rather than the roster the allocator
    will eventually build, since this has to run at save time, before any
    plan exists."""
    if len(offering_ids) < 2:
        return []

    result = await db.execute(
        select(Enrollment.student_id, SubjectOffering.exam_code)
        .join(SubjectOffering, SubjectOffering.id == Enrollment.offering_id)
        .where(
            Enrollment.org_id == session_org_id,
            Enrollment.offering_id.in_(offering_ids),
        )
    )
    codes_by_student: dict[str, list[str]] = {}
    for student_id, exam_code in result.all():
        codes_by_student.setdefault(student_id, []).append(exam_code)

    clashing_ids = [sid for sid, codes in codes_by_student.items() if len(set(codes)) >= 2]
    if not clashing_ids:
        return []

    students = (
        await db.execute(select(Student).where(Student.id.in_(clashing_ids)))
    ).scalars().all()
    roll_by_id = {s.id: s.roll_number for s in students}

    return [
        {
            "student_id": sid,
            "roll_number": roll_by_id.get(sid, ""),
            "exam_codes": sorted(set(codes_by_student[sid])),
            "acknowledged": False,
        }
        for sid in clashing_ids
    ]


@router.put("/{session_id}/papers", response_model=SessionOut)
async def set_session_papers(
    session_id: str,
    req: SetPapersRequest,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_session(session_id, org_id, db)

    if req.offering_ids:
        result = await db.execute(
            select(SubjectOffering.id).where(
                SubjectOffering.id.in_(req.offering_ids), SubjectOffering.org_id == org_id
            )
        )
        found = {row[0] for row in result.all()}
        missing = set(req.offering_ids) - found
        if missing:
            raise HTTPException(
                status_code=422, detail=f"Unknown offering id(s): {sorted(missing)}"
            )

    existing = (
        await db.execute(select(SessionPaper).where(SessionPaper.session_id == session_id))
    ).scalars().all()
    for row in existing:
        await db.delete(row)
    await db.flush()

    for offering_id in req.offering_ids:
        db.add(SessionPaper(org_id=org_id, session_id=session_id, offering_id=offering_id))

    new_clashes = await _compute_clashes(org_id, req.offering_ids, db)
    # A clash already acknowledged survives a re-save if the SAME student
    # still clashes over the SAME set of papers — re-saving the paper list
    # (e.g. adding an unrelated paper) shouldn't silently re-flag something
    # a controller already reviewed. A genuinely different exam_code set for
    # that student is treated as a new, unacknowledged clash.
    previously_acknowledged = {
        (c["student_id"], tuple(sorted(c["exam_codes"])))
        for c in (session.clashes or [])
        if c.get("acknowledged")
    }
    for clash in new_clashes:
        key = (clash["student_id"], tuple(sorted(clash["exam_codes"])))
        if key in previously_acknowledged:
            clash["acknowledged"] = True

    session.clashes = new_clashes
    await db.commit()
    return _to_out(session, req.offering_ids)


@router.post("/{session_id}/clashes/acknowledge", response_model=SessionOut)
async def acknowledge_clash(
    session_id: str,
    req: AcknowledgeClashRequest,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_session(session_id, org_id, db)
    # Copy each entry into a NEW dict, not just the outer list — SQLAlchemy's
    # plain JSON column detects a change by comparing the newly-assigned
    # value against what it already holds. `list(session.clashes)` only
    # shallow-copies the outer list; the inner dicts stay the SAME objects
    # still referenced by `session.clashes`, so mutating one in place before
    # reassigning makes old == new by the time SQLAlchemy compares them, and
    # the UPDATE is silently skipped (confirmed: no SQL emitted, no dirty
    # flag set). Reproduced and fixed 2026-09-20 while testing this endpoint.
    clashes = [dict(c) for c in (session.clashes or [])]
    match = next((c for c in clashes if c["student_id"] == req.student_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="No clash recorded for this student")
    match["acknowledged"] = True
    session.clashes = clashes
    await db.commit()
    return _to_out(session, await _offering_ids_for(session_id, db))
