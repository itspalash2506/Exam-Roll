import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    SESSION_COOKIE,
    create_session,
    current_user,
    revoke_session,
    verify_password,
)
from app.database import get_db
from app.models.db_models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    org_id: str
    email: str
    role: str


@router.post("/login", response_model=UserOut)
async def login(
    req: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    # Same error, same status, whether the email doesn't exist or the
    # password is wrong — a distinguishable response would let an attacker
    # enumerate registered emails.
    if user is None or not user.is_active or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user.last_login_at = datetime.now(timezone.utc)
    await create_session(user, response, db)  # commits, including last_login_at
    logger.info("Login: %s (org %s)", user.email, user.org_id)
    return UserOut(id=user.id, org_id=user.org_id, email=user.email, role=user.role)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: AsyncSession = Depends(get_db),
):
    if session_token:
        await revoke_session(session_token, db)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return UserOut(id=user.id, org_id=user.org_id, email=user.email, role=user.role)
