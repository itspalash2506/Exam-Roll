from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode

_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    # Empty default so the app still boots when the key isn't set yet (e.g. a
    # fresh hosted environment) — the pipeline already degrades gracefully to
    # rule-based extraction, and /health reports "not configured".
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"

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

    # Per-file ceiling. With uploads streamed to disk this no longer drives
    # upload memory, but it still bounds EXTRACTION: one file's bytes plus the
    # parser's working set are resident while that file is processed.
    max_file_size_mb: int = 50
    # Batch ceilings. Files are processed one at a time, so these bound disk
    # and total work rather than peak RAM — but without them a caller can queue
    # an unbounded number of files and exhaust the ephemeral disk instead.
    max_batch_files: int = 10
    max_total_batch_mb: int = 150
    # NoDecode: without it pydantic-settings JSON-decodes list fields itself
    # BEFORE the validator below runs, so a plain comma-separated value
    # (CORS_ORIGINS=http://a,https://b) crashed at boot with a JSONDecodeError.
    # With NoDecode the raw string reaches parse_cors_origins, which accepts
    # both the comma-separated and JSON-array forms.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    # Optional regex for origins that cannot be enumerated ahead of time —
    # chiefly Cloudflare Pages preview deployments, which get a fresh
    # per-build subdomain (https://<hash>.exam-roll.pages.dev) that no fixed
    # list can cover. Empty (the default) disables it: exact-list matching only.
    #
    # SECURITY: allow_credentials is on, so ALWAYS anchor the pattern (^...$)
    # and pin your own project's domain. A loose pattern like
    # r"https://.*\.pages\.dev" would let ANY Cloudflare Pages site — anyone
    # can deploy one — call this API with credentials. Correct form:
    #   CORS_ORIGIN_REGEX=^https://([a-z0-9-]+\.)?exam-roll\.pages\.dev$
    cors_origin_regex: str = ""
    app_env: str = "development"
    log_level: str = "INFO"
    # SQL echo — useful in development for debugging queries; MUST be False in
    # production because it logs every SQL statement, including student PII.
    sql_echo: bool = False

    # Object storage (Cloudflare R2, DECISIONS.md 2026-09-20): uploaded source
    # files and generated Excel outputs live here instead of accumulating on
    # local disk, which is what caused the memory/disk pressure this replaces.
    # All four empty by default — matches this file's existing pattern (e.g.
    # groq_api_key) of graceful degradation rather than a hard requirement:
    # when unset, storage.py falls back to local disk under upload_dir
    # exactly as before, so local dev and the test suite need no R2 account
    # at all. Only a real deployment needs these set.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""

    # Same-origin serving (DECISIONS.md, 2026-09-19): the built frontend
    # (`npm run build` → frontend/dist) is served by this same FastAPI process
    # alongside /api/v1/* and the WebSocket, so the browser sees ONE origin —
    # no cross-site cookie problem, no CSRF token, no CORS allowlist needed in
    # production. Empty (the default) disables it entirely: pytest and
    # `npm run dev` never build the frontend, so main.py checks whether this
    # directory actually exists before mounting anything. Resolves relative to
    # the process CWD like upload_dir/database_url; override with an absolute
    # path if the built assets live elsewhere.
    frontend_dist_dir: str = "../frontend/dist"

    @model_validator(mode="after")
    def never_echo_in_production(self) -> "Settings":
        """Refuse to boot if sql_echo is enabled in production — it would log
        every SQL statement, including student roll numbers and names, to the
        application log stream."""
        if self.sql_echo and self.app_env == "production":
            raise ValueError(
                "sql_echo must not be enabled in production (APP_ENV=production). "
                "SQL echo logs every query, including student PII, to the "
                "application log stream."
            )
        return self

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
    def max_total_batch_bytes(self) -> int:
        return self.max_total_batch_mb * 1024 * 1024

    @property
    def object_storage_enabled(self) -> bool:
        return bool(
            self.r2_account_id and self.r2_access_key_id
            and self.r2_secret_access_key and self.r2_bucket_name
        )

    @property
    def r2_endpoint_url(self) -> str:
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"

    @property
    def frontend_dist_path(self) -> Path | None:
        """Resolved path to the built frontend, or None if it doesn't exist.

        Returning None (rather than a Path that may not exist) lets main.py
        do a single truthy check before mounting anything static."""
        p = Path(self.frontend_dist_dir)
        return p if p.is_dir() else None

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
