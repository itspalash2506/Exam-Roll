import os
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.database as database
import app.routers.upload as upload_router
from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.schemas.schemas import AIInsight, SubjectEntry


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


@pytest_asyncio.fixture
async def client():
    """AsyncClient fixture against FastAPI app.
    Starlette ASGITransport executes BackgroundTasks inline before completing requests.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


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
                return_value=p,
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
