import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_org
from app.database import get_db
from app.models.db_models import Course, Enrollment, Exam, SubjectOffering

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


class OfferingOut(BaseModel):
    id: str
    exam_code: str
    subject_name: str
    paper_no: str | None = None
    group_label: str | None = None
    course_id: str | None = None
    course_name: str | None = None
    enrollment_count: int


@router.get("/{exam_id}/offerings", response_model=list[OfferingOut])
async def list_exam_offerings(
    exam_id: str, org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)
):
    """Backs the session setup papers multi-select (§15.2 step 3), which
    groups papers by exam (this endpoint's scope) and course (course_name,
    grouped client-side — null for an offering with no course link yet)
    with real enrolment counts, not guesses."""
    exam = (
        await db.execute(select(Exam).where(Exam.id == exam_id, Exam.org_id == org_id))
    ).scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    result = await db.execute(
        select(
            SubjectOffering,
            Course.name,
            func.count(Enrollment.id).label("enrollment_count"),
        )
        .outerjoin(Course, Course.id == SubjectOffering.course_id)
        .outerjoin(Enrollment, Enrollment.offering_id == SubjectOffering.id)
        .where(SubjectOffering.exam_id == exam_id, SubjectOffering.org_id == org_id)
        .group_by(SubjectOffering.id, Course.name)
        .order_by(SubjectOffering.exam_code)
    )
    return [
        OfferingOut(
            id=offering.id,
            exam_code=offering.exam_code,
            subject_name=offering.subject_name,
            paper_no=offering.paper_no,
            group_label=offering.group_label,
            course_id=offering.course_id,
            course_name=course_name,
            enrollment_count=count,
        )
        for offering, course_name, count in result.all()
    ]
