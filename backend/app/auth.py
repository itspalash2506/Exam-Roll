"""Server-side session auth (P0-4, P0-8; DECISIONS.md 2026-09-19).

Sessions, not JWT: an httpOnly cookie needs no token handling in JS at all
(removing the entire XSS-token-exfiltration class), and a server-side
session is instantly revocable — "log out everywhere" and "this account is
compromised" are one UPDATE (AuthSession.revoked_at) away. A stateless JWT
cannot do either without building a revocation list, which is a session
table with extra steps.

Same-origin serving (main.py, DECISIONS.md 2026-09-19) is what makes
`samesite="lax"` actually work here: app and API share one origin, so the
browser sends the cookie on every request and on the WebSocket handshake
with zero CORS/CSRF machinery needed.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, HTTPException, Request, Response, WebSocket, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.db_models import AuthSession, Job, User

logger = logging.getLogger(__name__)

SESSION_COOKIE = "examroll_session"
SESSION_TTL = timedelta(days=7)

# argon2id (the default argon2-cffi profile) — never bcrypt (silently
# truncates at 72 bytes), never a bare/unsalted hash.
_hasher = PasswordHasher()


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, raw)
        return True
    except VerifyMismatchError:
        return False


def _hash_token(raw: str) -> str:
    """SHA-256 of the raw cookie value. Only the hash is ever stored, so a
    DB read alone (a backup, a careless log line, a SQL injection) never
    yields a usable credential."""
    return hashlib.sha256(raw.encode()).hexdigest()


async def create_session(user: User, response: Response, db: AsyncSession) -> None:
    raw = secrets.token_urlsafe(32)
    db.add(AuthSession(
        token_hash=_hash_token(raw),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + SESSION_TTL,
    ))
    await db.commit()
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE, raw,
        httponly=True,      # unreadable from JS — an XSS cannot steal it
        # `Secure` only in production. Real browsers special-case localhost
        # as a "potentially trustworthy origin" and send a Secure cookie
        # over plain http://localhost anyway, which is why this doesn't
        # need to be true for local dev to work through the Vite proxy —
        # but httpx's ASGI test client follows RFC 6265 strictly and will
        # NOT send a Secure cookie back over its http://test base_url, so
        # forcing it on unconditionally silently broke every authenticated
        # test (found the hard way: login succeeded, the very next request
        # came back 401 with no cookie attached at all). Production is
        # always served over HTTPS, so this is never a real weakening.
        secure=settings.app_env == "production",
        samesite="lax",      # blocks cross-site POST/DELETE (CSRF) while
                             # allowing normal navigation; works as designed
                             # here because app+API are the same origin
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
    )


async def revoke_session(session_token: str, db: AsyncSession) -> None:
    result = await db.execute(
        select(AuthSession).where(AuthSession.token_hash == _hash_token(session_token))
    )
    auth_session = result.scalar_one_or_none()
    if auth_session is not None and auth_session.revoked_at is None:
        auth_session.revoked_at = datetime.now(timezone.utc)
        await db.commit()


async def _resolve_user_from_token(session_token: str | None, db: AsyncSession) -> User | None:
    if not session_token:
        return None
    result = await db.execute(
        select(User).join(AuthSession, AuthSession.user_id == User.id).where(
            AuthSession.token_hash == _hash_token(session_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(timezone.utc),
            User.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def current_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = await _resolve_user_from_token(session_token, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Session expired")
    return user


async def require_org(request: Request, user: User = Depends(current_user)) -> str:
    request.state.org_id = user.org_id  # available to a future rate limiter
    return user.org_id


# ── WebSocket auth (P0-8) ────────────────────────────────────────────────────
# CORS does not apply to WebSocket upgrades, so Origin must be checked here
# explicitly — and everything below must run BEFORE `websocket.accept()`, or
# the handshake has already succeeded regardless of what we decide after.

async def authorize_ws(websocket: WebSocket, job_id: str, db: AsyncSession) -> str | None:
    """Returns the org_id allowed to watch `job_id`, or None after closing
    the connection. The caller must not call websocket.accept() until this
    returns non-None.

    Every failure path closes with the SAME code (WS_1008_POLICY_VIOLATION)
    and no distinguishing message — whether the cookie is missing, the
    Origin is disallowed, or the job belongs to a different org. A close
    reason that told the two apart would turn the WebSocket endpoint into a
    job-ID existence oracle for other tenants' data, exactly the mistake
    P0-4's 404-not-403 rule exists to avoid on the HTTP side.
    """
    settings = get_settings()
    origin = websocket.headers.get("origin")
    if origin is not None and not _origin_allowed(origin, settings):
        logger.warning("WebSocket rejected: disallowed Origin %r for job %s", origin, job_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    # A same-origin browser WebSocket always sends Origin; a missing header
    # only happens for a non-browser client, which the cookie check below
    # still gates — so a missing Origin is not itself rejected here.

    session_token = websocket.cookies.get(SESSION_COOKIE)
    user = await _resolve_user_from_token(session_token, db)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    result = await db.execute(select(Job.id).where(Job.id == job_id, Job.org_id == user.org_id))
    if result.scalar_one_or_none() is None:
        # Same close code whether the job is missing entirely or belongs to
        # another org — see the docstring.
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    return user.org_id


def _origin_allowed(origin: str, settings) -> bool:
    if origin in set(settings.cors_origins):
        return True
    if settings.cors_origin_regex:
        import re
        return re.fullmatch(settings.cors_origin_regex, origin) is not None
    return False
