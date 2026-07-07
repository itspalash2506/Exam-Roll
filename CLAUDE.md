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
| Database    | SQLite (dev) via SQLAlchemy 2.0 ORM              |
| AI          | Groq API (llama-3.1-8b-instant)                 |
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
│   ├── alembic.ini                    Migration config (future)
│   └── app/
│       ├── main.py                    FastAPI app factory, CORS, router registration
│       ├── config.py                  Pydantic BaseSettings (reads .env)
│       ├── database.py                SQLAlchemy engine, session factory
│       ├── websocket_manager.py       WebSocket connection manager (broadcast)
│       ├── models/
│       │   └── db_models.py           ORM models: Job, ExtractedRow
│       ├── schemas/
│       │   └── schemas.py             Pydantic request/response models
│       ├── routers/
│       │   ├── upload.py              POST /api/v1/upload
│       │   ├── jobs.py                GET /api/v1/jobs, GET /api/v1/jobs/{id}
│       │   └── export.py              POST /api/v1/export
│       ├── services/
│       │   ├── ai/
│       │   │   ├── groq_client.py     Groq API wrapper (chat completions)
│       │   │   ├── classifier.py      Detect: attendance / marks / roll-list
│       │   │   └── extractor.py       AI-guided data extraction from raw text
│       │   ├── extractors/
│       │   │   ├── pdf_extractor.py   pdfplumber text + table extraction
│       │   │   └── excel_extractor.py openpyxl sheet reader
│       │   ├── generators/
│       │   │   └── excel_generator.py Styled openpyxl Excel output
│       │   └── pipeline/
│       │       └── processor.py       Orchestrator: extract → classify → generate
│       └── utils/
│           ├── file_utils.py          MIME detection, size validation, safe paths
│           └── subject_utils.py       Subject name normalization, abbreviation map
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

| Method | Route                       | Description                              |
|--------|-----------------------------|------------------------------------------|
| POST   | /api/v1/upload              | Upload ONE OR MORE PDF/Excel files (repeated `files` fields) as one batch job |
| GET    | /api/v1/jobs                | List all jobs (paginated)                |
| GET    | /api/v1/jobs/{job_id}       | Get job status + extracted data          |
| POST   | /api/v1/export              | Generate + download Excel output         |
| WS     | /ws/jobs/{job_id}           | Real-time job progress updates           |
| GET    | /health                     | Health check                             |

---

## Database Schema

### jobs
| Column          | Type     | Notes                                      |
|-----------------|----------|--------------------------------------------|
| id              | UUID     | Primary key                                |
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
| GROQ_MODEL         | Model ID (default: llama-3.1-8b-instant) |
| DATABASE_URL       | SQLAlchemy connection string             |
| UPLOAD_DIR         | Directory for temp uploads               |
| MAX_FILE_SIZE_MB   | Max upload size in MB                    |
| CORS_ORIGINS       | Allowed CORS origins (comma-separated)   |
| APP_ENV            | development / production                 |
| LOG_LEVEL          | INFO / DEBUG / WARNING                   |

Frontend (build-time, Vite):

| Variable           | Description                              |
|--------------------|------------------------------------------|
| VITE_API_BASE_URL  | Deployed backend origin (e.g. https://examroll-api.onrender.com). Unset in local dev → Vite proxy to localhost:8000. WS URL is derived from it in `src/api/client.js`. |

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
- Aggregation (processor.py): per-file extraction → `merge_subject_maps` (later files fill missing names; on a name conflict the longer name wins and a warning is recorded) → `aggregate_students` with `DEDUPE_ACROSS_FILES = True`: **(roll_number, subject_code) is unique across the batch**; duplicate pairs are merged and their real count reported by the new always-emitted `deduplicating` stage ("N duplicate entries merged" / "No duplicates"). A file yielding zero students or failing to read produces a per-file warning and the batch continues; only if ALL files fail does the job fail.
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
- `Settings.ensure_runtime_dirs()` (called in lifespan before `init_db`) creates `UPLOAD_DIR` and the SQLite file's parent dir, so a fresh ephemeral container boots cleanly. Ephemeral-disk caveat (DB/uploads/outputs wiped on restart) is documented in config.py, .env.example, and DEPLOYMENT.md — Phase 2 migrates to Postgres + object storage.
- Deploy artifacts: `render.yaml` (Blueprint, `rootDir: backend`, env vars `sync: false` — values live only in the Render dashboard), `backend/.python-version` (3.14.5, matching the local venv), `frontend/public/_redirects` + `frontend/vercel.json` (SPA fallback), `frontend/.env.example`.
- `.gitignore` fix: `uploads/*` was root-anchored and missed `backend/uploads/`; now `uploads/` (any depth).

### Purely numeric subject codes & PIN filtering (2026-07-07)
- Support for purely numeric codes: Updated `_CODE_RE` and `_PAIR_RE` in `subject_utils.py` and `excel_extractor.py` to match 5-to-6 digit purely numeric subject codes (e.g. `210236`) in addition to alphanumeric codes (e.g. `MBAN301`).
- Address PIN/phone number filtering: Enhanced `extract_all_subjects` in `subject_utils.py` to programmatically ignore matches if they are preceded by `pin`, `phone`, `mobile`, or `tel` in the local 20-character context, preventing address PIN codes from being identified as subject codes.

---

## Future Phases

| Phase | Feature                                              |
|-------|------------------------------------------------------|
| 2     | Auth (JWT), per-college data isolation               |
| 3     | Cloud storage (S3/R2), async Celery workers          |
| 4     | Marks extraction, grade calculation, report cards    |
| 5     | Email delivery, admin dashboard, audit logs          |

---

## Coding Conventions

- **Python**: snake_case files, functions, variables; PascalCase classes
- **React**: PascalCase components; camelCase hooks, utils, variables
- **Folders**: lowercase with hyphens
- **Env vars**: SCREAMING_SNAKE_CASE; all secrets in `.env`, never hardcoded
- **Commits**: conventional commits (`feat:`, `fix:`, `chore:`)
- **API responses**: always `{"data": ..., "error": null}` envelope
- **No magic numbers**: constants go in `config.py` or top of file
