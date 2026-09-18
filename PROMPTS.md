# ExamRoll — PROMPTS.md

**Purpose:** the exact sequence of prompts to run (one per Claude Code session) to take ExamRoll from
its current state to *safe to publish*, following `FUTURE.md` Revision 2 (§22 gates). Run them in
order. Do not start a prompt until the previous one's **Done when** list is fully true.

**Generated:** 2026-09-18 · **Source of truth:** `FUTURE.md` (Part I audit + Part II product plan),
`PROGRESS.md`, `CLAUDE.md`, `DESIGN.md`.

---

## How to use this file

1. Open a fresh Claude Code session in the repo root for each prompt. Paste the **Preamble** below
   first, then the prompt. The preamble is identical every time; it is what keeps 30 sessions
   consistent.
2. Each prompt ends with **Done when**. Verify every line yourself before moving on — run the
   commands, open the files. A prompt that is "mostly done" blocks the next one.
3. Every prompt updates `PROGRESS.md` (tick the task, add a dated note) and, when it changes an
   architectural decision, `CLAUDE.md`. That is part of the prompt, not optional.
4. If a prompt fails mid-way, re-run the *same* prompt with "Continue from where the last session
   stopped; read PROGRESS.md and `git status` first." Never skip ahead.
5. Prompts marked **[needs answer]** depend on an open question in `FUTURE.md` §23. Answer it in
   the prompt text before running.

---

## Preamble (paste before every prompt)

```
You are working on ExamRoll. Before doing anything:
1. Read CLAUDE.md, PROGRESS.md, DESIGN.md in full, and the FUTURE.md sections this prompt names.
2. Run `git status` and `git log --oneline -10`. Work on a feature branch named after the prompt
   (e.g. `p03-extraction-tests`). Commit with conventional commits; one logical change per commit.
3. Rules that override anything else:
   - Never weaken an existing test to make it pass. If a test is wrong, say so and explain why.
   - Never hardcode colours, shadows or fonts in components — use the tokens in DESIGN.md.
   - Every string that reaches an Excel cell from user, document or AI input goes through `_safe()`.
   - Every new table has `org_id NOT NULL` (FUTURE.md §13.1 rule 3).
   - No new user-facing feature that is not in this prompt. If you notice something else broken,
     write it in PROGRESS.md under "Found during <prompt id>" and continue.
   - Do not raise Groq `max_tokens` above 4096 (PROGRESS.md notes, 8000 TPM limit).
4. When finished: run the full backend test suite and `npm run build`; update PROGRESS.md (tick
   tasks, dated note with what changed and what you verified); update CLAUDE.md if an
   architectural decision changed; list the "Done when" items from the prompt and state for each
   whether it is true, with the command or file that proves it.
```

---

# GATE P — Private pilot (FUTURE.md §22)

Exit: real attestation sheets from the pilot centre import with correct counts and statuses; the
test suite is green in CI; one centre runs behind a shared key on Postgres.

---

### P01 · Baseline commit and the PII log leak

> FUTURE.md: P0-7, WS-0. PROGRESS.md: WS-0.

```
Task: establish a clean baseline and stop student PII flowing into production logs.

1. Commit the 5 uncommitted backend modifications (config.py, database.py, routers/upload.py,
   services/pipeline/processor.py, utils/file_utils.py) and FUTURE.md as `chore: baseline before
   Gate P`. Review the diff first and describe in the commit body what each file changed.
2. Fix database.py:11 per FUTURE.md P0-7: replace the inverted `echo=` with a `sql_echo: bool =
   False` setting in config.py plus the `never_echo_in_production` validator that raises at boot
   when `sql_echo` is true and `app_env == "production"`. Add a unit test for the validator.
3. Add the pilot notice: replace "Welcome to ExamRoll" on Dashboard.jsx with a clearly visible
   "Pilot instance — <org name>" banner using the `highlight` token, text from a
   `VITE_PILOT_NOTICE` env var (empty = hidden).
4. Update .env.example, render.yaml, DEPLOYMENT.md for the new variables.
```

**Done when**
- `git log` shows the baseline commit and a separate `fix:` commit for P0-7.
- Starting the app with `APP_ENV=production SQL_ECHO=true` exits with the validator's message.
- `pytest -q` shows the same pass count as before plus the new test; no new failures.

---

### P02 · Delete the red tests, add test infrastructure and CI

> FUTURE.md: P0-3, P3-63, §10 "Routers". PROGRESS.md: WS-A (tests half).

```
Task: make the test suite trustworthy and make it run on every push.

1. Delete tests/test_ai.py and tests/test_generators.py (they test APIs that no longer exist —
   FUTURE.md P0-3 shows the exact mismatches). Do not port them; the real API gets tests in P03/P05.
2. Add backend/pytest.ini exactly as FUTURE.md P0-3 specifies (asyncio_mode=auto, testpaths,
   pythonpath, --strict-markers). Add `httpx` and `pytest-asyncio` pins to requirements.txt.
3. Add tests/conftest.py providing: an async test DB (fresh SQLite file per session for now — it
   moves to Postgres in P08), an `AsyncClient` fixture against the FastAPI app with
   BackgroundTasks running inline, and a `make_pdf_pages` helper that patches
   `pdf_extractor._extract_page_texts`.
4. Add tests/test_routers.py covering /health, POST /upload (happy path, .xls rejected, >max size
   rejected, >max_batch_files rejected), GET /jobs, GET /jobs/{id} 404, DELETE /jobs/{id},
   POST /export happy path, GET /export/{job}/download/{file} 404.
5. Add .github/workflows/ci.yml: on push and PR — Python 3.12 matrix job running `pytest -q` in
   backend/, Node 20 job running `npm ci && npm run build` in frontend/. Cache pip and npm.
6. Change backend/.python-version from 3.14.5 to 3.12 and verify requirements install cleanly
   on 3.12 (FUTURE.md Part II §7 note: 3.14 wheel risk for asyncpg/argon2). Update the
   Dockerfile base image to python:3.12-slim-bookworm.
```

**Done when**
- `pytest -q` → 0 failed. Count recorded in PROGRESS.md.
- A push to a branch shows a green CI run with both jobs.
- `tests/test_routers.py` exists and exercises every route listed above.

---

### P03 · Regression tests that would have caught the data loss (written BEFORE the fix)

> FUTURE.md: P0-1, P0-2, P0-3 test snippets, §10 "Correctness".

```
Task: write failing tests that pin the extraction bugs, and commit them red.

Create tests/test_extraction_correctness.py with, at minimum:
- test_multiple_students_on_one_page_are_all_extracted (3 "Roll No:" lines on one page → 3 students)
- test_roll_numbers_never_become_subject_codes (no roll appears in subjects; no student's own roll is
  in its subject list)
- test_one_student_per_page_still_works (the current attestation shape — must keep passing)
- test_xlsx_header_202401_is_not_a_subject (excel_extractor `_is_subject_code`)
- test_bare_column_roll_layout (rolls listed with no "Roll No:" prefix, one per line)
- test_low_yield_warning (a 40-page doc yielding 1 student produces the warning text)
- test_pin_and_phone_numbers_are_not_subject_codes (existing behaviour — keep)

Use the exact page fixtures from FUTURE.md P0-1 and P0-2. Mark the tests you expect to fail today
with `@pytest.mark.xfail(strict=True, reason="P0-1/P0-2 not fixed yet")` so CI stays green but
the suite records that they fail. Commit as `test: pin P0-1/P0-2 extraction bugs`.
```

**Done when**
- The new file has ≥7 tests; the xfail ones fail for the right reason (show the assertion), the
  others pass.
- CI green.

---

### P04 · Extraction rewrite: per-line rolls, code disambiguation, status, name, exam code

> FUTURE.md: P0-1, P0-2 fixes; Part II §14 (WS-G) in full; P2-21, P2-22, P2-23.

```
Task: fix the two data-loss bugs and extend extraction with the fields the exam-centre workflow
needs. Read FUTURE.md §14 before writing code.

1. pdf_extractor.py: replace the `.search()` loop with the per-line scan in FUTURE.md P0-1 (roll
   on a line takes that line's codes; falls back to page codes for the one-student-per-page
   layout; bare-column layout fallback). Add the low-yield warning in processor.py.
2. subject_utils.py: split `_CODE_RE` into `_ALPHA_CODE_RE` (always accepted) and
   `_NUMERIC_CODE_RE` (accepted only with a subject/paper/course label nearby) per P0-2; add the
   `exclude` parameter and thread the document's roll numbers through it from both extractors.
   Fix P2-21 (alias expansion keeps the remainder), P2-22 (non-greedy `_PAIR_RE`), P2-23
   (`.isdecimal()`).
3. New fields per student (§14.1): `name` (printable, ≤120), `status` mapped through an
   allowlist to the enum {regular, ex, atkt, private, other} — unknown spellings → `other` +
   warning with count; missing → `regular` + warning with count; `admission_year` derived from an
   8-digit roll's first two digits. Add these to StudentRecord in schemas.py and to
   students_json.
4. New fields per paper (§14.2): `exam_code` (org-configurable regex, default
   `^[A-Z]{1,3}-?\d{3,6}$`), `paper_no`, `group_label`, all optional at extraction time.
5. Delete the "longer name wins" branch of merge_subject_maps. Same code + different name in one
   batch → record a `SubjectConflict` in processing_warnings with both names; pick neither.
6. Remove the xfail markers from P03's tests; add §14.5's tests (status vocabulary, missing status
   warning, conflict recorded, no auto-pick). Add a golden-file test harness:
   tests/golden/<course>.pdf.txt (page texts) + expected.json (counts, statuses, codes) — commit
   one synthetic example now; real anonymised ones are added in P12.
```

**Done when**
- All P03 tests pass without xfail; §14.5 tests pass.
- Running the real 167-page attestation PDF (`01_SRIT Regular 167.pdf`) still yields 167
  students / 15 subjects (regression against PROGRESS.md's recorded numbers).
- `processing_warnings` on a 3-student page with no status text contains "3 students … defaulted
  to Regular".

---

### P05 · Output and AI safety

> FUTURE.md: P0-5, P0-10, P0-9 (Groq budget only), §8.4 item 2.

```
Task: make it impossible for document or AI content to become a formula, and make the AI a
labeller rather than a source of truth.

1. excel_generator.py: add `_safe()` exactly as FUTURE.md P0-5 and apply it at every user/AI sink
   (rolls, headers, title, metadata, summary table). The generator's own COUNTA/SUM formulas must
   not pass through it. Add tests/test_excel_injection.py from P0-3 (no cell has data_type 'f'
   except =COUNTA/=SUM).
2. Create app/services/ai/validation.py per P0-10 (`valid_roll`, `valid_code`, `valid_status`,
   `clean_text_field`, MAX_* constants). Validate every field the classifier and extractor
   return; count and warn on rejects.
3. Prompt fencing in classifier.py and extractor.py per P0-10 layer 1 (`<document>` tags, closing
   tag stripped, "untrusted data" instruction).
4. processor.py: the AI may only *label* subjects the deterministic extractor found — replace the
   merge at processor.py:444-449 with the P0-10 layer 3 code (fill missing names only, warn on
   invented codes, route names through normalize_subject_name).
5. Groq daily budget: `groq_daily_call_budget` setting (default 500), a persisted daily counter
   (DB table `ai_usage(date, calls)`), and a skip-with-warning path when exhausted. Add
   `Organization`-independent `groq_enabled` setting for now; the per-org flag arrives in P09.
6. Tests: malformed AI roll rejected and counted; oversized notes truncated; invented subject code
   ignored with warning; budget exhaustion falls back to rule-based without failing the job.
```

**Done when**
- `tests/test_excel_injection.py` passes; the P0-5 repro in FUTURE.md §10 prints nothing.
- An uploaded PDF containing "Ignore prior instructions…" produces a job whose subjects are only
  the deterministic ones (test with a fixture).
- `/health` reports the Groq daily count.

---

### P06 · Request hardening for the pilot

> FUTURE.md: P0-6, P2-30, P2-32, P1-11, P1-12 (caps only).

```
Task: bound every input before it touches disk or memory.

1. app/middleware.py: BodySizeLimitMiddleware from FUTURE.md P0-6 (Content-Length pre-check plus
   streaming counter → 413). Register it in main.py. Set `File(..., max_length=max_batch_files)`
   on the upload route. Move the batch-total check inside the streaming loop.
2. main.py: docs_url/redoc_url/openapi_url = None when app_env == "production" (P2-30).
3. /health: real DB round-trip (`SELECT 1`) returning 503 with {"db": "unreachable"} on failure
   (P2-32). Keep the Groq status and daily count.
4. excel_extractor.py: `_read_rows` with max_rows_per_sheet / max_cols_per_sheet settings and a
   truncation warning; `_reject_zip_bomb` pre-flight; `wb.close()` in finally (P1-11).
5. pdf_extractor.py: `max_pdf_pages` setting with a truncation warning; stop building `full_text`
   as a second copy — extract subjects per page and merge (P1-12).
6. Tests: 413 before any file lands in upload_dir; production app has no /docs; /health 503 when
   the DB URL is bogus; a 200k-row xlsx fixture is truncated with a warning, not OOM.
```

**Done when**
- All six tests pass; `curl -H "Content-Length: 999999999"` gets 413 in <50 ms.
- Memory test: uploading the 168-page PDF peaks under 100 MB (measure with tracemalloc in a test
  or note the number in PROGRESS.md).

---

### P07 · Pilot access key and honest UI

> FUTURE.md: P0-4 interim mitigation, P3-70, §11 "fake features".

```
Task: stop anonymous access for the pilot, and remove features the product does not have.

1. app/auth.py: `require_pilot_key` from FUTURE.md P0-4 (X-ExamRoll-Key header, hmac.compare_digest,
   `pilot_access_key` setting; empty setting = 503 "not configured", never open). Apply as a
   router-level dependency on jobs, upload and export routers. Health stays public.
2. WebSocket: read the same key from a `key` query parameter on /ws/jobs/{id} (temporary until
   P-M03 replaces it with the session cookie); close 1008 if wrong; check the job exists before
   accept. Delete the duplicate WS endpoint in upload.py (P1-23).
3. Frontend: a one-time key entry screen stored in memory + sessionStorage; axios interceptor adds
   the header; WS URL carries the key; 401/503 → back to the key screen.
4. Remove the three "Coming Soon" tiles in OutputTypeSelector.jsx and the dead "Edit manually"
   button in Upload.jsx. README.md: replace "runs locally, no cloud account" and "Groq Llama 3.1"
   with accurate statements (P3-70).
5. Tests: every protected route 401 without the key; WS closes without it; 200 with it.
```

**Done when**
- Unauthenticated `GET /api/v1/jobs` → 401; with key → 200.
- The UI has no "Coming Soon" text anywhere (`grep -ri "coming soon" frontend/src` empty).

---

### P08 · Alembic and managed Postgres

> FUTURE.md: P2-44, P2-26, P2-27, P1-26, §9 "Why Postgres moved". §23 Q12. **[needs answer: Neon or Supabase]**

```
Task: move durable state to Postgres under Alembic, without changing behaviour.

1. Add `alembic`, `asyncpg`, `psycopg[binary]` (sync driver for Alembic) to requirements.txt.
   `alembic init backend/alembic`; configure env.py to read DATABASE_URL from app settings and to
   use the sync URL for migrations. Fix alembic.ini's driver.
2. Migration `0000_baseline`: autogenerate from the current models (jobs, extracted_data,
   output_files) and verify it matches an existing SQLite DB's schema. Add the P2-33 unique
   constraint and P2-34 indexes in this migration.
3. Delete `_add_missing_nullable_columns` from database.py and the `create_all` call; the app
   refuses to start if `alembic current` is not head (log a clear message).
4. Postgres: provision <Neon|Supabase> free tier; DATABASE_URL uses `postgresql+asyncpg://`.
   Keep SQLite working for tests only (conftest) — production and dev use Postgres.
5. Replace the per-job JSON-in-TEXT columns' types with JSONB on Postgres via a type decorator
   that stays TEXT on SQLite. Enforce String(n) limits in Pydantic so Postgres never rejects a row
   (P0-10 note).
6. Update DEPLOYMENT.md, render.yaml, Dockerfile CMD (`alembic upgrade head && exec uvicorn …`).
7. Tests: migration up/down round-trip on an empty Postgres (CI service container); router tests
   run against Postgres in CI too.
```

**Done when**
- `alembic upgrade head` on the empty managed DB succeeds; app boots; an upload round-trips.
- CI runs the suite against a Postgres service container and is green.
- No `create_all` or hand-rolled ALTER remains in the codebase.

---

### P09 · Tenancy tables (`0001`) and the exam model (`0002`)

> FUTURE.md: §7.1 (amended), §7.2 (amended), §13 in full. §23 Q18–Q20 do not block this.

```
Task: create the organisation/user tables and the normalised exam-centre model, and backfill
existing jobs into them. Read FUTURE.md §13.1–§13.5 before writing a line.

1. db_models.py: Organization (with centre_code, university_name, address, per_candidate_rate,
   currency, ai_processing_enabled, docket_labels JSON, the three retention_* columns), User
   (role ∈ admin|controller|clerk), AuthSession (§7.1 Session renamed), College, Course, Exam,
   SubjectOffering (UNIQUE(org_id, exam_id, exam_code)), Student (roll_number TEXT,
   roll_sort_key, UNIQUE(org_id, roll_number)), Enrollment (UNIQUE(student_id, offering_id)).
   Job gains org_id NOT NULL, exam_id, college_id. Every new table: org_id NOT NULL, indexed.
2. Migration 0001_add_tenancy: create organizations/users/auth_sessions; jobs.org_id nullable →
   insert the pilot org (name, centre_code, university from env vars PILOT_ORG_NAME,
   PILOT_CENTRE_CODE, PILOT_UNIVERSITY) → backfill → NOT NULL.
3. Migration 0002_exam_model: create the six tables; backfill from every ExtractedData blob into
   a synthetic Exam "Legacy import <date>" under the pilot org: one Student per distinct roll,
   one SubjectOffering per distinct code (exam_code = code), one Enrollment per (roll, code).
   Idempotent; logs counts; asserts Σ enrollments == Σ distinct (roll, code) pairs across blobs.
   Write and test downgrade().
4. utils/roll.py: `roll_sort_key(roll: str) -> str` (natural sort, digit runs zero-padded to 12,
   non-digit runs lower-cased) and `admission_year(roll)`. sort_roll_numbers now delegates to it.
5. processor.py: new `persisting_rows` stage after `saving` — upsert Student / SubjectOffering /
   Enrollment for the job's exam and college; "N already enrolled" replaces the dedupe count.
6. Routers: rooms/exams/colleges CRUD is NOT in this prompt. Only: GET /api/v1/exams,
   POST /api/v1/exams, GET /api/v1/colleges, POST /api/v1/colleges (all behind the pilot key,
   scoped to the pilot org via a `current_org()` dependency that returns the single org for now).
7. Tests: migration round-trip on Postgres with a seeded blob; backfill counts; upsert
   idempotence (upload same sheet twice → 0 new students); roll_sort_key ordering on the mixed
   fixture from FUTURE.md §20 ("0012", "12", "24109301", "MBA/23/001").
```

**Done when**
- `alembic upgrade head` from `0000` on a DB with real jobs creates the rows and logs matching counts.
- Second upload of the same sheet reports "N already enrolled", inserts no Student rows.
- `select roll_number from students order by roll_sort_key` is ascending numerically for 8-digit rolls.

---

### P10 · Upload flow: exam + college picker, conflict review, per-org AI opt-out

> FUTURE.md: §14.3, §14.4, §8.4 item 2, P0-10 principle.

```
Task: make every upload land in a known exam and college, and let the user resolve subject
conflicts instead of the pipeline guessing.

1. Upload.jsx: new Step 0 before the drop zone — "Exam" select (with inline create: title,
   programme label, semester, year, sticker label) and "College" select (inline create: name,
   short name). Files cannot be added until both are chosen. POST /upload takes exam_id and
   college_id; Job stores them. The AI classifier's course/semester guess pre-fills but never
   creates.
2. Review step: render SubjectConflict warnings as a card with both names and a radio; the
   choice is POSTed to /api/v1/exams/{id}/offerings/{code} and stored on SubjectOffering. Export is
   blocked while a conflict is unresolved.
3. `Organization.ai_processing_enabled=False` → processor skips Groq entirely (rule-based path),
   emits the ai_analysis stage as "skipped (AI disabled for this organisation)". Expose a toggle
   in a minimal Settings page (org name, centre code, university, rate, AI toggle) behind the
   pilot key.
4. Job list and detail show exam and college. History filter by exam.
5. Tests: upload without exam_id → 422; conflict blocks export until resolved; AI disabled →
   zero Groq calls (mock asserts not called).
```

**Done when**
- A new upload requires exam + college in the UI and API.
- A batch with `210236 - Business Mathematics` and `210236 - Bus. Maths` shows a conflict card and
  export is disabled until chosen.
- With AI disabled, the stage list shows "skipped" and the job completes.

---

### P11 · Subject-wise output on the new model (O3b) and roll-as-text

> FUTURE.md: §17 O3b, §18, P1-17, P1-18.

```
Task: make the existing Excel output read from Enrollment rows, write rolls as text, and fix the
export race.

1. excel_generator.py: source data from Enrollment ⋈ Student ⋈ SubjectOffering ordered by
   roll_sort_key (not from students_json). Rolls written as text with number_format '@'. Add the
   exam-code row under each subject code and a count row above (Sheet1!M1:Q3 layout from
   FUTURE.md §12.2). Keep the Summary sheet.
2. Introduce services/generators/workbook_builder.py: shared styles, `_safe()`, A4 page setup
   helpers (orientation, scale, print area, print_title_rows, margins), Devanagari font
   declaration (Mangal, Noto Sans Devanagari fallback). The subject-wise generator uses it; later
   generators will too.
3. export.py: run generate_excel in `asyncio.to_thread` (P1-18); write to a temp file and
   atomic-rename; reuse the OutputFile row when the name matches (P1-17).
4. Golden-file test: generate from a fixture and compare cell values, number formats, merges and
   print setup to tests/golden/subject_wise.xlsx (create it in this prompt, open it in Excel once
   to confirm, then commit).
5. Tests: every roll cell has data_type 's' and number_format '@'; column order ascending; two
   concurrent exports of one job produce one OutputFile row and identical bytes.
```

**Done when**
- Golden test passes; opening the file in Excel shows rolls left-aligned as text and ascending.
- `ab -c 5 -n 20` (or a pytest concurrency test) on /export produces no corrupt file.

---

### P12 · Real-data golden files and the Gate P sign-off

> FUTURE.md: §14.5 golden files, §10 manual smoke test, §22 Gate P exit criterion.

```
Task: prove Gate P against the pilot centre's real documents and close the gate.

1. Add anonymised page-text fixtures (roll numbers shifted by a constant, names replaced) for one
   attestation sheet per course the centre handles (M.Com, M.A., M.Sc., M.S.W., B.B.LLB) under
   tests/golden/<course>/ with expected.json (student count, status counts, exam codes/paper
   codes, warnings expected). I will provide the source PDFs; write the anonymiser script in
   scripts/anonymise_fixture.py and commit only its output.
2. Run the full §10 manual smoke test and record every result in PROGRESS.md.
3. Deploy to the pilot host (Render/Northflank per DEPLOYMENT.md) with Postgres, the pilot key,
   APP_ENV=production, SQL_ECHO unset. Verify /health, one real upload, one export, and that the
   production logs contain no roll numbers.
4. Update PROGRESS.md: mark Gate P closed with date; update CLAUDE.md schema section (it still
   lists `extracted_rows`) to the real models; make CLAUDE.md and README.md link to PROGRESS.md
   for phases instead of carrying their own tables.
```

**Done when**
- Every golden fixture passes with exact counts.
- PROGRESS.md has a dated "Gate P closed" entry with the smoke-test results.
- CLAUDE.md schema section matches db_models.py.

---

# GATE F — Features on Postgres (FUTURE.md §22)

Exit: one full exam session at the pilot centre from upload to docket with no hand edits to any
workbook.

---

### F01 · Frontend reliability floor

> FUTURE.md: P1-19, P1-20, P1-21, P1-22, P1-24. Pulled forward per §22.

```
Task: fix the frontend bugs a clerk entering 400 attendance rows cannot tolerate.

1. React error boundary at the router level with a "Something went wrong — reload / go home"
   panel in DESIGN.md tokens (P1-19).
2. JobDetail.jsx refetchInterval: v5 signature, return false when the job is completed/failed (P1-20).
3. useJobStatus.js: polling fallback via GET /jobs/{id} every 3 s after WS retries are exhausted;
   clear the reconnect timer on unmount and on job change (P1-21, P1-22).
4. client.js: if VITE_API_BASE_URL is unset in a production build, throw at startup with a clear
   message; axios response interceptor rejects any HTML body (P1-24).
5. Add Vitest + React Testing Library; tests for the timer cleanup, the refetchInterval callback,
   and the error boundary. Add `npm test` to CI.
```

**Done when**
- Killing the backend mid-job shows a failure state in the UI within 15 s, not a spinner.
- `npm test` runs in CI and is green.

---

### F02 · Migration `0003`: rooms and sessions; Room library API

> FUTURE.md: §13.2 (Room, ExamSession, SessionPaper), §13.4, §15.1, §15.2 steps 1–3.

```
Task: model rooms as columns of seats and sessions as date+shift slots.

1. Models + migration 0003_rooms_sessions: Room (seat_columns JSON [{label, seats}],
   blocked_seats JSON [{col, seat}], seats_per_bench, is_active, sort_priority, building, notes),
   ExamSession (UNIQUE(org_id, date, shift)), SessionPaper (UNIQUE(session_id, offering_id)).
   Capacity is a computed property, never a column.
2. Pydantic validation: seat_columns non-empty, each seats ≥ 1; blocked_seats must reference an
   existing (col, seat); seats_per_bench ∈ {1,2,3}.
3. Routers: /api/v1/rooms CRUD (delete refused if used by a published plan → 409, deactivate
   instead); POST /api/v1/rooms/generate {count, columns, seats_per_column, seats_per_bench,
   name_pattern} creating N rooms; /api/v1/sessions CRUD; PUT /api/v1/sessions/{id}/papers
   (set of offering ids).
4. Clash check on PUT papers: students enrolled in ≥2 papers of the session → response lists
   them with both exam codes; stored as session.clashes JSON; acknowledgement endpoint.
5. Tests: capacity of the FUTURE.md §12 Library Hall (columns 3/13/13/4, 2 blocked) = 31;
   generate creates N identical rooms; clash detected for a seeded student.
```

**Done when**
- The Library Hall and Room 4 from the workbook can be created via the API exactly as laid out.
- Clash endpoint returns the seeded clash; publishing is not yet possible (F04) so nothing more.

---

### F03 · Room library and session setup UI

> FUTURE.md: §15.6 (Rooms, Session), DESIGN.md tokens.

```
Task: build the two configuration screens for seating.

1. /rooms: table (name, building, columns, capacity, active) + "Generate rooms" dialog (Option 1)
   + room editor (Option 2): a visual column stack where each column is a vertical list of seat
   cells; click a seat to block/unblock (seat-blocked token); "+ column", "− column", and a
   per-column seat-count stepper; live capacity chip; rename; deactivate. Add the six seat-state
   tokens to theme.css and tailwind.config.js as tinted-background + solid-text pairs and
   document them in DESIGN.md.
2. /sessions: list by date; session form (date, shift, times); papers multi-select grouped by
   exam and course with enrolment counts; clash panel with acknowledge buttons; room picker
   (ordered, drag to reorder, each room tagged with the exam it serves) with a live
   "required seats / available seats" bar (error token when short).
3. Reduced-motion and keyboard access for the seat grid (arrow keys move, space toggles).
4. Vitest: capacity chip updates on block/unblock; generate dialog validation; clash panel
   renders seeded clashes.
```

**Done when**
- Entering the workbook's five rooms + two labs takes under five minutes in the UI.
- Screenshot of the room editor at 1120 px width attached to PROGRESS.md notes (7-column room legible).

---

### F04 · Migration `0004`: the allocator, validator and plan lifecycle

> FUTURE.md: §15.3, §15.4, §15.5, §20 allocator invariants, §21 item 4. **[needs answer: Q5 adjacency rule when seats_per_bench > 1; default from §15.3 if unanswered]**

```
Task: implement the seating allocator as a pure function with an independent validator, and the
plan lifecycle around it. No UI in this prompt.

1. Models + migration 0004_seating: SeatingPlan (version, status draft|published|superseded,
   strategy JSON, seed, created_by, published_by, published_at), SeatingPlanRoom (order_index,
   exam_id), SeatAssignment (col_index, seat_index, bench_pos, student_id, offering_id, locked;
   the two UNIQUE constraints from §13.2).
2. services/seating/allocator.py: `allocate(roster, rooms, strategy, locked) -> AllocationResult`
   implementing every strategy key in §15.3 with the workbook defaults (column_major,
   by_exam_code, contiguous_by_paper, adjacency none / no_same_paper_on_bench when
   seats_per_bench > 1, atkt_after_regular_per_paper, room_split allow, seed 0). Deterministic:
   any randomness comes from `random.Random(seed)`. Returns assignments, gaps, unseated.
3. services/seating/validator.py: `validate(plan) -> list[Violation]` checking every invariant in
   §15.4 independently of the allocator (do not share helper code that could hide a shared bug).
4. Lifecycle service: create draft (runs allocator), edit ops (move, swap, lock/unlock, block seat
   → re-run preserving locks), publish (controller role — for now any pilot-key user with
   role=controller chosen at key entry; refused if unseated or violations non-empty), new version
   (copies locks, supersedes the old).
5. Routers: POST /sessions/{id}/plans, GET /plans/{id}, POST /plans/{id}/{move|swap|lock|rerun|publish|new-version}.
6. Tests: Hypothesis property tests over random rooms (1–8 columns, 1–20 seats, random blocked),
   1–6 papers, all strategy combinations: validate(allocate(x)) == [] when capacity suffices;
   same seed ⇒ identical; locked never moves; unseated == shortfall exactly. Plus a fixture that
   reproduces the workbook's Rooms 1–3 with the 15-Sept roster ordering and asserts column 1 of
   Room 1 is 24109301, 302, 304, 305, 306, 308.
```

**Done when**
- Property tests run ≥200 examples each and pass.
- Publishing a plan with one unseated student returns 409 naming the roll.
- The workbook fixture reproduces Room 1's first column exactly.

---

### F05 · Seating plan UI

> FUTURE.md: §15.6 (Plan).

```
Task: the plan screen — one grid per room, server-authoritative.

1. /sessions/{id}/plan: room tabs or stacked room cards; each cell shows the roll (and paper
   colour from a legend keyed by exam_code — colours derived from the palette, AA-checked);
   blocked seats show "x" in seat-blocked; locked seats show a lock glyph.
2. Interactions: drag a student to an empty seat (move), onto another (swap), right-click/kebab →
   lock; "Re-run with locks"; strategy drawer (every §15.3 key as a control); violations panel
   listing each violation with a "go to seat" link; "Publish" disabled until violations and
   unseated are both zero; version banner with "Create version 2" after publish.
3. Every interaction is an API call; the grid re-renders from the response. No client-side
   allocation logic.
4. Vitest: publish button disabled state; violation list rendering; drag → API call payload.
```

**Done when**
- A full plan for the workbook's roster (175 candidates, 7 papers, 5 rooms + labs) can be
  generated, edited and published from the UI.
- Playwright run recorded in PROGRESS.md.

---

### F06 · Seating outputs: O1 chart, O5 stickers, O7 index, session pack skeleton

> FUTURE.md: §17 table rows O1, O5, O7, O8; §17.1 reconciliation; §18.

```
Task: generate the printed seating documents from a published plan.

1. services/generators/seating_chart.py (O1): layout per FUTURE.md §17 O1 and the `Room Dist`
   sheet — title, per-room exam label, room name, column headers from seat_columns labels, seat
   rows, "x" for blocked/empty, "TOTAL = n" computed, grand total; landscape A4 ~97 %, one or two
   room blocks per page by row count; print area set per page.
2. stickers.py (O5): 5 across, two merged rows per sticker (Exam.sticker_label over the roll,
   18 pt), 20 per page with row breaks, seating order; portrait A4 ~91 %.
3. roll_index.py (O7): roll → room → column/seat ascending, per exam.
4. Session pack: POST /sessions/{id}/pack → zip of the outputs available so far, file names per
   §17 O8; refuses (409, with details) if the reconciliation check fails: roster size == Σ room
   totals == Σ paper totals.
5. Golden-file tests for O1 (the workbook's Room Dist reproduced from the fixture plan), O5, O7;
   reconciliation test where one student is missing from every room.
```

**Done when**
- O1 for the fixture matches `Room Dist` block-for-block (values, "x", totals).
- Opening O1/O5 in Excel prints correctly on A4 without manual scaling (record in PROGRESS.md).

---

### F07 · Migration `0005`: attendance, UFM, roles

> FUTURE.md: §16.1, §16.2, §16.4, §13.2 (Attendance, AttendanceAudit, MalpracticeCase). **[needs answer: Q7 mandatory UFM fields/categories; Q9 who publishes/closes]**

```
Task: the attendance write path and its audit trail.

1. Models + migration 0005_attendance: Attendance (UNIQUE(session_id, offering_id, student_id),
   present NOT NULL, booklet_no, room_id, marked_by/at, updated_by/at), AttendanceAudit,
   MalpracticeCase (UNIQUE(attendance_id), case_no, category from an org-configurable list,
   remarks, reported_by/at, outcome, closed_at). ExamSession gains status open|closed, closed_by/at.
2. Endpoints: GET /sessions/{id}/rooms/{room}/attendance (seat-ordered rows pre-filled from the
   published plan, present=true default, not yet persisted); PUT /attendance/{session}/{offering}/
   {student} — per-row UPSERT; every change writes an AttendanceAudit row; POST /sessions/{id}/close
   (controller); after close, PUT requires controller and a `reason`.
3. UFM: POST /attendance/{id}/ufm creates the case; PATCH for outcome (controller).
4. Roles: User.role is enforced by a `require_role()` dependency now (pilot-key users pick a role
   at key entry and it is stored in the auth session table introduced in P09 — a stopgap until
   Gate M's real login).
5. Tests: concurrent upserts from two clients converge to the last write with two audit rows;
   clerk edit after close → 403; controller edit after close without reason → 422; UFM case
   unique per attendance.
```

**Done when**
- All tests pass; `attendance_audit` has one row per change in a scripted sequence.

---

### F08 · Attendance entry UI

> FUTURE.md: §16.1, §15.6 tokens.

```
Task: the screen a clerk uses after each paper.

1. /sessions/{id}/attendance: room selector; rows in seat order (seat, roll, name if
   Organization.print_names, exam code, Present/Absent toggle, booklet no., UFM flag);
   "Mark all present" then exceptions; each toggle saves immediately (per-row PUT) with an inline
   saved/failed indicator and retry; summary strip: present / absent / UFM per paper in this room.
2. UFM flag opens a drawer: case number, category, remarks, reporter; saves the case.
3. Session close button (controller) with confirmation; after close the rows are read-only for
   clerks and editable-with-reason for controllers.
4. Keyboard-first: tab moves between rows, space toggles, Enter opens UFM.
5. Vitest: toggle → PUT payload; failed save shows retry; closed session disables toggles for
   clerk role.
```

**Done when**
- Entering attendance for a 49-seat room with one absentee takes under two minutes by keyboard.

---

### F09 · O2 room attendance sheet and O4 docket

> FUTURE.md: §16.3, §17 O2 and O4, §12.1 Hindi/Unicode rule, §20 docket golden file.

```
Task: the two documents the invigilator and the superintendent sign.

1. room_attendance_sheet.py (O2): from the published plan — header (centre, university, session
   date/shift, room, papers), rows in seat order (seat, roll, name*, exam code, Present ☐ /
   Absent ☐, booklet no., signature), invigilator signature block; portrait A4, print_title_rows
   so the header repeats.
2. docket.py (O4): one docket per (paper, session) per page, layout exactly per FUTURE.md §17 O4
   and the `Docket MCom` block: 7-row bilingual header (labels from Organization.docket_labels
   JSON, defaults = the Unicode strings from the workbook; the two Kruti Dev strings replaced by
   "कुल उपस्थित परीक्षार्थियों की संख्या" and "कुल अनुपस्थित परीक्षार्थियों की संख्या"), present grid 10 per
   row with at least 10 rows, present total, absent list, absent total, UFM rows, superintendent
   signature bottom-right; portrait A4 ~90 %; optional two-per-page mode. Font Mangal with Noto
   Sans Devanagari fallback. Rolls as text.
3. Both added to the session pack; pack refuses if present + absent ≠ roster for any paper.
4. Golden-file test: the K-3672 / 17-09-2026 docket from the workbook (48 present, absent
   24112021, 0 UFM) reproduced cell-for-cell from a fixture; O2 golden for one room.
5. Confirm in Excel and LibreOffice that Devanagari renders (record which fonts were present).
```

**Done when**
- The docket golden test passes; the printed docket is accepted by the centre superintendent as
  equivalent to the current form (record the sign-off in PROGRESS.md).

---

### F10 · O3 paper roll-list grid and O6 centre summary & claim

> FUTURE.md: §17 O3, O6; §12.1 Summ facts; §23 Q19, Q20. **[needs answer: Q20 enrolled vs present; Q19 "All Sub" rows]**

```
Task: the per-paper grids and the remuneration claim.

1. paper_roll_grid.py (O3): per day — for each paper in the session(s): header
   "<exam_code>  <course>  <subject> - <DATE>", index row 1..10, rolls 10 per row ascending,
   "Total n"; per-day "Grand Total" as a =SUM formula over the totals; landscape A4.
2. centre_summary.py (O6): title from the exams' programme labels; header S.No / Name of College
   / Course / Subject / Regular / Ex / ATKT / Total / Amount; rows grouped by course with TOTAL
   rows; Total = SUM(E:G) and Amount = Total * <rate cell> as live formulas referencing a single
   rate cell populated from Organization.per_candidate_rate; grand total; landscape A4 85 %.
   Counts are <enrolled|present> per Q20. "All Sub" aggregate rows per Q19.
3. Both added to the session pack (O6 also available per exam, independent of session).
4. Golden tests: O3 reproduces `Sheet1!A4:J42` for the fixture (grand total 175); O6 reproduces
   `Summ` including formulas (check `cell.value` starts with "=SUM"/"=H" and the rate cell ref).
```

**Done when**
- Both golden tests pass; O6 grand total for the fixture is 175 candidates → ₹35,000 in Excel.

---

### F11 · PDF rendering for the printed set

> FUTURE.md: §17.2. §23 Q15. **[needs answer: Q15 — skip this prompt if PDF is deferred]**

```
Task: PDF versions of O1, O2, O4, O5 with identical layout, for reliable printing.

1. Choose one renderer and record the decision in CLAUDE.md: HTML templates (Jinja2) rendered
   with a headless Chromium via Playwright — already used in tests — producing A4 PDFs; embed
   Noto Sans Devanagari. (reportlab is the fallback if Chromium is unavailable on the host.)
2. Templates for O1, O2, O4, O5 driven by the same data objects the Excel generators use; page
   breaks match the Excel versions.
3. Session pack gains a "PDF" variant; download buttons on the plan and attendance screens.
4. Tests: PDF page count equals the Excel page count for the fixture; text extraction of the
   docket PDF contains every present roll and the Devanagari labels.
```

**Done when**
- The four PDFs print on A4 with no scaling on the centre's printer (record in PROGRESS.md).

---

### F12 · Gate F sign-off: one real session end-to-end

> FUTURE.md: §22 Gate F exit criterion; §17.1.

```
Task: run one real exam session at the pilot centre through the app and fix what breaks.

1. Before the session: import all attestation sheets, set up papers, rooms, session; generate
   and publish the plan; print O1, O5, O7, O2.
2. During/after: enter attendance and any UFM per room; close the session; generate O4, O3, O6
   and the pack.
3. Compare every output with what the clerk would have produced by hand; record every difference
   in PROGRESS.md as "Found during F12" and fix the ones that are bugs in this session.
4. Update FUTURE.md §23 with answers learned; mark Gate F closed in PROGRESS.md.
```

**Done when**
- PROGRESS.md has a dated "Gate F closed" entry with the list of differences and their resolution.

---

# GATE M — Multi-centre, public (FUTURE.md §22)

Exit: a second centre onboarded with zero shared data; public URL.

---

### M01 · Topology decision and same-site setup

> FUTURE.md: §7.1 prerequisite box, §22 Gate M topology note, §23 Q12. **[needs answer: custom domain vs same-origin static serving]**

```
Task: make the app and API same-site so the session-cookie design works.

Option A (custom domain): register <domain>; app on apex via Cloudflare Pages, API on api.<domain>
via Render/Northflank; CORS_ORIGINS and VITE_API_BASE_URL set accordingly; document DNS in
DEPLOYMENT.md.
Option B (same origin): FastAPI serves frontend/dist via StaticFiles with SPA fallback at "/",
API under /api; remove CORS for production; Cloudflare Pages retired. Document in DEPLOYMENT.md
and CLAUDE.md; Dockerfile builds the frontend in a stage and copies dist.

Implement the chosen option. Verify with a browser that a cookie set by the API is sent on XHR and
on the WebSocket handshake (temporary test endpoint, removed after).
```

**Done when**
- DevTools shows the cookie on both an XHR and the WS handshake from the deployed frontend.

---

### M02 · Real authentication: argon2id, sessions, login

> FUTURE.md: §7.3, §7.4, P0-4. PROGRESS.md WS-D.

```
Task: replace the pilot key with server-side sessions.

1. app/auth.py per §7.3: create_session (httpOnly, Secure, SameSite=Lax, 7-day), current_user,
   require_org (sets request.state.org_id), require_role. argon2-cffi hashing. POST /auth/login,
   POST /auth/logout, POST /auth/logout-all (revokes every session of the user), GET /auth/me.
2. User management (admin): POST /users (email, role, temporary password), PATCH /users/{id}
   (role, is_active), password change; first admin created by a CLI command
   `python -m app.cli create-admin`.
3. Remove require_pilot_key and the key screens; frontend /login, auth context, 401 → /login,
   role-aware navigation (clerk cannot see Settings/Users).
4. Rate limiting per P0-9 with slowapi keyed on org then IP; uvicorn --proxy-headers; login
   endpoint 5/minute per IP.
5. Tests: login/logout/logout-all; expired session 401; inactive user 401; every route 401
   without a cookie; rate limit 429 on the 6th login attempt.
```

**Done when**
- No reference to `X-ExamRoll-Key` remains; every route requires a session; tests pass.

---

### M03 · Tenant isolation everywhere, WebSocket auth, the isolation matrix

> FUTURE.md: §7.4, §7.5, §7.6, P0-8, §20 last bullet.

```
Task: make cross-tenant access impossible and prove it.

1. Every router: `dependencies=[Depends(require_org)]` at router level; every query adds
   `.where(Model.org_id == org_id)` in the WHERE clause — never fetch-then-check. 404, never 403,
   for foreign rows. Audit every `select(` in the codebase and list them in the PR description
   with the filter added.
2. app/ws_auth.py per §7.5 / P0-8: Origin allowlist + session cookie + job-belongs-to-org before
   accept; 1008 on any failure; `finally: manager.disconnect`.
3. tests/test_tenant_isolation.py: create org A and org B with users; for EVERY table with org_id
   (jobs, exams, offerings, students, enrollments, rooms, sessions, plans, assignments,
   attendance, UFM, output files) assert: B cannot GET/PUT/DELETE A's row (404), B's list never
   contains A's ids, B's WS to A's job is closed. Generate the matrix from the router table so a
   new route cannot be forgotten.
4. Remove the temporary role-at-key-entry stopgap from F07.
```

**Done when**
- The isolation matrix test enumerates every org-scoped route and passes.
- `grep -rn "select(" backend/app/routers | grep -v org_id` is empty (or each exception is justified in the PR).

---

### M04 · Security headers, retention tiers, privacy pages, drop the blobs

> FUTURE.md: P1-25, P1-16 (amended), §16.5, §8.4, §13.4 `0006`.

```
Task: the legal and hygiene floor before a public URL.

1. Security headers (P1-25): CSP, X-Frame-Options DENY, HSTS, Referrer-Policy, Permissions-Policy
   — via frontend/public/_headers (Option A) or middleware (Option B).
2. app/janitor.py per §16.5: tier 1 deletes uploads/{job} files older than
   Organization.retention_source_days after successful import; tier 2 stops persisting
   raw_text_sample (store sha256 + length); tier 3 lists Exams past retention_record_years without
   legal_hold, and an admin confirms deletion via POST /admin/retention/purge/{exam_id} which
   logs the action. Dry-run mode logs what it would delete. Started from lifespan.
3. Migration 0006_drop_blobs: drop students_json, subjects_json, raw_text_sample (after
   confirming F12 ran on rows only).
4. /privacy and /terms routes with the content from §8.4 items 4–7 (what is collected, the Groq
   transfer and the per-org opt-out, the three retention tiers, grievance contact from
   Organization settings, erasure process); consent checkbox at upload recorded on Job
   (consent_by, consent_at); footer links.
5. Tests: janitor dry run touches tiers 1–2 only; legal-hold exam never listed; upload without
   consent → 422; headers present on every response.
```

**Done when**
- All tests pass; securityheaders.com (or curl) shows the headers on the deployed app.
- `raw_text_sample` no longer exists in the schema.

---

### M05 · Second centre onboarding and public launch checklist

> FUTURE.md: §10 smoke test, §22 Gate M exit criterion, Gate 1 items.

```
Task: prove multi-tenancy with a real second organisation and close Gate M.

1. Admin CLI/UI: create Organization #2 with its own admin; onboard rooms and one exam.
2. From two browser profiles logged into different orgs, walk the full flow in both and confirm
   neither sees the other's exams, rooms, plans, or jobs (screenshots in PROGRESS.md).
3. Run the §10 manual smoke test on the public deployment; check production logs for PII; run
   the isolation matrix against the deployed API with two real accounts.
4. Remaining Gate 1 items still open (P1-13, P1-14, P1-15: job status commits per stage,
   CancelledError handling, pipeline timeout + concurrency limit) — implement now; they are small
   and the pipeline is otherwise frozen.
5. Error tracking (P2-31): add Sentry (or equivalent) DSN via env var, frontend + backend.
6. Mark Gate M closed in PROGRESS.md; update README.md to describe the product as it is.
```

**Done when**
- PROGRESS.md: dated "Gate M closed — safe to publish" with the smoke-test and isolation results.
- Two orgs coexist on the public URL with zero shared data.

---

## After Gate M (not in this file)

Object storage and a durable queue (P1-26), college branding on outputs, hall tickets, marks entry,
email delivery, admin dashboard, accessibility pass (P2-29/P2-42). Plan them in a new PROMPTS-2.md
once Gate M is closed and the pilot centres have run at least two full exam cycles.

---

## Prompt index

| ID | Title | Gate | Needs answer |
|---|---|---|---|
| P01 | Baseline + PII log leak | P | — |
| P02 | Test infra + CI | P | — |
| P03 | Red regression tests | P | — |
| P04 | Extraction rewrite + status/name/exam code | P | — |
| P05 | Output + AI safety | P | — |
| P06 | Request hardening | P | — |
| P07 | Pilot key + honest UI | P | — |
| P08 | Alembic + Postgres | P | Q12 (host) |
| P09 | Tenancy + exam model migrations | P | — |
| P10 | Exam/college picker, conflicts, AI opt-out | P | — |
| P11 | Subject-wise output on rows, rolls as text | P | — |
| P12 | Real-data goldens, Gate P sign-off | P | — |
| F01 | Frontend reliability floor | F | — |
| F02 | Rooms + sessions model/API | F | — |
| F03 | Rooms + sessions UI | F | — |
| F04 | Allocator + validator + lifecycle | F | Q5 |
| F05 | Plan UI | F | — |
| F06 | O1/O5/O7 + pack + reconciliation | F | Q4 |
| F07 | Attendance/UFM model + roles | F | Q7, Q9 |
| F08 | Attendance UI | F | Q11 |
| F09 | O2 + O4 docket | F | — |
| F10 | O3 + O6 claim | F | Q19, Q20 |
| F11 | PDF rendering | F | Q15 |
| F12 | Gate F sign-off | F | — |
| M01 | Same-site topology | M | Q12 |
| M02 | Real auth | M | — |
| M03 | Tenant isolation + WS auth | M | — |
| M04 | Headers, retention, privacy, drop blobs | M | Q8 |
| M05 | Second centre + launch | M | — |