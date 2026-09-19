"""Same-origin frontend serving (DECISIONS.md, 2026-09-19).

Two things need checking:
1. Settings.frontend_dist_path returns None (not a crash) when the built
   frontend doesn't exist, so main.py's mount stays a genuine no-op rather
   than raising at import time.
2. When it DOES exist (as it does in this repo from a prior `npm run build`),
   the SPA catch-all serves index.html for unknown client-side routes without
   ever shadowing a real API route.
"""

from pathlib import Path

from app.config import Settings


def test_frontend_dist_path_none_when_missing(tmp_path):
    """A Settings pointed at a directory that doesn't exist must not raise —
    main.py relies on this to decide whether to mount StaticFiles at all."""
    s = Settings(frontend_dist_dir=str(tmp_path / "does-not-exist"))
    assert s.frontend_dist_path is None


def test_frontend_dist_path_resolves_when_present(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html></html>")
    s = Settings(frontend_dist_dir=str(tmp_path))
    assert s.frontend_dist_path == tmp_path


async def test_api_routes_not_shadowed_by_spa_catchall(client):
    """The catch-all is registered last specifically so /api/v1/*, /health and
    /assets/* — all more specific — are matched first. Prove it."""
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res = await client.get("/api/v1/jobs")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


async def test_spa_route_falls_back_to_index_html(client):
    """A React Router client-side route (e.g. /jobs/abc123) must still return
    the SPA shell — this only holds when frontend/dist has been built; if it
    hasn't, the catch-all never registered and this is a plain 404, which is
    also correct (dev/test mode disables same-origin serving entirely)."""
    from app.config import get_settings

    dist = get_settings().frontend_dist_path
    res = await client.get("/jobs/some-fake-id-not-a-real-route")

    if dist is not None:
        assert res.status_code == 200
        assert "<div id=\"root\">" in res.text or "<!doctype html>" in res.text.lower()
    else:
        assert res.status_code == 404
