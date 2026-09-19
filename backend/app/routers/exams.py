import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_org
from app.database import get_db
from app.models.db_models import Exam

logger = logging.getLogger(__name__)
# Backs the exam+college picker (§14.3) — a caller may inline-create an exam
# rather than choosing an existing one, which is all this small CRUD surface
# needs to support today.
router = APIRouter(prefix="/exams", tags=["exams"], dependencies=[Depends(require_org)])


class ExamCreate(BaseModel):
    title: str
    programme_label: str | None = None
    semester: str | None = None
    year: int | None = None


class ExamOut(BaseModel):
    id: str
    title: str
    programme_label: str | None = None
    semester: str | None = None
    year: int | None = None
    status: str


def _to_out(exam: Exam) -> ExamOut:
    return ExamOut(
        id=exam.id,
        title=exam.title,
        programme_label=exam.programme_label,
        semester=exam.semester,
        year=exam.year,
        status=exam.status,
    )


@router.get("", response_model=list[ExamOut])
async def list_exams(org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Exam).where(Exam.org_id == org_id).order_by(Exam.created_at.desc())
    )
    return [_to_out(e) for e in result.scalars().all()]


@router.post("", response_model=ExamOut)
async def create_exam(
    req: ExamCreate, org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)
):
    exam = Exam(
        org_id=org_id,
        title=req.title,
        programme_label=req.programme_label,
        semester=req.semester,
        year=req.year,
    )
    db.add(exam)
    await db.commit()
    return _to_out(exam)
