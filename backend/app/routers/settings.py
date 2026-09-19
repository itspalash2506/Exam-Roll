import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_org
from app.database import get_db
from app.models.db_models import Organization

logger = logging.getLogger(__name__)
# A minimal org settings surface (P10, FUTURE_UNIFIED.md §8.4 item 2) — today
# this is only the AI opt-out toggle plus the identity fields already on
# Organization. per_candidate_rate/currency are deferred: they don't exist as
# columns yet, and adding them now (ahead of Gate F's O6 claim generator,
# which is the only consumer) would mean a migration for an unused field.
router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_org)])


class OrgSettingsOut(BaseModel):
    name: str
    centre_code: str | None = None
    university_name: str | None = None
    ai_processing_enabled: bool


class OrgSettingsUpdate(BaseModel):
    name: str | None = None
    centre_code: str | None = None
    university_name: str | None = None
    ai_processing_enabled: bool | None = None


def _to_out(org: Organization) -> OrgSettingsOut:
    return OrgSettingsOut(
        name=org.name,
        centre_code=org.centre_code,
        university_name=org.university_name,
        ai_processing_enabled=org.ai_processing_enabled,
    )


async def _get_org(org_id: str, db: AsyncSession) -> Organization:
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        # Should be unreachable — org_id comes from require_org, which reads
        # it off an authenticated session tied to a real Organization row.
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.get("", response_model=OrgSettingsOut)
async def get_settings(org_id: str = Depends(require_org), db: AsyncSession = Depends(get_db)):
    return _to_out(await _get_org(org_id, db))


@router.patch("", response_model=OrgSettingsOut)
async def update_settings(
    req: OrgSettingsUpdate,
    org_id: str = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(org_id, db)
    updates = req.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(org, field, value)
    await db.commit()
    await db.refresh(org)
    return _to_out(org)
