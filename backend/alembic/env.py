from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Import every ORM model so Base.metadata is fully populated before
# autogenerate (or the baseline migration) compares against it — a model
# module that's never imported never registers its table.
from app.config import get_settings
from app.database import Base
import app.models.db_models  # noqa: F401 — import for side effect (table registration)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_database_url() -> str:
    """Derive a SYNC SQLAlchemy URL from the app's own async DATABASE_URL.

    Alembic's migration runner is fundamentally synchronous — it cannot
    drive an async engine directly. The app itself always uses an async
    driver (aiosqlite locally, asyncpg in production), so this is the one
    place the driver name is swapped for its sync counterpart. The DB
    location and every other part of the URL come from Settings, never
    hardcoded here (DECISIONS.md, 2026-09-19) — alembic.ini deliberately
    leaves sqlalchemy.url unset.
    """
    url = get_settings().database_url
    if url.startswith("sqlite+aiosqlite:"):
        return "sqlite:" + url[len("sqlite+aiosqlite:"):]
    if url.startswith("postgresql+asyncpg:"):
        rest = url[len("postgresql+asyncpg:"):]
        # asyncpg and psycopg2 use DIFFERENT query-param names for the same
        # thing — asyncpg wants `ssl=require`, psycopg2 (the standard libpq
        # convention, and what Neon's own connection string uses) wants
        # `sslmode=require`. Swapping only the driver prefix and leaving the
        # query string untouched fails outright against a real TLS-required
        # host: psycopg2 raises "invalid dsn: invalid connection option
        # 'ssl'" the moment Alembic tries to connect (found live against
        # Neon, DECISIONS.md 2026-09-19).
        rest = rest.replace("ssl=require", "sslmode=require")
        return "postgresql+psycopg2:" + rest
    # Already a sync URL (or a dialect this project doesn't use yet) — pass
    # through unchanged rather than guessing at a transformation.
    return url


_SYNC_URL = _sync_database_url()
# render_as_batch=True (DECISIONS.md, 2026-09-19): SQLite can't ALTER a
# column in place (add NOT NULL, drop a column, etc.) — Alembic emulates
# this via create-copy-swap, but only when told to. Postgres does these
# operations natively and ignores the flag, so it's safe to leave on always
# rather than branch on dialect.
_RENDER_AS_BATCH = _SYNC_URL.startswith("sqlite:")

config.set_main_option("sqlalchemy.url", _SYNC_URL)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=_SYNC_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_RENDER_AS_BATCH,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_RENDER_AS_BATCH,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
