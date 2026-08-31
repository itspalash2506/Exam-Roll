# ExamRoll — Free-Tier Deployment Guide

Frontend → **Cloudflare Pages** (static SPA; Vercel as fallback).
Backend → **Render** free web service (FastAPI + uvicorn).

```
Browser ──HTTPS──► Cloudflare Pages  (static React build)
   │
   ├──HTTPS (axios)──► https://examroll-api.onrender.com  /api/v1/*
   └──WSS  (native)──► wss://examroll-api.onrender.com    /ws/jobs/{id}
```

Everything in-repo is already prepared. The steps below are the **dashboard
actions you must do yourself** — nothing here has been deployed for you.

> Free-tier behaviour changes often. Every assumption below that depends on the
> host is tagged **VERIFY THIS** — confirm it in the current dashboard/docs
> rather than trusting this file.

---

## What is already configured in the repo

| File | Purpose |
|---|---|
| `render.yaml` | Render Blueprint: free Python web service, `rootDir: backend`, health check `/health`, env vars declared as `sync: false` (dashboard prompts for values; nothing committed) |
| `backend/.python-version` | Pins Python **3.14.5** (matches local venv) |
| `frontend/.env.example` | Documents `VITE_API_BASE_URL` (build-time var) |
| `frontend/public/_redirects` | SPA fallback for Cloudflare Pages (`/* → /index.html 200`) |
| `frontend/vercel.json` | Same SPA fallback for Vercel |
| `.env.example` | Backend env vars with production notes (CORS, ephemeral-disk warning) |
| `src/api/client.js` | Single source of truth: reads `VITE_API_BASE_URL`, derives the WebSocket URL from it (http→ws, https→wss); falls back to the Vite dev proxy when unset, so local dev is unchanged |
| `app/config.py` | All paths/origins env-driven; creates `UPLOAD_DIR` + SQLite parent dir on startup so a fresh ephemeral container boots cleanly |

---

## Step 1 — Push to GitHub

The repo is initialised and committed locally. Create an empty GitHub repo
(e.g. `examroll`), then:

```powershell
cd C:\Projects\examroll
git remote add origin https://github.com/<you>/examroll.git
git branch -M main
git push -u origin main
```

Double-check on GitHub that **no `.env`, `venv/`, `node_modules/`, `*.db`, or
`uploads/` content appears** — they are gitignored, but verify once.

---

## Step 2 — Backend on Render

1. Sign in at https://dashboard.render.com (GitHub login is easiest).
2. **New → Blueprint**, select your `examroll` repo. Render reads `render.yaml`
   and proposes the `examroll-api` service.
   *(Alternative: New → Web Service and set manually — Root Directory
   `backend`, Build `pip install -r requirements.txt`, Start
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, Health check `/health`,
   plan Free.)*
3. When prompted for the environment variables (all `sync: false`), enter:

   | Key | Value |
   |---|---|
   | `GROQ_API_KEY` | your real key from https://console.groq.com — **only here, never in git** |
   | `GROQ_MODEL` | `openai/gpt-oss-20b` |
   | `DATABASE_URL` | `sqlite+aiosqlite:///./examroll.db` |
   | `UPLOAD_DIR` | `./uploads` |
   | `MAX_FILE_SIZE_MB` | `50` |
   | `CORS_ORIGINS` | `http://localhost:5173` for now — you'll append the frontend origin in Step 4 |
   | `CORS_ORIGIN_REGEX` | leave empty (optional; see Step 4 for preview deployments) |
   | `APP_ENV` | `production` |
   | `LOG_LEVEL` | `INFO` |

4. Deploy. When it's live, open `https://<your-service>.onrender.com/health` —
   expect `{"status":"ok", ..., "groq":"configured"}`. Note the service URL.

**VERIFY THIS (Render free tier), in the current docs/dashboard:**
- Free services **sleep after ~15 min idle**; the next request cold-starts
  (~30–60 s). The frontend's axios timeout is already 120 s to absorb this.
- The disk is **ephemeral**: the SQLite DB, uploaded files, and generated
  Excel outputs are wiped on every restart/sleep/deploy. Acceptable for this
  pilot (outputs are regenerable; Phase 2 = Postgres + object storage) — but
  confirm this is still how the free tier behaves, and warn users that job
  history will not persist.
- **WebSockets** are supported on free web services — confirm; the progress
  checklist depends on `wss://…/ws/jobs/{id}` connecting.
- Python **3.14.5** (from `backend/.python-version`) is available — if the
  build fails on the Python version, edit that file to the closest supported
  3.13/3.14 patch release (the code needs only 3.11+).

---

## Step 3 — Frontend on Cloudflare Pages

1. Sign in at https://dash.cloudflare.com → **Workers & Pages → Create →
   Pages → Connect to Git**, select the `examroll` repo.
2. Build settings:

   | Setting | Value |
   |---|---|
   | Framework preset | Vite (or None) |
   | Root directory | `frontend` |
   | Build command | `npm run build` |
   | Build output directory | `dist` |

3. **Environment variable (build-time!)** — add under the *production* build
   environment:

   | Key | Value |
   |---|---|
   | `VITE_API_BASE_URL` | `https://<your-service>.onrender.com` (from Step 2, no trailing slash) |

   Vite bakes this in at build time — changing it later requires a **rebuild**,
   not just a redeploy.
4. Deploy, note your URL (e.g. `https://examroll.pages.dev`).
5. Hard-refresh a deep route (e.g. `/history`) — it must load, not 404.

**VERIFY THIS (Cloudflare Pages):**
- SPA fallback: `frontend/public/_redirects` ships `/* /index.html 200`; Pages
  has also historically served SPAs automatically when no `404.html` exists.
  Confirm deep-route refresh works; if Pages complains about the `_redirects`
  rule, delete that file and rely on the automatic SPA mode.
- Free-tier build limits (500 builds/month historically) are enough for a
  pilot — confirm current limits.

### Fallback: Vercel instead
New Project → import repo → **Root Directory `frontend`** → framework Vite →
add the same `VITE_API_BASE_URL` env var → deploy. `frontend/vercel.json`
already provides the SPA rewrite. **VERIFY THIS:** Vercel Hobby is free for
non-commercial use — check the current terms fit a college pilot.

---

## Step 4 — Close the CORS loop

Back in **Render → examroll-api → Environment**, update:

```
CORS_ORIGINS=http://localhost:5173,https://exam-roll.pages.dev
```

(comma-separated, exact origin, no trailing slash, include `https://`). Save —
Render restarts the service. Without this the browser blocks every API call
from the deployed frontend.

**Symptom if you skip it:** the browser reports *"No 'Access-Control-Allow-Origin'
header is present"*. Note the API itself is fine — it returns 200 with
`access-control-allow-credentials: true`; Starlette simply omits the
`access-control-allow-origin` header when the request's origin isn't in the
allowlist. Confirm the fix from a terminal:

```bash
curl -s -D - -o /dev/null -H "Origin: https://exam-roll.pages.dev" \
  "https://examroll-api.onrender.com/api/v1/jobs?skip=0&limit=50"
```

### Preview deployments (optional)

Cloudflare Pages gives every preview build its own subdomain
(`https://<hash>.exam-roll.pages.dev`), which no fixed list can cover. To allow
those too, set the optional companion variable:

```
CORS_ORIGIN_REGEX=^https://([a-z0-9-]+\.)?exam-roll\.pages\.dev$
```

Leave it empty to keep exact-list matching only. **Anchor it and pin your own
domain** — `allow_credentials` is on, so an unanchored pattern such as
`https://.*\.pages\.dev` would let any Cloudflare Pages site (anyone can deploy
one) call this API with credentials.

---

## Step 5 — Smoke test

1. Open the Pages URL → Dashboard loads (first API call may take ~1 min if
   Render was asleep — that's the cold start).
2. Upload a small PDF/XLSX → the stage checklist should stream live
   (this proves the **WebSocket** path works end-to-end).
3. Confirm extraction results, then export → the styled `.xlsx` downloads.
4. `https://<service>.onrender.com/health` → `"groq":"configured"`.
5. Reload after 20+ min idle: expect one slow cold-start request, then normal.

If uploads work but the progress list stays empty: WebSocket issue — check
browser devtools for the `wss://` connection and re-verify Render WS support
and `CORS_ORIGINS`.

---

## Known free-tier caveats (accepted for the pilot)

- **Nothing persists**: SQLite DB, uploads, and generated files vanish on
  restart/sleep. Job history is best-effort. Phase 2 migrates to hosted
  Postgres; object storage follows in Phase 3.
- **Cold starts** after idle (~15 min) take up to a minute.
- **Single instance, no auth** — do not put real student data behind a public
  URL long-term; this is a pilot.

---

## Phase 2 deployment changes

Phase 2 (see `FUTURE.md` §9 Gate 0 and `PROGRESS.md`) changes this topology in two ways. Both are
prerequisites for the work, not follow-ups, and both have lead time — start them early.

### 1. A custom domain is required for authentication

**This is not cosmetic.** Phase 2 auth uses an httpOnly session cookie with `SameSite=Lax`, which the
browser only sends when the app and the API share a registrable domain. The current pair does not:
`exam-roll.pages.dev` and `examroll-api.onrender.com` are separate registrable domains (`pages.dev`
and `onrender.com` are both on the Public Suffix List), so they are **cross-site**. Deployed that way,
every authenticated request returns 401 and every WebSocket handshake is rejected — silently, because
the browser exposes almost nothing about a failed handshake.

| Setting | Value |
|---|---|
| Frontend | `https://examroll.com` (apex, on Cloudflare Pages) |
| Backend | `https://api.examroll.com` (CNAME to the backend host) |
| `CORS_ORIGINS` | `https://examroll.com` |
| `VITE_API_BASE_URL` | `https://api.examroll.com` |

Different origins, but the *same site* — so `SameSite=Lax` works as designed, with full CSRF
protection and no CSRF token to manage. If a custom domain is genuinely unavailable, the fallback is
`SameSite=None` plus an explicit double-submit CSRF token; see `FUTURE.md` §7.1.

### 2. Managed Postgres replaces SQLite

Phase 2's tenancy migration adds a `NOT NULL org_id` column, which SQLite cannot add without a full
table rebuild — so the storage move happens **before** auth rather than after it.

- Provision Postgres on a free tier (Neon or Supabase).
- Set `DATABASE_URL=postgresql+asyncpg://...` — already env-driven, so no code change beyond the
  driver dependency.
- Schema is created by `alembic upgrade head`, not by `create_all` + the boot-time `ALTER TABLE`,
  which Phase 2 deletes.

This also makes the backend **stateless**: with durable state in Postgres and source files deleted
after extraction, the local disk becomes scratch space. The persistent-volume question below stops
being architectural, and Render vs. Northflank becomes a reversible choice.

### 3. Pick one deployment path

`render.yaml` (`runtime: python`, `pip install -r requirements.txt`) and `backend/Dockerfile` are
two divergent definitions of the same service, and they disagree: the Dockerfile sets
`DATABASE_URL` and `APP_ENV=production` as image ENV, while `render.yaml` requires them to be typed
by hand with `sync: false` — so a Render deploy that skips `APP_ENV` silently runs in development
mode. Before Phase 2 ships, delete one or make them explicitly consistent.

## Alternative backend host — Northflank (Docker)

`backend/Dockerfile` builds the API as a container, so it runs on any Docker
host. Northflank is the motivating target because it offers a **persistent
volume**, which removes the biggest limitation of the Render free tier: the
SQLite DB, uploads, and generated Excel files no longer vanish on restart.

**Build context is `backend/`, not the repo root** — `backend/.dockerignore`
then keeps the venv, local `*.db`, `uploads/`, and `.env` out of the image.

```bash
docker build -t examroll-api backend/
docker run --rm -p 8000:8000 -v examroll-data:/data   -e GROQ_API_KEY=... -e CORS_ORIGINS=https://exam-roll.pages.dev   examroll-api
```

### Northflank service settings

| Setting | Value |
|---|---|
| Type | Service → build from Git repo (Dockerfile) |
| Dockerfile path | `backend/Dockerfile` |
| Build context | `backend` |
| Port | `8000`, HTTP, public |
| Volume | mount at **`/data`** |

The image defaults `DATABASE_URL` and `UPLOAD_DIR` into `/data`, so attaching
the volume is all that's needed for persistence — but **if no volume is mounted
at `/data` the app still starts and silently loses data on restart**, exactly
like Render. Verify the mount before treating history as durable.

Environment variables to set in the dashboard — same list as Step 2, minus the
ones the image already defaults (`DATABASE_URL`, `UPLOAD_DIR`, `APP_ENV`,
`LOG_LEVEL`):

| Key | Value |
|---|---|
| `GROQ_API_KEY` | your key — dashboard only, never in the image |
| `GROQ_MODEL` | `openai/gpt-oss-20b` |
| `CORS_ORIGINS` | must include the frontend origin, e.g. `https://exam-roll.pages.dev` |
| `MAX_FILE_SIZE_MB` | `50` |

`PORT` is honoured if the platform injects it, defaulting to 8000 otherwise, so
the same image runs unchanged on Northflank, Render, Fly, or locally.

Finally, repoint the frontend: set `VITE_API_BASE_URL` to the Northflank URL in
Cloudflare Pages and **trigger a rebuild** (Vite inlines it at build time), then
add that same origin to `CORS_ORIGINS`.

**VERIFY THIS:** Northflank's free-tier resource limits, whether persistent
volumes are included on it, and WebSocket support — the progress checklist
needs `wss://…/ws/jobs/{id}`.

---

## Local development — unchanged

`VITE_API_BASE_URL` unset → the Vite proxy forwards `/api` and `/ws` to
`http://localhost:8000` exactly as before. Run backend + frontend per README.
