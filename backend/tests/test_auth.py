"""Session auth (P0-4, P0-8; DECISIONS.md 2026-09-19).

Login success/failure, session expiry, revocation, and WebSocket
authorization — the mechanism cross-tenant isolation (test_tenancy.py)
depends on being correct in the first place.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.auth import SESSION_COOKIE, hash_password
from app.models.db_models import AuthSession, Organization, User


async def _make_user(test_session_factory, *, email: str, password: str) -> str:
    async with test_session_factory() as session:
        org = Organization(name="Auth Test Org")
        session.add(org)
        await session.flush()
        user = User(org_id=org.id, email=email, password_hash=hash_password(password))
        session.add(user)
        await session.commit()
        return user.id


async def test_login_success_sets_cookie(anon_client, test_session_factory):
    await _make_user(test_session_factory, email="alice@example.test", password="correct-horse")
    res = await anon_client.post(
        "/api/v1/auth/login", json={"email": "alice@example.test", "password": "correct-horse"}
    )
    assert res.status_code == 200
    assert res.json()["email"] == "alice@example.test"
    assert SESSION_COOKIE in res.cookies


async def test_login_wrong_password_rejected(anon_client, test_session_factory):
    await _make_user(test_session_factory, email="bob@example.test", password="right-password")
    res = await anon_client.post(
        "/api/v1/auth/login", json={"email": "bob@example.test", "password": "wrong-password"}
    )
    assert res.status_code == 401


async def test_login_unknown_email_same_error_as_wrong_password(anon_client):
    """A distinguishable response for 'no such user' vs 'wrong password'
    would let an attacker enumerate which emails are registered."""
    res = await anon_client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.test", "password": "anything"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid email or password"


async def test_login_inactive_user_rejected(anon_client, test_session_factory):
    async with test_session_factory() as session:
        org = Organization(name="Inactive Org")
        session.add(org)
        await session.flush()
        user = User(
            org_id=org.id,
            email="inactive@example.test",
            password_hash=hash_password("whatever"),
            is_active=False,
        )
        session.add(user)
        await session.commit()

    res = await anon_client.post(
        "/api/v1/auth/login", json={"email": "inactive@example.test", "password": "whatever"}
    )
    assert res.status_code == 401


async def test_me_requires_a_valid_session(anon_client, test_session_factory):
    res = await anon_client.get("/api/v1/auth/me")
    assert res.status_code == 401

    await _make_user(test_session_factory, email="carol@example.test", password="s3cret!!")
    login_res = await anon_client.post(
        "/api/v1/auth/login", json={"email": "carol@example.test", "password": "s3cret!!"}
    )
    me_res = await anon_client.get("/api/v1/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "carol@example.test"


async def test_logout_revokes_the_session(anon_client, test_session_factory):
    await _make_user(test_session_factory, email="dave@example.test", password="p4ssword")
    await anon_client.post(
        "/api/v1/auth/login", json={"email": "dave@example.test", "password": "p4ssword"}
    )
    assert (await anon_client.get("/api/v1/auth/me")).status_code == 200

    logout_res = await anon_client.post("/api/v1/auth/logout")
    assert logout_res.status_code == 204

    # The cookie is still attached (client jars don't auto-clear on
    # delete_cookie from the test client's perspective within one process),
    # but the session it names is now revoked server-side.
    me_res = await anon_client.get("/api/v1/auth/me")
    assert me_res.status_code == 401


async def test_expired_session_is_rejected(anon_client, test_session_factory):
    email, password = "erin@example.test", "expired-pw"
    user_id = await _make_user(test_session_factory, email=email, password=password)

    async with test_session_factory() as session:
        import hashlib
        import secrets

        raw = secrets.token_urlsafe(32)
        session.add(AuthSession(
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            user_id=user_id,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),  # already expired
        ))
        await session.commit()

    anon_client.cookies.set(SESSION_COOKIE, raw)
    res = await anon_client.get("/api/v1/auth/me")
    assert res.status_code == 401


async def test_revoked_session_is_rejected(anon_client, test_session_factory):
    email, password = "frank@example.test", "revoked-pw"
    await _make_user(test_session_factory, email=email, password=password)
    await anon_client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert (await anon_client.get("/api/v1/auth/me")).status_code == 200

    # Revoke every session for this user directly (simulating "log out
    # everywhere" / "this account is compromised").
    async with test_session_factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        result = await session.execute(select(AuthSession).where(AuthSession.user_id == user.id))
        for auth_session in result.scalars().all():
            auth_session.revoked_at = datetime.now(timezone.utc)
        await session.commit()

    res = await anon_client.get("/api/v1/auth/me")
    assert res.status_code == 401


# ── WebSocket auth (P0-8) ────────────────────────────────────────────────────

def test_ws_connects_with_a_valid_session_and_owned_job(test_client_sync, org_a, make_pdf_pages):
    with make_pdf_pages():
        files = [("files", ("ws_test.pdf", b"%PDF-1.4 content", "application/pdf"))]
        res = test_client_sync.post("/api/v1/upload", files=files, cookies=org_a.cookies)
        assert res.status_code == 200
        job_id = res.json()["job_id"]

    with test_client_sync.websocket_connect(
        f"/ws/jobs/{job_id}", cookies=org_a.cookies
    ) as ws:
        # A successful handshake is the assertion — accept() only runs after
        # authorize_ws returns non-None.
        ws.close()


def test_ws_rejects_missing_cookie(test_client_sync):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with test_client_sync.websocket_connect("/ws/jobs/some-job-id"):
            pass
    assert exc_info.value.code == 1008


def test_ws_rejects_job_belonging_to_another_org(
    test_client_sync, org_a, org_b, make_pdf_pages
):
    from starlette.websockets import WebSocketDisconnect

    with make_pdf_pages():
        files = [("files", ("ws_cross_org.pdf", b"%PDF-1.4 content", "application/pdf"))]
        res = test_client_sync.post("/api/v1/upload", files=files, cookies=org_a.cookies)
        job_id = res.json()["job_id"]

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with test_client_sync.websocket_connect(f"/ws/jobs/{job_id}", cookies=org_b.cookies):
            pass
    # Same close code as "job missing entirely" — never a distinguishing
    # reason, or the handshake becomes a job-ID existence oracle.
    assert exc_info.value.code == 1008


def test_ws_rejects_disallowed_origin(test_client_sync, org_a):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with test_client_sync.websocket_connect(
            "/ws/jobs/some-job-id",
            cookies=org_a.cookies,
            headers={"origin": "https://evil.example.com"},
        ):
            pass
    assert exc_info.value.code == 1008
