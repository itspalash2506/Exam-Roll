from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in _settings.database_url else {},
    echo=_settings.sql_echo,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


# Schema is managed exclusively by Alembic now (`alembic upgrade head`, run
# out-of-band before the app starts — see alembic/env.py), not at app boot
# (DECISIONS.md, 2026-09-19). This replaces the previous init_db(), which
# ran create_all() plus a hand-rolled _add_missing_nullable_columns() shim
# that could only ever ADD a nullable column — never enforce NOT NULL,
# rename, drop, or add an index (P2-44) — and raced unguarded if more than
# one worker started at once. The upcoming tenancy migration needs a real
# NOT NULL column, which that shim could never have added anyway.
#
# Test schema setup is unaffected: conftest.py's setup_test_db fixture calls
# Base.metadata.create_all directly against its own throwaway test engine
# and has never gone through this module's init_db — removing it changes
# nothing about how the test suite sets up its database.


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
