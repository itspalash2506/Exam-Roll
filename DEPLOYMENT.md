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
   | `GROQ_MODEL` | `llama-3.1-8b-instant` |
   | `DATABASE_URL` | `sqlite+aiosqlite:///./examroll.db` |
   | `UPLOAD_DIR` | `./uploads` |
   | `MAX_FILE_SIZE_MB` | `50` |
   | `CORS_ORIGINS` | `http://localhost:5173` for now — you'll append the frontend origin in Step 4 |
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
CORS_ORIGINS=http://localhost:5173,https://examroll.pages.dev
```

(comma-separated, exact origin, no trailing slash, include `https://`). Save —
Render restarts the service. Without this the browser blocks every API call
from the deployed frontend.

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
  Postgres + object storage.
- **Cold starts** after idle (~15 min) take up to a minute.
- **Single instance, no auth** — do not put real student data behind a public
  URL long-term; this is a pilot.

## Local development — unchanged

`VITE_API_BASE_URL` unset → the Vite proxy forwards `/api` and `/ws` to
`http://localhost:8000` exactly as before. Run backend + frontend per README.
