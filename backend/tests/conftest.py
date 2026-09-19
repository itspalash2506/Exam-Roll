import os
import uuid
from dataclasses import dataclass
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.database as database
import app.routers.upload as upload_router
from app.auth import hash_password
from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models.db_models import Organization, User
from app.schemas.schemas import AIInsight, SubjectEntry

# Test users all share this password — it's never asserted against anything
# real, only used to exercise the actual login endpoint (create_session /
# current_user), rather than hand-crafting a session cookie.
_TEST_PASSWORD = "test-password-not-real"


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    """Create a fresh SQLite database file for the test session."""
    db_file = tmp_path_factory.mktemp("data") / "test_examroll.db"
    return str(db_file)


@pytest.fixture(scope="session")
def test_db_url(test_db_path):
    return f"sqlite+aiosqlite:///{test_db_path}"


@pytest.fixture(scope="session")
def test_engine(test_db_url):
    return create_async_engine(
        test_db_url,
        connect_args={"check_same_thread": False},
        echo=False,
        # NullPool (DECISIONS.md, 2026-09-19): a pooled aiosqlite connection
        # is tied to the event loop that created it. The async `client`/
        # `anon_client` fixtures run on pytest-asyncio's loop; the sync
        # `test_client_sync` (Starlette TestClient, needed for WebSocket
        # tests — httpx's ASGITransport has no WS support) runs the app in
        # its OWN background thread with its OWN loop. A test using both
        # (e.g. org_a/org_b fixtures + test_client_sync) could reuse a
        # connection across that loop boundary and fail with "no active
        # connection" — found via test_ws_rejects_job_belonging_to_another_org.
        # NullPool opens a fresh connection per checkout, so no connection
        # is ever reused across a loop boundary in the first place.
        poolclass=NullPool,
    )


@pytest.fixture(scope="session")
def test_session_factory(test_engine):
    return async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db(test_engine, test_session_factory, tmp_path_factory):
    """Initialize test DB schema and isolate upload directory for the session."""
    test_upload_dir = str(tmp_path_factory.mktemp("uploads"))
    settings = get_settings()
    settings.upload_dir = test_upload_dir
    # Force local-disk storage for the whole session regardless of what's in
    # .env — a real .env now carries live R2 credentials (needed to verify
    # the R2 backend against a real bucket), and Settings reads .env
    # unconditionally. Without this reset, every test that exercises
    # /api/v1/upload or /api/v1/export was silently writing to the real
    # production R2 bucket over the network instead of test_upload_dir.
    # Individual tests that want R2 coverage opt back in per-test via the
    # r2_settings/moto_bucket fixtures in test_storage.py, which monkeypatch
    # (and auto-revert) these same four fields (DECISIONS.md, 2026-09-20).
    settings.r2_account_id = ""
    settings.r2_access_key_id = ""
    settings.r2_secret_access_key = ""
    settings.r2_bucket_name = ""

    database.engine = test_engine
    database.AsyncSessionLocal = test_session_factory
    upload_router.AsyncSessionLocal = test_session_factory

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    await test_engine.dispose()


@pytest.fixture(autouse=True)
def override_get_db(test_session_factory):
    """Override get_db FastAPI dependency to use the async test DB."""
    async def _get_test_db():
        async with test_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def mock_classifier():
    """Deterministic AI classifier insight to keep tests fast and offline."""
    default_insight = AIInsight(
        document_type="attestation_sheet",
        course="Master of Business Administration",
        semester="3rd Semester",
        exam_name="End Term Examination 2026",
        total_students=2,
        subjects_detected=[
            SubjectEntry(code="MBAN301", name="Business Mathematics"),
            SubjectEntry(code="MBAN302", name="Accountancy"),
        ],
        confidence=0.95,
        notes="Automated test insight",
        suggested_outputs=["Subject-wise Roll Number List"],
    )
    with patch(
        "app.services.pipeline.processor.classify_document",
        return_value=default_insight,
    ):
        yield


async def _create_org_and_user(
    session_factory, *, org_name: str, email: str
) -> tuple[str, str]:
    """Insert an Organization + User directly (there is no signup endpoint
    by design — see scripts/create_admin.py), returning (org_id, user_id).
    """
    async with session_factory() as session:
        org = Organization(name=org_name)
        session.add(org)
        await session.flush()
        user = User(
            org_id=org.id,
            email=email,
            password_hash=hash_password(_TEST_PASSWORD),
        )
        session.add(user)
        await session.commit()
        return org.id, user.id


@dataclass
class AuthedOrg:
    """A logged-in org+user for tests. `.cookies` is a plain dict suitable
    for httpx's `cookies=` kwarg on ANY client instance — not tied to the
    client that performed the login."""

    org_id: str
    user_id: str
    email: str
    cookies: dict[str, str]


async def _login_new_org(test_session_factory, *, org_name: str) -> AuthedOrg:
    email = f"{uuid.uuid4().hex[:10]}@example.test"
    org_id, user_id = await _create_org_and_user(
        test_session_factory, org_name=org_name, email=email
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/auth/login", json={"email": email, "password": _TEST_PASSWORD}
        )
        assert res.status_code == 200, f"test fixture login failed: {res.text}"
        cookies = dict(ac.cookies)
    return AuthedOrg(org_id=org_id, user_id=user_id, email=email, cookies=cookies)


@pytest_asyncio.fixture
async def client(test_session_factory):
    """AsyncClient fixture against FastAPI app, pre-authenticated as a fresh
    org+user via the REAL /api/v1/auth/login endpoint (DECISIONS.md,
    2026-09-19) — exercises the actual create_session/current_user code
    path rather than a hand-crafted cookie, so every existing test that
    just uploads/lists/exports jobs keeps working unchanged now that auth
    is required, without any test needing to know auth exists.

    Starlette ASGITransport executes BackgroundTasks inline before completing requests.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        email = f"{uuid.uuid4().hex[:10]}@example.test"
        await _create_org_and_user(test_session_factory, org_name="Test Org", email=email)
        login_res = await ac.post(
            "/api/v1/auth/login", json={"email": email, "password": _TEST_PASSWORD}
        )
        assert login_res.status_code == 200, f"test fixture login failed: {login_res.text}"
        yield ac


@pytest.fixture
def test_client_sync():
    """Starlette's sync TestClient, for WebSocket tests only — httpx's
    ASGITransport (used by the async `client`/`anon_client` fixtures above)
    does not support WebSocket connections at all. Runs against the same
    `app` object, so the same dependency_overrides / test DB apply."""
    from starlette.testclient import TestClient

    with TestClient(app, base_url="http://test") as tc:
        yield tc


@pytest_asyncio.fixture
async def anon_client():
    """A plain AsyncClient with no login performed — for tests that pass
    org_a/org_b cookies explicitly on each request instead of relying on an
    automatically-authenticated session (avoids any ambiguity between a
    client's own persistent cookie jar and a per-request cookie override)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def org_a(test_session_factory) -> AuthedOrg:
    """A logged-in org, distinct from org_b, for cross-tenant isolation tests."""
    return await _login_new_org(test_session_factory, org_name="Org A")


@pytest_asyncio.fixture
async def org_b(test_session_factory) -> AuthedOrg:
    """A second logged-in org, distinct from org_a."""
    return await _login_new_org(test_session_factory, org_name="Org B")


@pytest.fixture
def make_pdf_pages():
    """Helper fixture that patches pdf_extractor._extract_page_texts.
    Can be used as a context manager: `with make_pdf_pages(pages): ...`
    or called to set return value: `make_pdf_pages(pages)`
    """
    default_pages = [
        "Roll No: 10001  MBAN301 Business Mathematics  MBAN302 Accountancy",
        "Roll No: 10002  MBAN301 Business Mathematics  MBAN302 Accountancy",
    ]
    patcher = None

    class _Helper:
        def __call__(self, pages=None):
            nonlocal patcher
            p = pages if pages is not None else default_pages
            if patcher is not None:
                patcher.stop()
            patcher = patch(
                "app.services.extractors.pdf_extractor._extract_page_texts",
                return_value=(p, False),
            )
            return patcher.start()

        def __enter__(self):
            return self()

        def __exit__(self, exc_type, exc_val, exc_tb):
            nonlocal patcher
            if patcher is not None:
                patcher.stop()
                patcher = None

    helper = _Helper()
    yield helper
    if patcher is not None:
        patcher.stop()
