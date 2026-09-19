"""app.main computes docs_url/redoc_url/openapi_url once, at import time, from
APP_ENV (P2-30) — so gating them off in production can't be exercised against
the shared `app` object the rest of the suite imports (it's already
constructed under the test env). Each case here imports app.main fresh in an
isolated subprocess with its own APP_ENV instead.
"""

import os
import subprocess
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent

_CHECK_SCRIPT = (
    "from app.main import app; "
    "print(app.docs_url, app.redoc_url, app.openapi_url)"
)


def _docs_urls_for(app_env: str) -> str:
    env = {**os.environ, "APP_ENV": app_env}
    result = subprocess.run(
        [sys.executable, "-c", _CHECK_SCRIPT],
        cwd=str(_BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"import failed:\n{result.stderr}"
    return result.stdout.strip()


def test_docs_disabled_in_production():
    assert _docs_urls_for("production") == "None None None"


def test_docs_enabled_outside_production():
    assert _docs_urls_for("development") == "/docs /redoc /openapi.json"
