import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_org
from app.database import get_db
from app.models.db_models import College

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/colleges", tags=["colleges"], dependencies=[Depends(require_org)])


class CollegeCreate(BaseModel):
    name: str
    short_name: str | None = None


class CollegeOut(BaseModel):
    id: str
    name: str
    short_name: str | None = None


def _to_out(college: College) -> CollegeOut:
    return CollegeOut(id=college.id, name=college.name, short_name=college.short_name)


@router.get("", response_model=list[CollegeOut])
async def list_colleges(org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(College).where(College.org_id == org_id).order_by(College.name)
    )
    return [_to_out(c) for c in result.scalars().all()]


@router.post("", response_model=CollegeOut)
async def create_college(
    req: CollegeCreate, org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)
):
    college = College(org_id=org_id, name=req.name, short_name=req.short_name)
    db.add(college)
    await db.commit()
    return _to_out(college)
