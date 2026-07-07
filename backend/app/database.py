from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in _settings.database_url else {},
    echo=_settings.app_env == "development",
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


async def init_db() -> None:
    from app.models import db_models  # noqa: F401 — registers all ORM models
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all only creates missing *tables* — it never adds columns to an
        # existing table. Auto-add any nullable model columns missing from an
        # existing SQLite DB (e.g. jobs.source_files / file_count added for
        # multi-file batches) so old examroll.db files keep working without a
        # manual migration step.
        await conn.run_sync(_add_missing_nullable_columns)


def _add_missing_nullable_columns(conn) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(conn)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing or not column.nullable:
                continue  # only safe, nullable additions — never touch NOT NULL
            col_type = column.type.compile(conn.dialect)
            conn.execute(
                text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}')
            )


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
