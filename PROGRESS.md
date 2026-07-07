# ExamRoll — Progress Tracker

**Project:** ExamRoll
**Current Phase:** Phase 1
**Overall Status:** 🟢 Phase 1 Complete

---

## Phase 1 Tasks

- [x] PROMPT 1: Project scaffold + CLAUDE.md + PROGRESS.md — 2026-06-21
- [x] PROMPT 2: Database models + config + schemas — 2026-06-21
- [x] PROMPT 3: Groq AI service (classifier + extractor) — 2026-06-21
- [x] PROMPT 4: PDF + Excel extraction pipeline — 2026-06-21
- [x] PROMPT 5: Excel generation service — 2026-06-21
- [x] PROMPT 6: FastAPI routes + WebSocket progress — 2026-06-21
- [x] PROMPT 7: React Vite frontend — 2026-06-21
- [x] PROMPT 8: End-to-end testing + README — 2026-06-22
- [x] Phase 1 polish: Honest granular progress system — 2026-07-02
- [x] Phase 1 polish: Editorial visual redesign (Fraunces + Bricolage, warm palette, framer-motion) — 2026-07-02
- [x] Phase 1 polish: Multi-file aggregation + sorted subject-wise output — 2026-07-06
  - Dedupe rule: (roll_number, subject_code) is unique across the batch — repeats merged, count reported honestly in a new "Merging duplicates" stage (`DEDUPE_ACROSS_FILES` flag in processor.py). Sort rule: each subject column sorts ascending at export time only (numeric when all-digits, natural/alphanumeric otherwise); stored extraction order untouched.
- [x] Phase 1 polish: Purely numeric subject code support & PIN filtering — 2026-07-07
- [x] Deployment prep: free-tier hosting config (Cloudflare Pages + Render) — 2026-07-08
  - Env-driven API/WS base (`VITE_API_BASE_URL`, single helper in client.js), CORS docs, boot-safe missing Groq key, startup dir creation for ephemeral disks, `render.yaml` + `.python-version` + SPA `_redirects`/`vercel.json`, git repo initialised. Dashboard walkthrough in `DEPLOYMENT.md`.
  - Enabled support for 5-to-6 digit purely numeric subject codes (e.g. `210236`) while filtering out address PIN codes (e.g. `482001`) and phone numbers using programmatic context checks.

---

✅ **Phase 1 COMPLETE** — 2026-06-22

---

## What Works

- **File upload** — one or MANY PDF/XLSX files per job (up to 50 MB each) with per-file type + size validation; an invalid file rejects the batch with a message naming it
- **Multi-file aggregation** — all files in a batch are extracted, students merged, subject maps unified (later files fill missing names; longer name wins on conflict, with a warning), and (roll, subject) pairs de-duplicated; per-file warnings ("File 2 (x.xlsx): no roll numbers found") surface in the AI Insight card
- **Sorted output** — every subject column in the generated Excel is ascending (numeric sort for all-digit rolls, natural sort otherwise); DB keeps raw extraction order for traceability
- **AI classification** — Groq Llama 3.1 identifies document type, course, semester, exam name, and all subject codes; gracefully falls back to rule-based results if Groq is unavailable
- **PDF extraction** — pdfplumber per-page roll-number extraction; pypdf fallback for scanned PDFs; handles RDVV attestation sheet format (one student per page)
- **Excel extraction** — Auto-detects matrix format (subject codes as header columns) and flat-list format (comma/space-separated codes in one column)
- **Subject detection** — Regex-based subject code detection (`MBAN301`, `CS401`, etc.) and purely numeric subject codes (e.g. `210236`), with programmatic context filtering to ignore address PIN codes and phone numbers.
- **Excel generation** — Styled two-sheet output: "Subject-wise Roll Number List" (merged title, two-line subject headers, alternating row colours, COUNTA totals, freeze panes) + "Summary" (metadata + per-subject enrollment table)
- **Customizable styling** — Header colour, font, font size, column width configurable before download
- **Honest granular progress** — WebSocket streams 9 discrete stage events (validating → reading_document → extracting_rolls → detecting_subjects → deduplicating → ai_analysis → matching → validating_data → saving), each carrying real detail/count pulled from the actual documents (e.g. "File 2 of 3 · 158 pages" live per file, "10 students across 3 files", "3 duplicate entries merged" — or "No duplicates"); frontend `StageProgress` renders a live checklist with a thin overall percent bar
- **AI Insight card** — Displays document type, confidence score, detected subjects, and metadata after processing
- **Job history** — SQLite-backed paginated list of all jobs with status badges, delete (cascades to files on disk), and re-download
- **Health check** — `/health` endpoint reports Groq config and DB status
- **404 page** — Friendly not-found page for unknown routes
- **Page titles** — Each page updates `document.title` (Dashboard / Upload / History / Job Detail / 404)
- **Smooth transitions** — Fade-in animation on every page navigation
- **33 passing tests** — PDF extractor, Excel extractor (both formats), subject detection, Excel generator, roll-number sorting (numeric + natural), multi-file merge/dedupe, numeric subject code parsing. (`tests/test_ai.py` and `tests/test_generators.py` are stale Prompt-1 scaffold stubs testing APIs that no longer exist — 4 failures that pre-date this work; run `pytest tests/test_extractors.py tests/test_multifile_and_sorting.py` for the real suite)

## Known Limitations

- **One student per page** — PDF extraction expects the RDVV attestation format where each page belongs to one student; multi-student-per-page PDFs may only yield the first student per page
- **ASCII-only roll numbers** — The roll-number regex (`\d{4,12}` or `[A-Z0-9]{5,15}`) may miss alphanumeric roll formats from other universities
- **No authentication** — All data is visible to anyone with access to the running server
- **SQLite only** — Not suitable for concurrent multi-user production use
- **Local storage only** — Uploaded files and Excel outputs live in `uploads/` on disk; no cloud backup
- **Groq dependency** — Without a valid API key the document is classified as "unknown" and no AI subject enrichment runs (rule-based extraction still works)
- **Single-sheet output only** — The "per-subject sheets" output type shown in the UI is listed as coming soon
- **Numeric code collision** — 5-to-6 digit numeric subject codes could conflict with 5-to-6 digit student roll numbers if the roll numbers are parsed as subject codes.

## Next: Phase 2

- User login + JWT authentication
- Per-college role-based access control
- PostgreSQL migration (replace SQLite)
- PDF output with college letterhead
- Word document (.docx) output
- Print layout / print-to-PDF in browser
- College branding / logo upload
- Hall ticket generation
- Seating arrangement generation

---

**Last Updated:** 2026-07-08 (Free-tier deployment prep — see DEPLOYMENT.md)

## Notes

**Purely numeric subject code support & PIN filtering (2026-07-07):**
- Updated `_CODE_RE` and `_PAIR_RE` in `subject_utils.py` and `excel_extractor.py` to match 5-to-6 digit purely numeric subject codes (e.g. `210236`) in addition to standard alphanumeric codes.
- Enhanced `extract_all_subjects` in `subject_utils.py` with context checking: if a numeric code is found, the system scans the preceding 20 characters for keywords like `pin`, `phone`, `mobile`, or `tel` to filter out PIN codes (like `482001`) and phone numbers.
- Added `test_subject_detection_numeric_codes` in `test_extractors.py` verifying correct extraction of purely numeric codes and filtering of PIN code variants. All 33 unit tests pass.

**Multi-file aggregation + sorted subject-wise output (2026-07-06):**
- `POST /api/v1/upload` now takes `files: list[UploadFile]` (repeated `files` multipart fields). Every file is validated up front; one bad file → HTTP 400 naming it. One Job per batch: sources saved under `uploads/{job_id}/` (`NN_originalname`), `Job.file_path` points at that directory (delete_job now rmtree's directories), `Job.filename` holds a summary ("3 files (a.xlsx, …)"), and new nullable columns `source_files` (JSON array), `file_count`, `processing_warnings` (JSON array), `ai_notes` store the batch metadata. `init_db` gained a generic auto-migration that ALTERs missing nullable columns into an existing SQLite DB — no manual step for old examroll.db files.
- `processor.process(job_id, files, db, ws)` runs each file through its extractor (mixed PDF+XLSX batches fine), then aggregates: subject maps merged via `merge_subject_maps` (later files fill names, longer name wins on conflict + warning), students via `aggregate_students` with `DEDUPE_ACROSS_FILES = True` — (roll, subject) unique, duplicate-pair count reported by the new always-emitted `deduplicating` stage ("N duplicate entries merged" / "No duplicates"). Per-file honest details stream during reading ("File 2 of 3 · 158 pages" — StageProgress now shows detail on *active* rows too). Unreadable file → warning + continue; ALL unreadable → job failed with aggregate message. Zero-roll file in a batch → warning, not abort. Classifier runs ONCE on a combined sample slicing every file; disjoint subject-code sets between files → "may be different document types" warning appended to `ai_notes` (which is now actually persisted + returned). All warnings land in `Job.processing_warnings` and render in a warm box on the AI Insight card ("N things to know").
- `sort_roll_numbers` in subject_utils: all-digits → sort by int; else natural sort (digit/non-digit chunk key, digit chunks always align at odd tuple positions so int-vs-str comparison can't happen). Applied inside `build_subject_roll_map`; the Excel generator's `_build_roll_map` now delegates to it — this also FIXED a real pre-existing bug: the generator previously `.sort()`ed lexicographically, so variable-width numeric rolls ordered wrong ("100" before "23"). Sorting is export-time only; `students_json` keeps raw order.
- Frontend: DropZone is multi-file and appends across drops (compact once files are queued); new `FileList.jsx` (staggered rows, per-file remove, "Add more files", "Clear all", "N files · X MB total", "Upload & Analyze N files" button — replaces FilePreview.jsx, deleted); `uploadFiles(files)` in client.js with `uploadFile` kept as the n=1 wrapper; duplicate filenames rejected with a toast (fired outside the setState updater — StrictMode double-invokes updaters, found via Playwright when the toast showed twice).
- Verified: 32 unit tests pass; live API run (35/35 checks): single xlsx → columns numerically ascending, counts/metadata otherwise unchanged; 2 xlsx + 1 pdf batch → 10 raw students across 3 files merged to 7 unique, 3 duplicate pairs merged (WS stage history replay confirmed real numbers), all columns sorted, Summary counts match deduped data; invalid batch member → 400 naming file; zero-roll member → warning + batch completes. Playwright UI run (11/11): append/dedupe/remove in FileList, dedupe stage row, aggregated chips on Insight + Review.


**Editorial visual redesign (2026-07-02):**
- Replaced the generic Inter/blue-gradient look with a "warm editorial" design system: Fraunces (variable, self-hosted via `@fontsource-variable/fraunces`) for headings/stat numbers/wordmark, Bricolage Grotesque (variable, self-hosted) for body/UI text — both work fully offline, no Google Fonts network dependency
- New warm palette: canvas `#FAF8F4`, surface `#FFFFFF`, warm border `#EDE8E0`, ink `#1F1B16`, muted `#6B6257`, primary teal-green `#1F5D4C`/`#2E8168` hover, terracotta accent `#C4623F`, soft ochre highlight `#F0E3C4` — defined once in `frontend/src/styles/theme.css` and mirrored into `frontend/tailwind.config.js`
- Added `framer-motion`; motion tokens + reusable variant builders (`pageTransition`, `staggerContainer`/`staggerItem`, `cardHover`, `buttonTap`, `useCountUp`) live in `frontend/src/lib/motion.js`; every builder respects `prefers-reduced-motion` by dropping transforms and keeping opacity-only fades, and a global CSS rule in `theme.css` covers plain CSS transitions too
- Re-skinned every component/page with zero logic changes: Navbar (serifed "ER" monogram, not a graduation-cap icon), Button/Badge/Modal/ProgressBar (new `emphasis` button variant = ink-on-ochre), StageProgress + Upload stepper (teal complete / terracotta active ring, animated fill), DropZone (warm dashed→solid teal border, animated icon), AIInsightCard ("reading" layout with Fraunces subhead, italic pull-quote AI notes), StudentSummary/Dashboard stat cards (count-up Fraunces numbers), SubjectTable (ochre-tinted header band + count row), History/Dashboard empty states ("Nothing here yet" in Fraunces), 404 (large Fraunces numeral)
- New `frontend/DESIGN.md`-equivalent at project root (`DESIGN.md`) documents the full token set and rationale
- Verified `npm run build` and `npm run dev` both succeed; manually reviewed every route in the browser

**Honest granular progress system (2026-07-02):**
- Replaced the six-step percentage progress bar with 8 discrete stage events (`validating`, `reading_document`, `extracting_rolls`, `detecting_subjects`, `ai_analysis`, `matching`, `validating_data`, `saving`), each emitted `active` then `complete` with a real `detail`/`count` computed from the actual document — no fabricated sub-steps, no invented numbers. An overall `percent` (stages-complete / 8) rides along on every event for a thin top bar.
- `pdf_extractor.py` / `excel_extractor.py` — added `extract_from_pdf_with_stats` / `extract_from_excel_with_stats` alongside the existing 3-tuple functions (kept untouched for test/back-compat) so the processor can report the real page count / data-row count without re-parsing the file or changing extraction logic.
- `processor.py` — `_run` now emits stage events via an `_emit` closure instead of six coarse `_send` calls; on any exception the `process()` wrapper emits `{"type":"error","stage_id":<last active stage>,"message":<real error>}`. Rule-based extraction and AI classification/labeling logic are unchanged — this was a reporting refactor only.
- `websocket_manager.py` — added `send_stage(job_id, payload)` (kept `send_progress` as-is, unused by the new pipeline). **Found and fixed a real race**: background processing starts the instant the upload HTTP response returns, which can outrun the frontend opening its WebSocket — so `ConnectionManager` now buffers each job's stage history and replays it on `connect()`, otherwise fast-firing early stages (e.g. "validating") were silently lost for anyone who connected a beat late. History is cleared when the last socket for a job disconnects.
- `useJobStatus.js` — now collects an ordered `stages` array (one entry per `stage_id`, updated in place) and a `stageError` object, while still deriving the legacy `status`/`progress`/`message` fields so `JobDetail.jsx` needed no changes.
- `StageProgress.jsx` (new) — vertical checklist (pending/active/complete/warning/error rows) with a cosmetic-only stagger: real events that land in the same tick reveal ~180ms apart so a human can read them, explicitly commented as never fabricating a stage/status/number. Settles with a green flourish, then auto-advances Upload.jsx to Step 3 after ~600ms. **Found and fixed a second real bug** during testing: the settle effect's own `setSettled(true)` retriggered the same effect (via the `settled` dependency), and React's cleanup-before-rerun cancelled the just-scheduled `onComplete` timeout before it could fire — split into two effects (detect-settle, then schedule-callback via a ref) to fix.
- Verified end-to-end with a real 167-page attestation PDF via a scripted Playwright run (no `chromium-cli` available in this environment, so Playwright + Chromium were installed ad hoc): every stage showed real data — "PDF · 2.6 MB", "168 pages", "167 students", "15 subjects", "Attestation sheet · 90% confidence", "9 subjects labelled", a real "Unknown subject codes: BB2361, BB5486" warning, "167 record(s) saved" — and Step 3 (AI Insight) correctly displayed the same 167 students / 90% confidence / 15 subjects afterward.

**PROMPT 8 notes:**
- Backend: fixed file-size status code 413 → 400; added `skip`/`limit` query params to `GET /jobs`; wrapped Groq calls in try/except so AI failure produces best-effort rule-based result; added exception handlers to WebSocket endpoints; hardened export router with explicit try/except around Excel generation and disk write
- Frontend: added `NotFound.jsx` 404 page (with Home + Upload links); replaced `<Navigate to="/">` catch-all with `<NotFound />`; added `document.title` updates in all four pages; added `animate-fade-in` Tailwind keyframe + applied per-page in PageWrapper; added `exportError` state to `useExport` hook; added inline error+retry block in Upload step 5
- Tests: rewrote `backend/tests/test_extractors.py` from placeholder stubs to 18 real pytest tests covering PDF extractor (3), Excel extractor (4), subject detection (4), and Excel generator (7); all 18 pass
- Docs: wrote full `README.md` at project root with setup instructions, API table, project structure, and roadmap; wrote conftest-less test setup using only deps already in requirements.txt

**PROMPT 7 notes:**
- Complete React 18 + Vite + Tailwind CSS frontend with design language: primary #1F4E79, accent #2E86C1, background #F8FAFC, Inter font
- `src/api/client.js` — axios instance at `/api/v1`; exports `uploadFile`, `getJobs`, `getJob`, `deleteJob`, `exportExcel` (triggers browser download), `createWebSocket` (connects to `/ws/jobs/{jobId}` via vite proxy)
- `src/context/JobContext.jsx` — TanStack Query-powered context providing `jobs`, `currentJob`, `setCurrentJob`, `refreshJobs`, `isLoading`
- `src/hooks/useJobStatus.js` — WebSocket hook with up to 3 auto-reconnect retries; auto-closes on "completed"/"failed"; returns `{progress, message, status, aiInsight}`
- Layout: `Navbar` (sticky, 64px, GraduationCap logo, New Upload + History), `Sidebar` (240px, active state highlighted in #1F4E79), `PageWrapper` (flex layout with sidebar offset)
- Common: `Button` (4 variants, 3 sizes, loading spinner), `Badge` (status-aware colors), `Modal` (ESC-to-close), `ProgressBar` (color by status, pulse while processing), `Toast`, `LoadingSkeleton`
- Upload: `DropZone` (280px min-height, file type icon changes, selected state), `FilePreview` (upload button + progress), `AIInsightCard` (confidence meter, subjects list, AI notes, suggested output chips, proceed/edit buttons)
- Preview: `StudentSummary` (4 stat cards with icons), `SubjectTable` (sticky roll-no column, subject columns, count row in gold, show-all toggle at 10 rows), `ConfirmExtraction`
- Customize: `StylePanel` (collapsible, 4 color pickers, font selector, size+width sliders, live preview strip), `OutputTypeSelector` (subject-wise selected, 3 coming-soon cards)
- Pages: `Dashboard` (quick upload card, recent 5 jobs, stats bar), `Upload` (5-step workflow with step indicator), `JobDetail` (progress → summary → table → style panel → export with re-download), `History` (table with delete confirmation modal, pagination)
- Backend data shape: responses are NOT wrapped in `{data: ...}` envelope; status values are "queued"/"processing"/"completed"/"failed"; job detail has `extracted_data.students` (StudentRecord with `roll_number`, `subjects: [codes]`) and `extracted_data.subjects` ([{code, name}])
- Vite proxy: `/api` → `http://localhost:8000`, `/ws` → `ws://localhost:8000` (WebSocket)
- Build: `vite build` succeeds with no errors; dev server starts at `http://localhost:5173`

**PROMPT 2 notes:**
- Switched to async SQLAlchemy with `aiosqlite` driver; added `aiosqlite>=0.20.0` to requirements.txt
- `DATABASE_URL` in `.env` / `.env.example` updated to `sqlite+aiosqlite:///./examroll.db`
- `CORS_ORIGINS` in `.env` uses JSON array format: `["http://localhost:5173"]`
- `config.py` uses absolute path to resolve `.env` from project root (so it works when running from `backend/`)
- DB models: `Job`, `ExtractedData`, `OutputFile` — new schema; old `ExtractedRow` scaffold removed
- Schemas include backward-compat `ApiResponse`, `JobOut`, `JobListOut` so scaffold routers still import cleanly until Prompt 6 replaces them

**PROMPT 6 notes:**
- All three routers fully async (AsyncSession via `select()`, never sync `.query()`)
- `upload.py` — validates type+size, saves with UUID prefix via `save_upload()`, creates Job with `file_path` stored for later deletion, launches `DocumentProcessor.process()` as BackgroundTask via a fresh `AsyncSessionLocal` session; WebSocket at `/api/v1/ws/{job_id}` sends current job state on connect then stays open
- `jobs.py` — `GET /api/v1/jobs` returns up to 50 jobs newest-first as `list[JobResponse]`; `GET /api/v1/jobs/{job_id}` returns full `JobDetailResponse` (parses `students_json`/`subjects_json` from `ExtractedData`, builds `ExtractedDataSchema`); `DELETE /api/v1/jobs/{job_id}` cascade-deletes DB records then removes uploaded file + output files from disk
- `export.py` — `POST /api/v1/export` builds `ExtractedDataSchema`, calls `generate_excel()`, writes to `uploads/{job_id}/output_{filename}.xlsx`, saves `OutputFile` DB record, returns `FileResponse`; `GET /api/v1/export/{job_id}/download/{file_id}` re-serves a previously generated file
- `db_models.py` — added `file_path` (String 512, nullable) and `ai_confidence` (Float, nullable) to `Job`
- `processor.py` — now saves `ai_insight.confidence` → `job.ai_confidence`
- `schemas.py` — `UploadResponse.ai_insight` is now `AIInsight | None = None`; `ExtractedDataSchema.ai_confidence` has `default=0.0`
- Verified: `/health` → `{"status":"ok",...}`, `/docs` → 200, `/api/v1/jobs` → `[]`

**PROMPT 5 notes:**
- `generate_excel(extracted_data, style_config, output_filename) → bytes` — returns workbook as bytes via `io.BytesIO`, never writes to disk
- Sheet 1 "Subject-wise Roll Number List": label column A + one column per subject; Row 1 merged title with exam metadata; Row 2 two-line subject headers (code + name, wrap_text); alternating row colors; COUNTA formulas in count row; freeze panes at A3
- Sheet 2 "Summary": metadata block (rows 2–7), table with S.No/Code/Name/Enrolled (row 9+), SUM total row, note about multi-subject counting
- Border color #B0B0B0 on all table cells; row heights per spec (40/50/18/22px); column widths from StyleConfig
- Edge case: if no students, data_rows clamped to 1 so COUNTA range stays valid (non-backwards)

**PROMPT 4 notes:**
- `file_utils.py` — added `detect_file_type` (raises ValueError for .xls/unknown), `validate_file_size`, `save_upload`, `clean_text`; kept `validate_upload` + `safe_upload_path` for scaffold router backward compat
- `subject_utils.py` — complete rewrite: `detect_subject_code_pattern` (finds most common prefix like `MBAN\d+`), `extract_all_subjects` (paired code-name regex + lone codes), `normalize_subject_name`, `sort_subjects` (numeric suffix sort), `build_subject_roll_map`
- `pdf_extractor.py` — `extract_from_pdf(bytes, filename)` → `(students, subjects, text_sample)`; per-page roll number + subject extraction; pdfplumber table fallback then pypdf per-page fallback; whole-doc pypdf fallback if pdfplumber raises
- `excel_extractor.py` — `extract_from_excel(bytes, filename)` → `(students, subjects, text_sample)`; auto-detects Format A (matrix, ≥2 subject codes in header row) vs Format B (flat list, paper code column); sheet preference: "Split Subjects" → "Sheet1" → first
- `processor.py` — `DocumentProcessor.process(job_id, file_bytes, filename, db_session, ws_manager)`; 6 async steps at 5/15/40/60/80/100%; AI extraction fallback when rule-based finds no students; `validate_extraction` warnings logged; `process_job` stub kept for scaffold router

**PROMPT 3 notes:**
- `GroqClient` class in `groq_client.py` with `complete()` and `complete_json()` methods
- `complete_json()` strips markdown code fences before JSON parse; returns `{}` on failure
- Retry logic: 3 attempts, 2s delay on `RateLimitError`; other errors raise `RuntimeError`
- `get_groq_client()` uses `@lru_cache(maxsize=1)` for singleton
- `classify_document(text_sample, filename) → AIInsight` — 8 doc types, extracts subjects/metadata
- `extract_students_ai(text_sample, doc_type, detected_subjects) → list[StudentRecord]` — AI fallback extractor, merges duplicates, filters to known subject codes
- `validate_extraction(students, expected_subjects) → dict` — checks for duplicates, unknown codes, missing subjects
- `processor.py` scaffold updated to stub (broken old imports removed); full pipeline in Prompt 4
- Real Groq API key required in `.env` — set `GROQ_API_KEY=gsk_...`
