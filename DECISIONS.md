# ExamRoll — Decisions Log

A running record of problems hit during development and the decisions made to resolve them.
Format per entry: **What happened** → **Why** → **Cost of ignoring it** → **What we decided and why**.

This file is appended to as work progresses — it is not a design document, it is a record of
*why* the design ended up the way it did.

---

## 2026-09-19 — Auth topology: same-origin serving instead of a custom domain

**What happened.** The auth design this project settled on (`FUTURE_UNIFIED.md` §7) uses a
server-side session cookie (`httpOnly`, `SameSite=Lax`) rather than a JWT, specifically for
revocability — "log out everywhere" and "this account is compromised" are one `UPDATE` away,
which a stateless token cannot do without building a session table anyway. But `SameSite=Lax`
only sends the cookie on **same-site** requests, and the deployed topology is not same-site:
the frontend is on `exam-roll.pages.dev` and the backend is on `examroll-api.onrender.com` —
two different registrable domains (`pages.dev` and `onrender.com` are both on the Public Suffix
List, so every subdomain under them is its own independent site as far as the browser is
concerned).

**Why it happened.** Frontend and backend were deployed to two separate free-tier hosts
independently, before auth existed, with no domain-topology constraint in mind at the time.

**What it would have cost to ignore.** The browser would silently withhold the session cookie
on every API call and on the WebSocket handshake. Every authenticated request would return 401
with no indication of why; the WebSocket would simply never connect, since browsers expose
almost nothing about a failed handshake. This is the kind of failure that looks like a bug in
the auth code when the actual cause is deployment topology — expensive to debug after the fact.

**What we decided and why.** FastAPI serves the built `frontend/dist` itself, alongside
`/api/v1/*` and the WebSocket route. This makes the app and API the literal same origin, not
just the same site — so `SameSite=Lax` works exactly as designed, with zero CSRF token
machinery to build or maintain, and the WebSocket handshake carries the cookie automatically.
It costs nothing and needs no DNS, unlike the two alternatives considered:
- **Buy a custom domain** (`examroll.com` + `api.examroll.com`) — same-site, so it would also
  work, and keeps a CDN in front of the frontend bundle. But it costs money, has DNS
  registration/propagation lead time, and doesn't remove the CORS allowlist to maintain.
- **Keep the split hosts, set `SameSite=None`, add a double-submit CSRF token** — the
  documented fallback in `FUTURE_UNIFIED.md` §7.1 "if a custom domain is not available." Rejected
  because a `SameSite=None` cookie here is a genuine third-party cookie, which Safari blocks by
  default and other browsers are moving toward blocking — so the extra CSRF/WebSocket-ticket
  machinery could be built correctly and still silently fail for some users.

This reverses `FUTURE_UNIFIED.md` §7.1's original "chosen: custom domain" resolution. The
auth code itself (`app/auth.py`, the cookie attributes, `current_user`/`require_org`) is
**unchanged** by this decision — same-origin and same-site both use identical
`samesite="lax"` session-cookie code. A custom domain remains a valid upgrade path later
(e.g. once handing the URL to a real college matters); if adopted, only deployment
configuration changes, not application code.

**Trade-off accepted.** Same-origin serving couples frontend and backend into one deployed
service — no CDN in front of the React bundle, and a cold start on Render's free tier (the
container sleeps after ~15 min idle) now delays the page load itself, not just the first API
call. This is a hosting problem with hosting answers (keep-alive ping, a paid tier, Cloudflare
in front) to be addressed at actual deploy time — not a reason to reopen this decision now.

---

## 2026-09-19 — Production deployment config left untouched this phase

**What happened.** Same-origin serving (above) changes what a "correct" production deployment
looks like — one service instead of the current Cloudflare Pages + Render split described in
`DEPLOYMENT.md`/`render.yaml`.

**Why it happened.** This phase's scope is auth + storage migration + the exam-model bridge,
not deployment. The user was explicit that v1 is live and working and should not be disturbed.

**What it would have cost to ignore.** Touching `DEPLOYMENT.md`/`render.yaml`/Cloudflare Pages
config now risks breaking the deployed v1 for no benefit — this phase's work isn't deployed yet.

**What we decided and why.** Same-origin serving is built and verified locally only
(`npm run build` + `uvicorn`, manual hard-refresh test). Deployment config changes are deferred
to the "v2 deploy" step the user already described as coming after the new features are built
and tested.

---

## 2026-09-19 — Local dev keeps SQLite; production moves to Postgres

**What happened.** Migrating to Postgres (below) raises the question of whether local
development should also move off SQLite, so migrations are tested against the same engine
they'll run against in production.

**Why it happened.** SQLite and Postgres diverge on constraint/ALTER handling — a migration
that works on one dialect isn't guaranteed to work on the other without care.

**What it would have cost to ignore either way.** Moving local dev to Postgres too would add
real setup friction (Docker or a second cloud DB per developer) for a project that currently
runs with zero local infrastructure beyond `pip install` / `npm install`. Keeping SQLite without
accounting for the dialect gap risks a migration that passes locally and fails against the real
Postgres target.

**What we decided and why.** Local dev keeps `aiosqlite`; Alembic migrations run in batch mode
(`render_as_batch=True` in `env.py`) so `ALTER TABLE` operations that SQLite can't do directly
(like adding a `NOT NULL` column) still apply via SQLite's create-copy-swap emulation. The test
suite is unaffected either way — `conftest.py` builds its schema directly via
`Base.metadata.create_all` and never invokes Alembic. CI gains a dedicated Postgres
service-container job that runs `alembic upgrade head` from empty, which is the actual
safety net against dialect drift (see next entry).

---

## 2026-09-19 — CI gains a Postgres migration smoke job

**What happened.** Alembic migrations are authored and tested locally against SQLite (per the
entry above), but ship against Postgres in production (Supabase).

**Why it happened.** Same root cause as above — dialect divergence between the two engines.

**What it would have cost to ignore.** A migration could pass every local check and still fail
the moment it's actually run against Postgres — discovered only when deploying to Supabase,
the most expensive place to find out.

**What we decided and why.** Added a CI job that starts a `postgres` service container and runs
`alembic upgrade head` from an empty database on every push — the only way to catch a
migration that doesn't actually apply to Postgres before it reaches Supabase.

---

## 2026-09-19 — No historical-data backfill in the exam-model migration

**What happened.** The exam-model migration (`0002_exam_model`) creates relational tables
(`Student`, `Enrollment`, etc.) to replace the JSON-blob extraction data. The question was
whether to backfill existing completed jobs' `students_json`/`subjects_json` into the new
tables, or leave historical jobs relational-empty.

**Why it happened.** `FUTURE_UNIFIED.md` §13.4 describes a backfill step as part of this
migration for a system with real accumulated data to migrate.

**What it would have cost to ignore either way.** Building a backfill (with the idempotency
and row-count-assertion safeguards §13.4 requires) is real work; skipping it loses any
historical job data that isn't re-uploaded.

**What we decided and why.** No backfill. Production has run on ephemeral disk with documented
data loss on every restart/redeploy (see `PROGRESS.md`'s OOM/502 incident notes) — there is no
durable job history worth migrating. New data flows through the new `persisting_rows` pipeline
stage going forward; any job a user cares about can simply be re-uploaded post-migration.

---

## 2026-09-19 — First admin user created by a one-shot script, not a signup flow

**What happened.** Auth requires at least one `User` row to exist before anyone can log in, but
there's no signup UI (none is planned — this is an invite-only, single-pilot-org system for now).

**Why it happened.** Bootstrapping the very first account is a different problem from ongoing
user management, which doesn't exist yet either.

**What it would have cost to ignore.** Building a signup UI for a system that will only ever
have staff accounts created by an admin is unnecessary surface area for this phase.

**What we decided and why.** A standalone `backend/scripts/create_admin.py`, run manually once
per environment (local, then again against the Supabase production DB after migration `0001`
is applied there). Kept out of the Alembic migration itself — seed *data* doesn't belong in a
schema migration, and keeping it separate means re-running migrations can never risk
re-creating or duplicating the admin user.

---

## 2026-09-19 — The pilot organization *is* the legacy-backfill org, not a separate one

**What happened.** Migration `0001_add_tenancy` needs to backfill a value into the new
`Job.org_id NOT NULL` column for any pre-auth rows, which `FUTURE_UNIFIED.md`'s original §7.2
design does by creating a throwaway "Legacy (pre-auth)" organization.

**Why it happened.** The original design assumed multiple real organizations might eventually
need to be disentangled from a shared legacy bucket.

**What it would have cost to ignore.** Creating a separate throwaway "legacy" org plus a
distinct "real" pilot org adds bookkeeping with no present benefit — this app has exactly one
tenant (the pilot exam centre) and no near-term plan for a second.

**What we decided and why.** The org created by `0001`'s backfill *is* the real pilot centre
(with its actual `centre_code`/`university_name` where already known, else a placeholder
updated once known) rather than a separate legacy org plus a real one created later. This
matches `FUTURE_UNIFIED.md`'s own 2026-09-18 amendment to §7.2, which reaches the same
conclusion under the "pilot-first" sequencing this project adopted.

---

## 2026-09-19 — Stale `.gitignore` rule would have silently excluded every migration

**What happened.** While wiring up Alembic, `.gitignore` was found to contain a rule
`alembic/versions/` — added at some earlier point, apparently in anticipation of Alembic,
before it was actually set up. If left in place, it would have silently excluded every
migration file (`0000_baseline.py` and everything after it) from every future commit.

**Why it happened.** The rule was speculative — written before there was any
`alembic/versions/` directory to test it against, so nothing ever exercised it.

**What it would have cost to ignore.** A migration history that looks complete locally
(the files exist on disk, `alembic upgrade head` works) but is entirely absent from the
repository — every clone, every CI run, and every deploy would be missing the actual
schema history, discovered only when someone else tried to run `alembic upgrade head`
against an empty database and got nothing.

**What we decided and why.** Removed the rule. Migration files are schema history, not
build output — they belong in version control the same way the ORM models do. Verified
`git add -n backend/alembic/` now stages exactly `env.py`, `script.py.mako`, `README`, and
`versions/0000_baseline.py`, with `__pycache__/` still correctly excluded by the existing
top-level rule.

---

## 2026-09-19 — `Secure` cookie flag needed to be environment-conditional

**What happened.** The session cookie was implemented exactly as designed — `httponly=True`,
`secure=True`, `samesite="lax"`. Login worked (200 OK, `Set-Cookie` present), but every
following request from the same test client came back `401 Unauthorized` as if no cookie had
ever been sent.

**Why it happened.** A `Secure` cookie is only sent back over an HTTPS connection, per RFC
6265. Real browsers special-case `localhost` as a "potentially trustworthy origin" and send
`Secure` cookies over plain `http://localhost` anyway — which is why this would have looked
fine in a real browser during local dev. httpx's test client (`ASGITransport`, base URL
`http://test`) follows the RFC strictly, with no such exception, and silently drops the
cookie rather than erroring — so the failure surfaced as an unrelated-looking 401 on the
request *after* a successful login, not as anything pointing at the cookie itself.

**What it would have cost to ignore.** Nothing broken in production (real HTTPS deployments
would never hit this), but the entire authenticated test suite would either have needed
hand-crafted cookies (bypassing the real `create_session`/`current_user` code path the tests
are supposed to exercise) or would have stayed permanently red — either silently weakening
exactly the tests meant to catch an auth regression.

**What we decided and why.** `secure=settings.app_env == "production"` instead of a hardcoded
`True`. Production is always served over HTTPS, so this never actually weakens the real
deployment — it only affects local dev and tests, both of which are plain HTTP by nature and
now get real, working session cookies through the real login flow.

---

## 2026-09-19 — Test DB engine needed `NullPool` for the WebSocket auth tests

**What happened.** Testing `authorize_ws` requires a real WebSocket handshake, which
httpx's `ASGITransport` (used by every other test in the suite) cannot do at all — it has
no WebSocket support. The only option is Starlette's synchronous `TestClient`, which runs
the ASGI app in its own background thread with its own event loop. A test needing both an
async fixture (to set up two separate logged-in orgs) and `TestClient` (to open the
WebSocket) failed with `sqlite3.OperationalError: no active connection`.

**Why it happened.** A pooled `aiosqlite` connection is tied to the event loop that created
it. The async test fixtures run on pytest-asyncio's loop; `TestClient` runs the app on a
different loop in its own thread. The default connection pool reused a connection across
that loop boundary, which aiosqlite does not support.

**What it would have cost to ignore.** The WebSocket auth tests — covering exactly the
scenario `authorize_ws` exists for, a foreign-org job producing the same closed connection
as a missing one — would have stayed flaky or unwritable, leaving the one part of auth that
can't reuse the HTTP 404-not-403 pattern effectively untested.

**What we decided and why.** `poolclass=NullPool` on the test engine: every connection
checkout opens a fresh `aiosqlite` connection rather than reusing one from a pool, so no
connection can ever be reused across a loop boundary in the first place. Session-scoped test
DB, in-process, so the minor overhead of not pooling is negligible.

---

## 2026-09-20 — `asyncpg` and `psycopg2` disagree on the SSL query-param name

**What happened.** Connecting Alembic to a real Neon Postgres database failed immediately with
`psycopg2.ProgrammingError: invalid dsn: invalid connection option "ssl"`, even though the exact
same connection string worked perfectly for the app's own driver (`asyncpg`) seconds earlier via a
direct connection test.

**Why it happened.** `asyncpg` (the app's async driver) expects the SSL setting as `ssl=require`
in the URL's query string. `psycopg2` (which Alembic's migration runner needs, since Alembic can't
drive an async engine — see the earlier `env.py` entry) expects the standard libpq name,
`sslmode=require`, instead. Neon's own connection string uses `sslmode=require` by default — the
correct form for `psycopg2`, but not for `asyncpg`. `alembic/env.py`'s `_sync_database_url()`
already swapped the driver prefix (`postgresql+asyncpg:` → `postgresql+psycopg2:`) when deriving
Alembic's sync URL, but passed the rest of the URL through untouched, so the query string kept
`asyncpg`'s spelling even after the driver name changed.

**What it would have cost to ignore.** Every migration against real Postgres would fail at the
connection step, immediately, with an error that names a plausible-looking connection option
("ssl") rather than pointing at the actual driver mismatch — a confusing first real-Postgres
experience for anyone following the setup.

**What we decided and why.** `_sync_database_url()` now also translates `ssl=require` →
`sslmode=require` when converting to the `psycopg2` URL, alongside the driver-prefix swap it
already did. Verified against the real Neon database: `alembic upgrade head` applied all three
migrations cleanly, and a direct query confirmed the correct schema landed (12 tables, `org_id`
NOT NULL, `exam_id`/`college_id` nullable).

---

## 2026-09-20 — `moto` doesn't intercept a custom S3 `endpoint_url`

**What happened.** Testing the R2 storage backend with `moto` (which mocks the S3 API in-process
for automated tests) worked for a plain `boto3.client("s3")` with no endpoint override, but every
call through a client configured with R2's actual `endpoint_url`
(`https://<account_id>.r2.cloudflarestorage.com`) failed with a genuine SSL handshake error against
that hostname — meaning the request was actually leaving the process and hitting the network,
not being mocked at all.

**Why it happened.** `moto`'s HTTP interception matches requests against botocore's known AWS
endpoint URL patterns. A custom domain like R2's account-specific endpoint doesn't match any of
those patterns, so `moto` has nothing to intercept and the request goes out for real — to a
hostname that (in the test's case) doesn't resolve to anything real.

**What it would have cost to ignore.** Either the R2 backend's actual logic (upload/download/
delete/prefix-delete, especially the pagination and batch-delete behavior for cleaning up a job's
files) would have shipped with zero automated coverage, or tests would have silently made real
network calls during every CI run — slow, flaky, and pointless against a nonexistent host.

**What we decided and why.** Tests patch `_r2._client` to construct a `boto3` client with NO
custom endpoint (which `moto` mocks correctly), while every function body under test —
`upload_local_file`, `download_bytes`, `object_exists`, `delete_object`, `delete_prefix`'s
pagination/batch-delete loop — runs completely unmodified. That's the actual logic that could have
a bug. The `endpoint_url`/`region_name="auto"` wiring itself is a single f-string in `_client()`,
low-risk by inspection, and gets its real verification separately: a live check against the user's
actual R2 bucket once credentials exist, the same two-layer approach (automated logic tests +
one live check) already used for the Postgres migration.

---

## 2026-09-20 — Uploaded files and generated outputs moved off local disk to Cloudflare R2

**What happened.** Uploaded attestation sheets and generated Excel outputs lived on the server's
local disk (`uploads/{job_id}/`), permanently, with nothing cleaning them up. On the current
deployment topology this caused real memory/disk pressure on the running server — every upload
and every export added another file that never went away.

**Why it happened.** The app was originally built as a single-server local tool; disk-backed
storage was the simplest thing that worked at the time, and cleanup was explicitly deferred (this
matches a known gap already named in the project's own roadmap — a retention janitor was always
planned, just not built yet).

**What it would have cost to ignore.** The disk fills up in direct proportion to usage, with no
ceiling — every exam batch uploaded and every Excel exported is one more file that stays forever.
On a small/shared-resource host this becomes an outage, not just a cleanup annoyance.

**What we decided and why.** Object storage (Cloudflare R2), not a database BLOB column — a
database is the wrong tool for multi-MB files (cost, backup size, and query-optimized storage
engines aren't built for streaming binary blobs). R2 specifically: zero egress fees (every
download costs nothing, ever, no allowance to track) and a mature, stable product — chosen over
Neon's own newer object storage offering (which is S3-compatible too, and genuinely would have
worked, but is in beta) specifically because this data is real student records, not something to
build on a beta dependency for. Full comparison discussed with the user before deciding.

**How it was built**, to keep the change reversible and low-risk:
- `app/services/storage/` — one module (`upload_local_file`, `upload_bytes`, `download_bytes`,
  `object_exists`, `delete_object`, `delete_prefix`) with two interchangeable backends chosen on
  every call by whether R2 is configured, not fixed once at import — `_local.py` (the fallback,
  used whenever R2 settings are unset) and `_r2.py` (boto3, wrapped in `asyncio.to_thread()` the
  same way this codebase already handles other blocking I/O). Every router and the pipeline call
  only the top-level dispatch, never a backend directly, and never touch `os`/`shutil` for
  source/output files anymore.
- Zero new database migration: `Job.file_path` and `OutputFile.filepath` already were plain
  string columns — they now hold a storage KEY (`{job_id}/{filename}`) instead of a local path.
  Both backends interpret the same key consistently, so nothing else had to change shape.
- Local disk is not eliminated entirely: incoming uploads are still briefly staged to a real
  temp directory (`tempfile.mkdtemp()`, never `UPLOAD_DIR` — see the local-fallback note below)
  because the existing chunked-async-upload code can't hand bytes directly to the synchronous R2
  client. That staged copy is deleted immediately after the push to the storage backend, on
  success or failure — local disk is scratch space for the duration of one upload, not storage.
- Extraction already worked from in-memory bytes (`pdfplumber`/`openpyxl` both open a `BytesIO`)
  — confirmed by reading the actual extractor code rather than trusting an older note in
  `PROGRESS.md` that turned out to describe an earlier version. This meant the pipeline needed no
  second local copy at all to process a file: it fetches bytes from storage directly.
- The local-disk fallback (`_local.py`) matters for more than just tests: if R2 settings are
  ever unset (misconfigured, or a deliberate choice), `upload_dir` becomes the real permanent
  store again, exactly as before this change — deleting the transient staging copy in that mode
  would have deleted the only copy, which is why staging uses a genuinely separate temp
  directory rather than `upload_dir` itself.

**Testing**: the R2 backend has real automated coverage via `moto` (mocks the S3 API in-process —
see the separate DECISIONS.md entry on its custom-`endpoint_url` limitation and how that was
worked around), not just the local-disk fallback tests. Full live verification — upload the real
167-page attestation PDF, confirm the exact known-good extraction count, export, re-download
byte-identical, delete, confirm disk fully clean — was run end-to-end in local-disk mode; the same
flow against a real R2 bucket is verified once real credentials exist, matching the same
two-layer approach (automated logic tests + one live check) already used for the Postgres
migration.

---

## Live R2 + Neon verification, and a test-isolation bug it surfaced (2026-09-20)

**Problem**: ran the same live end-to-end sequence used for local-disk mode (upload the real
167-student attestation PDF → process → export → re-download → delete) against genuinely real
Neon Postgres and real Cloudflare R2, using the credentials the user provided in `.env`. Every
step passed: the source file landed at the expected R2 key, extraction matched the pinned
167-student/15-subject count, the exported `.xlsx` round-tripped byte-identical on re-download,
`DELETE /api/v1/jobs/{id}` returned 204, and both the source and output keys were confirmed gone
from R2 afterward (direct `object_exists` calls, both `False`).

**A follow-up full `pytest` run then failed** one assertion in `test_storage.py`
(`test_dispatch_uses_local_backend_when_r2_unconfigured`) that documents an assumption: "this
test suite never sets R2 credentials, so `object_storage_enabled` is already `False`." That
assumption broke the moment `.env` gained real R2 credentials, because `Settings` (`config.py`)
loads `.env` unconditionally — nothing in the test suite ever forced R2 back off.

**Why this was a bigger problem than one failing assertion**: `conftest.py`'s session-scoped
`setup_test_db` fixture isolates `upload_dir` into a tmp directory, but never touched the four
R2 settings. That meant `object_storage_enabled` was `True` for the *entire* test session, so
every test hitting `/api/v1/upload` or `/api/v1/export` through the app (not just
`test_storage.py`) — `test_routers.py`, `test_tenancy.py`, `test_exam_model.py`,
`test_extraction_correctness.py` — was routing through the real `_r2` backend and writing to the
live production bucket over the network on every `pytest` run, not a mock. Listing the bucket
confirmed it: 60 stray objects (tiny placeholder test PDFs and their generated `.xlsx` outputs,
all timestamped from one earlier test run) were sitting in `examroll-uploads`.

**Fix**: `setup_test_db` now also resets all four `r2_*` settings to `""` at session start,
regardless of what `.env` contains, so local disk is the default for the whole suite again. Tests
that specifically want R2 coverage still get it: `test_storage.py`'s `r2_settings`/`moto_bucket`
fixtures `monkeypatch` those same four fields back on per-test, and `monkeypatch` auto-reverts
after each test — so they compose correctly with the new session-level reset instead of fighting
it. Confirmed by re-running the full suite twice (134 passed, 0 failed) and listing the real
bucket immediately after: 0 objects both times.

**Cleanup**: the 60 stray pre-existing objects were confirmed to be nothing but test fixtures
(all under 25 bytes, or generated `.xlsx` files from the same test run) and deleted from the real
bucket after explicit user confirmation, since a bulk delete against production infrastructure is
exactly the kind of action this project treats as requiring a stop-and-ask rather than
proceeding autonomously.

**Lesson for future phases**: any time real credentials get written to `.env` for a live
verification step, immediately re-run the full test suite and check whether a previously-safe
"this is always false/unset in tests" assumption just became false — `.env`-based settings are
session-global, and a session-scoped test fixture that isolates one field (`upload_dir`) can
silently fail to isolate a sibling field (`r2_*`) that gates the same code path.

---
