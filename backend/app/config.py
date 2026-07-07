from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode

_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    # Empty default so the app still boots when the key isn't set yet (e.g. a
    # fresh hosted environment) — the pipeline already degrades gracefully to
    # rule-based extraction, and /health reports "not configured".
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    # ── Storage (DEPLOYMENT NOTE) ────────────────────────────────────────────
    # Both paths are env-configurable and resolve relative to the process CWD
    # (backend/ in dev; the service root on Render). On free-tier hosts the
    # disk is EPHEMERAL: uploaded files, generated Excel outputs, and this
    # SQLite DB may be wiped on every restart/sleep. That is acceptable for
    # the pilot because outputs are regenerable from re-uploaded sources.
    # Phase 2 migrates to hosted Postgres + object storage. If the service
    # root is ever read-only, point these at a /tmp path via env vars, e.g.
    #   DATABASE_URL=sqlite+aiosqlite:////tmp/examroll/examroll.db
    #   UPLOAD_DIR=/tmp/examroll/uploads
    database_url: str = "sqlite+aiosqlite:///./examroll.db"
    upload_dir: str = "./uploads"

    max_file_size_mb: int = 50
    # NoDecode: without it pydantic-settings JSON-decodes list fields itself
    # BEFORE the validator below runs, so a plain comma-separated value
    # (CORS_ORIGINS=http://a,https://b) crashed at boot with a JSONDecodeError.
    # With NoDecode the raw string reaches parse_cors_origins, which accepts
    # both the comma-separated and JSON-array forms.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    app_env: str = "development"
    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            raw = v.strip()
            if raw.startswith("["):
                import json
                return json.loads(raw)
            return [o.strip() for o in raw.split(",") if o.strip()]
        return v

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def sqlite_file_path(self) -> Path | None:
        """Filesystem path of the SQLite DB, or None for non-SQLite/in-memory URLs."""
        if "sqlite" not in self.database_url:
            return None
        _, _, raw = self.database_url.partition("///")
        if not raw or raw == ":memory:":
            return None
        return Path(raw)

    def ensure_runtime_dirs(self) -> None:
        """Create the upload dir and the SQLite DB's parent dir if missing, so a
        fresh (ephemeral) container boots cleanly with nothing pre-provisioned."""
        Path(self.upload_dir).mkdir(parents=True, exist_ok=True)
        db_path = self.sqlite_file_path
        if db_path is not None and db_path.parent != Path("."):
            db_path.parent.mkdir(parents=True, exist_ok=True)

    model_config = {"env_file": str(_ENV_FILE), "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
