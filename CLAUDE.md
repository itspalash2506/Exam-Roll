# ExamRoll — Project Bible

## Description

ExamRoll is a production-ready web application for college exam departments to:
1. Upload attestation sheets (PDF or Excel)
2. Auto-detect document structure using Groq AI
3. Extract student roll numbers and subject assignments
4. Generate styled subject-wise roll number Excel sheets for download

---

## Tech Stack

| Layer       | Technology                                      |
|-------------|--------------------------------------------------|
| Frontend    | React 18, Vite, Tailwind CSS, React Router v6   |
| Design      | "Warm editorial" system — Fraunces + Bricolage Grotesque (self-hosted variable fonts via `@fontsource-variable`), framer-motion — see `DESIGN.md` |
| Backend     | FastAPI 0.115, Python 3.11+, Uvicorn             |
| Database    | SQLite (dev) / Postgres (production, `asyncpg`) via SQLAlchemy 2.0 ORM, Alembic migrations |
| AI          | Groq API (openai/gpt-oss-20b)                   |
| PDF         | pdfplumber, pypdf                                |
| Excel I/O   | openpyxl                                         |
| Real-time   | WebSocket (native FastAPI)                       |
| HTTP Client | Axios + TanStack Query                           |

---

## Folder Structure

```
examroll/
├── CLAUDE.md                          Project bible (this file)
├── PROGRESS.md                        Phase tracker
├── .env                               Runtime secrets (never commit)
├── .env.example                       Safe reference copy
├── .gitignore
│
├── backend/
│   ├── requirements.txt               Python dependencies
│   ├── alembic.ini                    Alembic config (DB URL from Settings, not hardcoded)
│   ├── alembic/
│   │   ├── env.py                     Derives sync DB URL from Settings; SQLite batch mode
│   │   └── versions/                  0000_baseline, 0001_add_tenancy, 0002_exam_model
│   ├── scripts/
│   │   └── create_admin.py            One-shot: create the first user for an org
│   └── app/
│       ├── main.py                    FastAPI app factory, CORS, router registration, same-origin frontend serving
│       ├── config.py                  Pydantic BaseSettings (reads .env)
│       ├── database.py                SQLAlchemy engine, session factory (schema via Alembic only)
│       ├── auth.py                    Session auth: create_session, current_user, require_org, authorize_ws
│       ├── websocket_manager.py       WebSocket connection manager (broadcast)
│       ├── middleware/
│       │   └── body_size_limit.py     Pure ASGI middleware, outermost — rejects oversized bodies pre-parse
│       ├── models/
│       │   └── db_models.py           ORM models: Organization, User, AuthSession, Job, College, Course, Exam, SubjectOffering, Student, Enrollment, ExtractedData, OutputFile
│       ├── schemas/
│       │   └── schemas.py             Pydantic request/response models
│       ├── routers/
│       │   ├── auth.py                POST /api/v1/auth/login, /logout, GET /me
│       │   ├── exams.py, colleges.py  Minimal org-scoped CRUD backing the §14.3 upload picker
│       │   ├── upload.py              POST /api/v1/upload
│       │   ├── jobs.py                GET /api/v1/jobs, GET /api/v1/jobs/{id}
│       │   └── export.py              POST /api/v1/export
│       ├── services/
│       │   ├── ai/
│       │   │   ├── groq_client.py     Groq API wrapper (chat completions)
│       │   │   ├── classifier.py      Detect: attendance / marks / roll-list
│       │   │   ├── extractor.py       AI-guided data extraction from raw text
│       │   │   └── validation.py      Validates every AI-returned field (P0-10)
│       │   ├── extractors/
│       │   │   ├── pdf_extractor.py   pdfplumber text + table extraction
│       │   │   └── excel_extractor.py openpyxl sheet reader
│       │   ├── generators/
│       │   │   ├── excel_generator.py Styled openpyxl Excel output
│       │   │   └── workbook_builder.py Shared formula-injection guard (_safe()) + styling helpers (P0-5)
│       │   └── pipeline/
│       │       └── processor.py       Orchestrator: extract → classify → generate → persisting_rows
│       └── utils/
│           ├── file_utils.py          MIME detection, size validation, safe paths
│           ├── subject_utils.py       Subject name normalization, abbreviation map
│           └── roll_sort.py           roll_sort_key() — flat, storable natural-sort key
│
├── frontend/
│   ├── index.html
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── package.json
│   └── src/
│       ├── main.jsx                   React entry point
│       ├── App.jsx                    Router + QueryClient + Toast provider
│       ├── index.css                  Tailwind directives + theme.css import
│       ├── styles/theme.css           Design tokens: color, type, shadow, motion (see DESIGN.md)
│       ├── lib/motion.js              framer-motion tokens + reusable variant builders
│       ├── api/client.js              Axios instance + all API call functions
│       ├── context/JobContext.jsx     Global job list state (Context + Provider)
│       ├── hooks/
│       │   ├── useUpload.js           File upload with progress tracking
│       │   ├── useJobStatus.js        WebSocket-based job status polling
│       │   └── useExport.js           Trigger export + download blob
│       ├── pages/
│       │   ├── Dashboard.jsx          Home page + recent jobs summary
│       │   ├── Upload.jsx             Multi-step upload workflow
│       │   ├── JobDetail.jsx          Job result viewer + export panel
│       │   └── History.jsx            Paginated job history table
│       ├── components/
│       │   ├── layout/
│       │   │   ├── Navbar.jsx
│       │   │   ├── Sidebar.jsx
│       │   │   └── PageWrapper.jsx
│       │   ├── upload/
│       │   │   ├── DropZone.jsx       react-dropzone wrapper (multi-file, appends across drops)
│       │   │   ├── FileList.jsx       Queued files list: remove / add more / clear all / upload
│       │   │   └── AIInsightCard.jsx  AI doc type + confidence + batch chip + per-file warnings
│       │   ├── preview/
│       │   │   ├── SubjectTable.jsx   Extracted data table by subject
│       │   │   ├── StudentSummary.jsx Roll count per subject
│       │   │   └── ConfirmExtraction.jsx Confirm before generating output
│       │   ├── customize/
│       │   │   ├── StylePanel.jsx     Header color, font size pickers
│       │   │   └── OutputTypeSelector.jsx Single-sheet vs per-subject sheets
│       │   └── common/
│       │       ├── ProgressBar.jsx
│       │       ├── Toast.jsx
│       │       ├── Modal.jsx
│       │       ├── Button.jsx
│       │       ├── Badge.jsx
│       │       └── LoadingSkeleton.jsx
│       └── utils/
│           ├── formatters.js          Date formatting, number display
│           └── validators.js          File type + size validation (client-side)
│
└── uploads/                           Temp files — gitignored
```

---

## API Endpoints

All routes below except `/health` and `/api/v1/auth/*` require a valid session cookie
(`require_org` router-level dependency) and are scoped to the caller's own `org_id` — see
"Auth and tenancy" below.

| Method | Route                       | Description                              |
|--------|-----------------------------|------------------------------------------|
| POST   | /api/v1/auth/login          | Log in; sets the session cookie          |
| POST   | /api/v1/auth/logout         | Revoke the current session               |
| GET    | /api/v1/auth/me             | Current user (used to detect an existing session on app load) |
| GET    | /api/v1/exams               | List this org's exams                    |
| POST   | /api/v1/exams               | Create an exam (§14.3 picker's inline-create) |
| GET    | /api/v1/colleges            | List this org's colleges                 |
| POST   | /api/v1/colleges            | Create a college (§14.3 picker's inline-create) |
| POST   | /api/v1/upload               | Upload ONE OR MORE PDF/Excel files (repeated `files` fields) as one batch job; optional `exam_id`/`college_id` form fields |
| GET    | /api/v1/jobs                | List this org's jobs (paginated)         |
| GET    | /api/v1/jobs/{job_id}       | Get job status + extracted data          |
| DELETE | /api/v1/jobs/{job_id}       | Delete a job and its files               |
| POST   | /api/v1/export              | Generate + download Excel output         |
| GET    | /api/v1/export/{job_id}/download/{file_id} | Re-download a previously generated output |
| WS     | /ws/jobs/{job_id}           | Real-time job progress updates (session cookie + Origin check) |
| GET    | /health                     | Health check                             |

### Auth and tenancy

Server-side sessions (`app/auth.py`), not JWT — revocable without a revocation-list. `httponly`,
`samesite=lax` cookie (`secure` only in production — see `DECISIONS.md`), argon2id password hashing.
Every query filters by `org_id`; a cross-org request returns 404, never 403. No signup UI — the first
user in an org is created by `backend/scripts/create_admin.py`. Full design in `DECISIONS.md` and
`FUTURE_UNIFIED.md` §7.

---

## Database Schema

Schema is now managed exclusively by Alembic (`backend/alembic/versions/`), not this section —
`db_models.py` is the source of truth for exact columns/types/constraints; treat the tables below as
an orientation summary, not the authoritative reference.

### jobs
| Column          | Type     | Notes                                      |
|-----------------|----------|--------------------------------------------|
| id              | UUID     | Primary key                                |
| org_id          | UUID     | FK → organizations.id, NOT NULL, indexed — the tenancy boundary |
| created_by      | UUID     | FK → users.id, nullable                    |
| exam_id         | UUID     | FK → exams.id, nullable (§14.3 picker)     |
| college_id      | UUID     | FK → colleges.id, nullable (§14.3 picker)  |
| filename        | VARCHAR  | Summary name (single filename, or "N files (first, …)" for a batch) |
| file_path       | VARCHAR  | uploads/{job_id}/ directory holding all source files + outputs |
| source_files    | TEXT     | JSON array of original uploaded filenames  |
| file_count      | INTEGER  | Files in the batch (nullable; NULL ⇒ 1)    |
| processing_warnings | TEXT | JSON array of per-file warnings            |
| ai_notes        | TEXT     | AI classifier notes (+ mixed-doc-type warning) |
| status          | ENUM     | pending / processing / done / failed       |
| doc_type        | VARCHAR  | attendance / marks / roll_list / unknown   |
| ai_confidence   | FLOAT    | AI classification confidence 0–1           |
| error_message   | TEXT     | Set on failure                             |
| created_at      | DATETIME |                                            |
| updated_at      | DATETIME |                                            |

### Tenancy and exam model tables (2026-09-19)

`organizations`, `users`, `auth_sessions` (migration `0001_add_tenancy`) and `colleges`, `courses`,
`exams`, `subject_offerings`, `students`, `enrollments` (migration `0002_exam_model`) — see
`db_models.py` for exact columns. Identity rules worth remembering: a paper's identity is
`(org, exam, exam_code)`, never its name (names repeat across schemes/years); a student's identity is
`(org, roll_number)`. Every table here carries `org_id NOT NULL` from its first migration.

### extracted_rows
| Column     | Type    | Notes                                  |
|------------|---------|----------------------------------------|
| id         | INTEGER | Primary key                            |
| job_id     | UUID    | FK → jobs.id                           |
| roll_no    | VARCHAR | Student roll number                    |
| subject    | VARCHAR | Normalized subject name                |
| raw_row    | JSON    | Original parsed row dict               |

---

## Environment Variables

| Variable           | Description                              |
|--------------------|------------------------------------------|
| GROQ_API_KEY       | Groq API key (required)                  |
| GROQ_MODEL         | Model ID (default: openai/gpt-oss-20b)   |
| DATABASE_URL       | SQLAlchemy connection string — `sqlite+aiosqlite:///...` in dev, `postgresql+asyncpg://...` in production. `alembic/env.py` derives its own sync URL from this same value; schema is applied via `alembic upgrade head`, not at app boot. |
| UPLOAD_DIR         | Directory for temp uploads               |
| MAX_FILE_SIZE_MB   | Max upload size in MB                    |
| CORS_ORIGINS       | Allowed CORS origins (comma-separated). With same-origin serving in production this is mostly a local-dev concern (Vite on `localhost:5173`); also checked by `authorize_ws`'s `Origin` validation. |
| CORS_ORIGIN_REGEX  | Optional anchored regex for preview origins |
| APP_ENV            | development / production — also gates the session cookie's `Secure` flag (see `DECISIONS.md`) |
| LOG_LEVEL          | INFO / DEBUG / WARNING                   |
| SQL_ECHO           | false (default) — MUST be false in production; app refuses to start if true+production (PII leak prevention) |
| FRONTEND_DIST_DIR  | Path to the built frontend for same-origin serving (default `../frontend/dist`, relative to `backend/`). If missing, static serving is skipped — `pytest`/`npm run dev` are unaffected. |

Frontend (build-time, Vite):

| Variable           | Description                              |
|--------------------|------------------------------------------|
| VITE_API_BASE_URL  | Deployed backend origin (e.g. https://examroll-api.onrender.com). Unset in local dev → Vite proxy to localhost:8000. WS URL is derived from it in `src/api/client.js`. |
| VITE_PILOT_NOTICE  | Pilot banner text shown on the Dashboard (e.g. "Pilot instance — SRIT Exam Centre"). Empty/unset = hidden. |

---

## How to Run (Windows)

```powershell
# Backend
cd C:\Projects\examroll\backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (new terminal)
cd C:\Projects\examroll\frontend
npm install
npm run dev
```

Access:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

---

## Architecture Overview

```
[User Upload]
     │
     ▼
POST /api/v1/upload
     │
     ▼
[file_utils.py] → validate type + size → save to uploads/
     │
     ▼
[processor.py] orchestrator (async background task)
     │
     ├─► [pdf_extractor.py / excel_extractor.py] → raw text + tables
     │
     ├─► [classifier.py + groq_client.py] → doc_type + confidence
     │
     ├─► [extractor.py + groq_client.py] → structured rows [{roll_no, subject}]
     │
     ├─► save to DB (jobs + extracted_rows)
     │
     └─► WebSocket broadcast → frontend progress bar
          │
          ▼
POST /api/v1/export → [excel_generator.py] → .xlsx blob → download
```

---

## Phase 1 Scope — ✅ COMPLETE (2026-06-22)

**Included:**
- File upload (PDF + Excel)
- AI classification via Groq
- Roll number + subject extraction
- Subject-wise Excel generation
- Real-time progress via WebSocket
- Job history with SQLite
- 18 pytest tests for extractors and generator
- Full README.md + this CLAUDE.md

**Not included (Phase 1):**
- User authentication
- Multi-tenant / college separation
- Cloud storage (S3)
- Email delivery of results
- Marks / grades extraction
- Mobile app

---

## Architectural Decisions (recorded during development)

### Database
- **Async SQLAlchemy + aiosqlite** chosen over sync SQLite so FastAPI background tasks can await DB writes without blocking the event loop.
- `DATABASE_URL` uses the `sqlite+aiosqlite:///` scheme; the path is resolved relative to `backend/` (where uvicorn runs).
- Three ORM models: `Job` (main record), `ExtractedData` (students + subjects JSON blobs, 1-to-1 with Job), `OutputFile` (0-to-many generated Excel files per Job).

### API response shape
- Routers return plain Pydantic models (not wrapped in `{data: ..., error: ...}`), matching what the frontend receives directly via `res.data` (Axios unwraps the JSON body automatically).
- Status values: `"queued"` / `"processing"` / `"completed"` / `"failed"`.

### AI pipeline
- Groq calls run via `asyncio.to_thread()` so the async event loop is never blocked.
- **Groq failure → graceful fallback**: if `classify_document()` raises, the processor logs a warning and continues with `document_type="unknown"`, `confidence=0.0`, and the rule-based subjects. If `extract_students_ai()` raises, the rule-based student list (possibly empty) is used as-is.
- `complete_json()` in `groq_client.py` returns `{}` on JSON parse failure (never raises), so the classifier always returns a valid `AIInsight`.

### WebSocket
- Two WS endpoints exist: `/ws/jobs/{job_id}` (registered directly on `app` in `main.py`, used by the frontend) and `/api/v1/ws/{job_id}` (on the upload router, kept for internal use). The frontend always connects to the former via the Vite proxy.
- Both endpoints handle `WebSocketDisconnect` and general `Exception` so a crashing client or network drop never takes down the server.

### File handling
- Uploaded files are saved immediately before the background task starts, so the bytes are on disk even if the background task outlives the request. Batch files live under `uploads/{job_id}/NN_originalname`; `Job.file_path` stores that directory (job deletion rmtree's it).
- `file_size > max_mb` returns HTTP 400 (not 413) for API consistency.
- `.xls` (legacy Excel) is explicitly rejected with a clear message; only `.pdf` and `.xlsx` are accepted.

### Multi-file batches & output sorting (2026-07-06)
- `POST /api/v1/upload` accepts `files: list[UploadFile]` — a single file is just the n=1 case. Every file is validated independently up front; one invalid file rejects the whole request with HTTP 400 naming that file. Mixed PDF+XLSX batches are allowed (`Job.file_type` becomes `"mixed"`).
- New nullable `Job` columns: `source_files` (JSON array of original filenames), `file_count`, `processing_warnings` (JSON array), `ai_notes`. `init_db()` auto-ALTERs missing nullable columns into an existing SQLite DB on startup (create_all never adds columns to existing tables), so old `examroll.db` files need no manual migration.
- Aggregation (processor.py): per-file extraction → `merge_subject_maps` (later files fill missing names; on a name conflict **neither** name is chosen — the code is left unnamed and a `SubjectConflict` is recorded for the review step, per `FUTURE_UNIFIED.md` §14.4) → `aggregate_students` with `DEDUPE_ACROSS_FILES = True`: **(roll_number, subject_code) is unique across the batch**; duplicate pairs are merged and their real count reported by the new always-emitted `deduplicating` stage ("N duplicate entries merged" / "No duplicates"). A file yielding zero students or failing to read produces a per-file warning and the batch continues; only if ALL files fail does the job fail.
- The AI classifier runs ONCE on a combined sample slicing every file; if two files share zero subject codes, a "may be different document types" warning goes into `ai_notes` (and `processing_warnings`) instead of failing.
- Output sorting: `sort_roll_numbers()` in subject_utils sorts each subject's roll list ascending — by integer when every roll is all-digits, else by natural/alphanumeric key. Applied in `build_subject_roll_map` (which the Excel generator now delegates to), i.e. **at export time only** — `students_json` in the DB keeps raw extraction order for traceability. This replaced the generator's old lexicographic `.sort()`, which mis-ordered variable-width numeric rolls ("100" before "23").

### Frontend state
- TanStack Query is the primary server-state manager; JobContext wraps it to expose `jobs`, `currentJob`, and `refreshJobs` without prop-drilling.
- `useJobStatus` maintains a WebSocket connection and reconnects up to 3 times; it marks `doneRef = true` on completion/failure to stop reconnects.
- `useExport` now exposes `exportError` state so the Upload page can render an inline error banner with a Retry button alongside the toast.

### Testing
- Tests are self-contained: Excel fixtures built with openpyxl in-memory; PDF extractor tested by patching `_extract_page_texts` to return known text strings (avoids PDF font-encoding issues in CI).
- No additional test dependencies beyond `pytest` and `pytest-asyncio` (both added to `requirements.txt`).

### Design system
- "Warm editorial" visual system — full rationale, palette, type scale, spacing/radius/shadow tokens, and motion tokens documented in `DESIGN.md` at the project root; do not hardcode hex colors or px shadows in components, use the Tailwind theme tokens (`bg-canvas`, `text-ink`, `border-line`, `shadow-warm`, etc.) defined in `tailwind.config.js` / `src/styles/theme.css`.
- Fonts (Fraunces, Bricolage Grotesque) are self-hosted via `@fontsource-variable/*` npm packages so the app works fully offline — never add a Google Fonts `<link>` back to `index.html`.
- `framer-motion` powers page transitions (`PageWrapper` via `useOutlet()` + `AnimatePresence`), staggered list/card entrance, count-up stat numbers, and button press feedback; all shared variant builders live in `src/lib/motion.js` and accept a `reduced` flag from `useReducedMotion()` so every animation degrades to opacity-only under `prefers-reduced-motion: reduce`.

### Free-tier deployment prep (2026-07-08)
- Target: frontend on Cloudflare Pages (Vercel fallback), backend on Render free tier — full dashboard walkthrough in `DEPLOYMENT.md`.
- `src/api/client.js` is the single source of truth for the backend location: `VITE_API_BASE_URL` (build-time) prefixes the axios base URL and the WebSocket URL is derived from it (http→ws / https→wss); unset ⇒ relative paths through the Vite dev proxy, so local dev is unchanged. Axios timeout raised 60s→120s to survive Render cold starts.
- `GROQ_API_KEY` now defaults to `""` so the app boots without it (pipeline already degrades to rule-based; `/health` reports "not configured").
- `Settings.ensure_runtime_dirs()` (called in lifespan before `init_db`) creates `UPLOAD_DIR` and the SQLite file's parent dir, so a fresh ephemeral container boots cleanly. Ephemeral-disk caveat (DB/uploads/outputs wiped on restart) is documented in config.py, .env.example, and DEPLOYMENT.md — **Phase 2 migrates to managed Postgres; object storage follows in Phase 3.** Once Postgres holds durable state and source files are deleted after extraction, local disk is scratch space and an ephemeral disk stops being a data-loss risk.
- Deploy artifacts: `render.yaml` (Blueprint, `rootDir: backend`, env vars `sync: false` — values live only in the Render dashboard), `backend/.python-version` (3.14.5, matching the local venv), `frontend/public/_redirects` + `frontend/vercel.json` (SPA fallback), `frontend/.env.example`.
- `.gitignore` fix: `uploads/*` was root-anchored and missed `backend/uploads/`; now `uploads/` (any depth).

### Extraction rewrite — P0-1, P0-2, WS-G (2026-09-19)
- **`pdf_extractor` scans per LINE, not per page.** `re.search()` returned the first roll on a page and stopped, so any layout with more than one student per page silently kept one and discarded the rest. `_scan_page_rolls` uses `finditer` per line; codes on a student's own line win, a line with none inherits the page's codes (the one-student-per-page attestation shape), and a bare-column fallback handles rolls printed with no label. Attestation sheets carry both a Roll No and an Enrollment No per student, so the two labelled forms are tried **in precedence order per page** — without that the real sheet yields exactly double.
- **Roll numbers and subject codes are now distinguishable.** `_ALPHA_CODE_RE` is always accepted; a purely numeric code needs positive evidence — a `CODE - Name` pair or an explicit subject/paper/course label. `extract_all_subjects(text, exclude=rolls)` takes the document's roll numbers as an exclusion set. `_is_subject_code` in `excel_extractor` no longer accepts bare `\d{5,6}`, so a session header like `202401` cannot become a column.
- **A labelled status is read from the value, not the label** — the sheets print `Regular/Backlog : ATKT`, and a bare keyword scan matches the "Regular" in the label.
- **Per-student fields** (`name`, `status`, `admission_year`, `status_explicit`) and **per-paper fields** (`exam_code`, `paper_no`, `group_label`) are captured at extraction time, because adding them later means re-uploading every sheet. `aggregate_students` carries them through the dedupe rather than rebuilding a bare record.
- **Nothing defaults silently.** A defaulted status, an unrecognised status, a subject-name conflict, and a document yielding <=1 student across many pages all produce warnings on the Job. Silence is what let P0-1 ship.
- Real-PDF regression is pinned at **167 students / 15 subjects**; `tests/golden/` holds page-text + expected-JSON fixtures. `*.pdf` is gitignored — real attestation sheets are student PII.

### Same-origin serving, Postgres/Alembic, session auth, exam model (2026-09-19)
- **Same-origin serving lands before auth, deliberately.** `main.py` mounts the built `frontend/dist`
  (when it exists — guarded, so `pytest`/`npm run dev` are unaffected) alongside `/api/v1/*` and the
  WebSocket, with a catch-all SPA route registered last so it can never shadow a more specific one.
  This makes app and API the literal same origin, which is what lets the session cookie's
  `samesite="lax"` work with zero CSRF machinery — chosen over a custom domain or `SameSite=None`;
  full reasoning in `DECISIONS.md`.
- **Alembic replaces the boot-time schema hacks entirely.** `_add_missing_nullable_columns()` and
  `init_db()`'s `create_all()` are deleted from `database.py`; schema is now applied exclusively by
  `alembic upgrade head`, run out-of-band before the app starts. `alembic/env.py` derives its DB URL
  from the app's own `Settings` (never hardcoded) and runs in SQLite batch mode
  (`render_as_batch=True`) so `ALTER` operations SQLite can't do in place still apply via
  create-copy-swap — Postgres ignores the flag and uses its native `ALTER` either way. Three
  migrations so far: `0000_baseline` (captures the pre-existing schema), `0001_add_tenancy`
  (`organizations`/`users`/`auth_sessions` + `Job.org_id`/`created_by`), `0002_exam_model`
  (`colleges`/`courses`/`exams`/`subject_offerings`/`students`/`enrollments` +
  `Job.exam_id`/`college_id`). CI's `alembic-postgres` job verifies every migration's
  upgrade/downgrade/upgrade round-trip against a real `postgres:16` container on every push — not
  just SQLite, which is what local dev and the test suite still use.
- **Auth is server-side sessions, argon2id, `httponly + samesite=lax` cookie** (`app/auth.py`) — see
  the `Future Phases` section above for why sessions over JWT. `require_org` is a router-level
  dependency on `jobs`/`export`/`upload`, so a route added later is protected by default. Every query
  filters by `org_id` in the `WHERE` clause and returns **404, never 403**, on a cross-org hit — a 403
  would confirm the row exists and turn the endpoint into an existence oracle for other tenants' data.
  `authorize_ws` applies the same rule to the WebSocket (plus an `Origin` check, since CORS doesn't
  cover WebSocket upgrades), validated **before** `accept()` is ever called. The frontend has a
  matching `AuthContext`/`RequireAuth`/`Login` and a 401 interceptor that redirects to `/login`.
  `backend/scripts/create_admin.py` is the only way to create a user — no signup UI, by design.
- **The exam data model is the relational bridge extraction always needed but never had.**
  Extraction has only ever written JSON blobs (`ExtractedData.students_json`/`subjects_json`); the
  new `persisting_rows` pipeline stage (after `saving`) upserts real `Student`/`SubjectOffering`/
  `Enrollment` rows once an exam is selected at upload — a safe no-op otherwise, since most uploads
  still predate the picker. `SubjectOffering` is `UNIQUE(org, exam, exam_code)` — identity of a paper
  is the exam code, never the name, which repeats across schemes and years. A cross-job name conflict
  on the same `exam_code` is recorded, never silently overwritten (the cross-job counterpart to the
  within-batch rule the extraction rewrite above already enforces). `roll_sort_key()`
  (`utils/roll_sort.py`) is a flat, storable natural-sort key computed once at insert, distinct from
  `subject_utils._natural_sort_key`'s in-process tuple sorter.
- **A real bug found while wiring the exam model's matching-stage helper, not by design review:**
  `processor.py`'s matching stage let the AI add a brand-new subject code to the merged map — not
  just relabel one rule-based extraction already found — the same failure class as P0-1 (a silent
  default that discards what actually happened). Fixed by extracting the logic into a pure,
  unit-tested `apply_ai_subject_labels()`; full writeup in `DECISIONS.md`.
- Suite grew from 115 to **135 passing, 0 failing**; `npm run build` succeeds. Verified end-to-end in
  a real browser, not just automated tests (see `DECISIONS.md` and `PROGRESS.md`'s P05 notes for the
  session-cookie/test-infrastructure gotchas found and fixed along the way).
- **Landed on branch `p05-foundation-auth-postgres`, not yet merged to `main`** — `main` remains the
  deployed v1, untouched, at the user's explicit request until this branch is tested and the merge is
  a deliberate separate decision.

### Purely numeric subject codes & PIN filtering (2026-07-07)
- Support for purely numeric codes: Updated `_CODE_RE` and `_PAIR_RE` in `subject_utils.py` and `excel_extractor.py` to match 5-to-6 digit purely numeric subject codes (e.g. `210236`) in addition to alphanumeric codes (e.g. `MBAN301`).
- Address PIN/phone number filtering: Enhanced `extract_all_subjects` in `subject_utils.py` to programmatically ignore matches if they are preceded by `pin`, `phone`, `mobile`, or `tel` in the local 20-character context, preventing address PIN codes from being identified as subject codes.

---

## Future Phases

| Phase | Feature                                                                                  |
|-------|------------------------------------------------------------------------------------------|
| **2** | **Production Foundation** — test suite, Alembic, managed Postgres, extraction correctness, **session** auth + per-org data isolation, rate limiting, output sanitisation, privacy/retention. *No new features.* |
| 3     | Object storage (S3/R2), durable queue replacing `BackgroundTasks`, PDF letterhead output, .docx output, print layout |
| 4     | College branding upload, hall ticket generation, seating arrangement generation           |
| 5     | Marks extraction, grade calculation, report cards, email delivery, admin dashboard, audit logs |

**Phase 2 is `FUTURE.md` §9 Gate 0** — the 10 launch blockers found in the 2026-08-31 production
audit. The task breakdown lives in `PROGRESS.md`; the finding-to-workstream map is `FUTURE.md` §11.

**Status as of 2026-09-19** (branch `p05-foundation-auth-postgres`, not yet merged to `main` — see
`DECISIONS.md` and `PROGRESS.md`'s WS notes for full detail): extraction correctness, output
sanitisation, Alembic + Postgres, session auth, and per-org tenant isolation are done. Still open
before Phase 2 can close: rate limiting (P0-9), `/docs` still public in production (P2-30), no real
`/health` DB check (P2-32), no security headers (P1-25), and all of privacy/retention/DPDP (§8) —
**do not start Phase 3 work until those close.**

Two corrections to earlier plans, both recorded in `FUTURE.md`, one since amended again in
`DECISIONS.md`:

- **Auth is server-side sessions, not JWT.** Sessions are revocable ("log out everywhere", "this
  account is compromised"); a stateless JWT needs a revocation list, which is a session table with
  extra steps. Design in `FUTURE.md` §7.
- **The custom-domain requirement was reversed in `DECISIONS.md` (2026-09-19).** `FUTURE.md` §7
  originally required app and API to share a registrable domain (`examroll.com` +
  `api.examroll.com`), because on the old `pages.dev` + `onrender.com` pair they were cross-site and
  the browser sent no session cookie at all, on XHR or on the WebSocket handshake. **Built instead:**
  FastAPI serves the built frontend itself (`main.py`, same-origin serving) — app and API become the
  literal same origin, deleting the problem rather than routing around it with DNS, at zero cost and
  no lead time. The auth code (`app/auth.py`) is identical either way; a custom domain remains a
  valid upgrade path later, changing only deployment configuration.
- **Postgres moved into Phase 2**, ahead of auth. The tenancy migration adds a `NOT NULL org_id`, and
  SQLite cannot alter a column to NOT NULL without a full table rebuild — doing it twice is waste.
  Object storage stays in Phase 3. Driver support and every migration are verified against a real
  Postgres container in CI; a managed Postgres project (Supabase/Neon) is not yet provisioned.

---

## Coding Conventions

- **Python**: snake_case files, functions, variables; PascalCase classes
- **React**: PascalCase components; camelCase hooks, utils, variables
- **Folders**: lowercase with hyphens
- **Env vars**: SCREAMING_SNAKE_CASE; all secrets in `.env`, never hardcoded
- **Commits**: conventional commits (`feat:`, `fix:`, `chore:`)
- **API responses**: always `{"data": ..., "error": null}` envelope
- **No magic numbers**: constants go in `config.py` or top of file
