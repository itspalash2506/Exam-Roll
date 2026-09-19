import uuid
from datetime import datetime, timezone
# Aliased: ExamSession has columns literally named `date` and `time`-typed
# ones, and an annotation `Mapped[date]` on an attribute named `date` is the
# kind of shadowing that resolves differently under PEP 649 than before it.
from datetime import date as _date, time as _time
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    String,
    Integer,
    Text,
    Time,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.room_capacity import DEFAULT_SEATS_PER_BENCH, room_capacity


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    """The tenancy boundary (DECISIONS.md, 2026-09-19; FUTURE_UNIFIED.md §7,
    §13). All data isolation is by org, not by user — staff at one exam
    centre share a workspace. Every other table's rows belong to exactly one
    Organization; every query in every router MUST filter by it."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # §13.2's amended columns — the tenant is an exam CENTRE (of a
    # university), not "a college", so these are the two other identifying
    # facts on every printed docket. Nullable for now: a pilot org created by
    # migration 0001 may not have real values yet.
    centre_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    university_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # Retention window in days. Kept as a single value for this phase; §16.5
    # replaces it with three separate tiers (source files / raw AI text /
    # records) once retention enforcement is actually built — not yet.
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # Per-org opt-out from sending document text to the third-party Groq API.
    ai_processing_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    # argon2id via argon2-cffi. Never bcrypt (silently truncates at 72 bytes),
    # never a bare/unsalted hash.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # admin|member for this phase; widens to admin|controller|clerk (§16.4)
    # once roles are actually enforced anywhere — not yet, so keeping it
    # narrow rather than pretending three roles already mean something.
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthSession(Base):
    """Server-side session, not a JWT — a logout or a compromised account is
    one UPDATE (revoked_at) away, with no revocation-list machinery to build.
    Named AuthSession, not Session, to avoid colliding with a future
    ExamSession model (FUTURE_UNIFIED.md §13.2)."""

    __tablename__ = "auth_sessions"

    # The cookie carries a random token; only its SHA-256 is stored here, so
    # a DB read alone never yields a usable credential.
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Exam model (WS-G, FUTURE_UNIFIED.md §13) ─────────────────────────────────
# The relational bridge extraction needs before the seating planner (and
# later features) can exist: today's pipeline only ever writes JSON blobs
# (ExtractedData.students_json/subjects_json) — a roster query like
# "Enrollment JOIN SessionPaper" has nothing to run against without real
# rows. §13.1's design rules, reproduced here rather than re-derived:
#   1. Identity of a paper is (exam, exam_code), NEVER the subject name —
#      names repeat across schemes, courses and years.
#   2. Identity of a student is (org, roll_number).
#   3. Every table here carries org_id NOT NULL from creation (0002 adds no
#      data to backfill into these six tables — see DECISIONS.md, no
#      historical-data-backfill entry, 2026-09-19).


class College(Base):
    """Where a student is enrolled — distinct from Organization (the exam
    CENTRE). §12.1: the workbook this design is based on lists ten colleges
    under one centre, which is the evidence the tenant is a centre, not a
    college."""

    __tablename__ = "colleges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(50), nullable=True)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    programme_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    semester: Mapped[str | None] = mapped_column(String(100), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sticker_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")  # draft|active|closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SubjectOffering(Base):
    """A paper within one exam. Identity is (org, exam, exam_code) — see the
    module-level note above. `subject_name` deliberately has no UNIQUE
    constraint of its own: the same name can legitimately appear on two
    different exam_codes (different schemes/years), and a NAME conflict on
    the SAME exam_code is recorded, not merged (§14.4 — see
    processor.py's persisting_rows)."""

    __tablename__ = "subject_offerings"
    __table_args__ = (
        UniqueConstraint("org_id", "exam_id", "exam_code", name="uq_offering_org_exam_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    exam_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exam_code: Mapped[str] = mapped_column(String(20), nullable=False)
    course_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    subject_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    paper_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    group_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scheme_year: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Student(Base):
    """Identity is (org, roll_number) — §13.1 rule 2. `roll_sort_key` is
    computed once at insert (utils/roll_sort.py) so every future query can
    `ORDER BY roll_sort_key` and get the same order a numeric-aware sort
    would give, without re-deriving it per query."""

    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("org_id", "roll_number", name="uq_student_org_roll"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    roll_number: Mapped[str] = mapped_column(String(30), nullable=False)
    roll_sort_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    college_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("colleges.id", ondelete="SET NULL"), nullable=True
    )
    course_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="regular")
    admission_year: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Job(Base):
    __tablename__ = "jobs"
    # ix_jobs_org_created backs list_jobs' `WHERE org_id = :org_id ORDER BY
    # created_at DESC` — declared here (not just as a raw migration op) so
    # the ORM metadata matches the DB and a future autogenerate diff doesn't
    # propose dropping it as drift (found the hard way while writing 0002 —
    # DECISIONS.md, 2026-09-19).
    __table_args__ = (Index("ix_jobs_org_created", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    # NOT NULL and indexed — a nullable org_id would reintroduce exactly the
    # bug this fixes, since a NULL never matches a `WHERE org_id = :org_id`
    # filter (DECISIONS.md, 2026-09-19).
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Which exam/college this attestation sheet is for — chosen by the
    # uploader (§14.3's picker), never guessed from the sheet itself. Both
    # nullable: an existing job predating this column, or a batch uploaded
    # before the picker is enforced client-side, is not retroactively
    # assigned one (DECISIONS.md, 2026-09-19 — no historical-data backfill).
    exam_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("exams.id", ondelete="SET NULL"), nullable=True
    )
    college_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("colleges.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Multi-file batches: JSON array of the original uploaded filenames, and how
    # many files the job covers. `filename` keeps a human summary for back-compat
    # (the single filename, or "N files (first, …)" for a batch). All columns are
    # nullable so a pre-existing DB row keeps working across the Alembic
    # migration that adds them (schema changes go through alembic/versions/
    # now, not a boot-time auto-migration — DECISIONS.md, 2026-09-19).
    source_files: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    # JSON array of per-file processing warnings (e.g. "File 2 (x.pdf): no roll
    # numbers found") so the frontend can surface them honestly after the job.
    processing_warnings: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AI classifier notes (plus any mixed-document-type warning appended).
    ai_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    document_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    course: Mapped[str | None] = mapped_column(String(200), nullable=True)
    semester: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exam_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    total_students: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    extracted_data: Mapped["ExtractedData | None"] = relationship(
        "ExtractedData", back_populates="job", uselist=False, cascade="all, delete-orphan"
    )
    output_files: Mapped[list["OutputFile"]] = relationship(
        "OutputFile", back_populates="job", cascade="all, delete-orphan"
    )


class Enrollment(Base):
    """A student's enrollment in one paper. Upserted by processor.py's
    persisting_rows stage — a re-upload of the same sheet resolves to the
    same (student_id, offering_id) pair and is reported as "already
    enrolled" rather than duplicated (§14.5)."""

    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("student_id", "offering_id", name="uq_enrollment_student_offering"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    student_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True
    )
    offering_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subject_offerings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Traceability: which upload created/last-confirmed this enrollment.
    source_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    # A per-enrollment override of the student's general status (e.g. ATKT
    # for this one paper only) — null means "use Student.status".
    status_override: Mapped[str | None] = mapped_column(String(20), nullable=True)


class ExtractedData(Base):
    __tablename__ = "extracted_data"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=False)
    students_json: Mapped[str] = mapped_column(Text, nullable=False)
    subjects_json: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text_sample: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped["Job"] = relationship("Job", back_populates="extracted_data")


# ── Seating planner (WS-H, FUTURE_UNIFIED.md §13.2, §15.1) ──────────────────
# Rooms and sessions only. The plan itself (SeatingPlan / SeatingPlanRoom /
# SeatAssignment, migration 0004) and attendance (0005) are later gates —
# these three tables are what the room library and session setup screens
# (§15.1, §15.2 steps 1–3) need, and nothing more.


class Room(Base):
    """A physical exam room, modelled as a LIST OF COLUMNS each with its own
    seat count — not `rows × cols` (§12.1, §15.1).

    The workbook this design comes from has `ROOM - 5 LIBRARY HALL` with
    columns of 3, 13, 13 and 4 seats, and `ROOM NO. 4` as two blocks of 5 and
    2 columns. A rectangular model cannot represent either without inventing
    seats that do not exist, and an invented seat is a candidate sent to a
    place they cannot sit. The sheet's "Row 1".."Row 5" headers are physical
    COLUMNS of benches running front-to-back; `seat_columns[].label` keeps
    whatever the centre calls them so the printed chart matches the room.

    Index convention, stated once and depended on by the allocator (§15.4):
    `blocked_seats` entries are **1-based on both axes** — `{"col": 1,
    "seat": 1}` is the first seat of the first column. See
    utils/room_capacity.py, which owns the capacity arithmetic and the
    "is this a real seat" predicate.

    A `seats` count is a number of BENCHES; `seats_per_bench` (1–3) is how
    many candidates share one. Blocking is per bench: a blocked entry removes
    every place on that bench, which is why §15.1's formula multiplies last.
    """

    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    building: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Rooms persist across exams; one used in a published plan is deactivated,
    # never deleted (§15.1), so this flag — not a DELETE — is how a room leaves
    # the picker.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Display/allocation order of the room library ("Room 1" before "Room 10",
    # labs last). Ties fall back to name at query time.
    sort_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # [{"label": "Row 1", "seats": 6}, …] — order IS the column order.
    seat_columns: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    # [{"col": 1, "seat": 4}, …] — 1-based, see the class docstring.
    blocked_seats: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    seats_per_bench: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_SEATS_PER_BENCH
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def capacity(self) -> int:
        """(Σ seats − |blocked|) × seats_per_bench — §15.1.

        A PROPERTY, not a column: §13.1 rule 5 is that derived numbers are
        derived. A stored capacity is a number that can disagree with the
        seats it claims to count, and the first person to notice would be a
        candidate standing in a room with no seat left.

        SQLAlchemy's generic JSON type deserializes to native Python lists on
        both SQLite (json.loads over TEXT) and Postgres (asyncpg JSON codec),
        so this reads identically on either backend. Note that in-place
        mutation of these lists is not tracked by the ORM (no MutableList) —
        assign a new list to change them, which is what an editor PATCH does
        anyway.
        """
        # A Room() built in Python still has None in every column whose
        # default the ORM only applies at INSERT. Falling back to the same
        # literal the column declares is not a silent default — it is what
        # the row will hold a moment later — and it keeps a capacity chip in
        # an unsaved editor from raising.
        per_bench = self.seats_per_bench
        if per_bench is None:
            per_bench = DEFAULT_SEATS_PER_BENCH
        return room_capacity(self.seat_columns, self.blocked_seats, per_bench)


class ExamSession(Base):
    """One centre day-shift: `(date, shift)` (§13.2, §15.2 step 2).

    Named ExamSession, not Session, to avoid colliding with AuthSession (and
    with SQLAlchemy's own Session). A session belongs to the CENTRE's day,
    not to one Exam: §12.1 found P.G. Sem 4 and B.B.LLB Sem 10 sitting in the
    same building on the same morning, so the papers it carries (see
    SessionPaper) may come from several different Exam rows.
    """

    __tablename__ = "exam_sessions"
    __table_args__ = (
        UniqueConstraint("org_id", "date", "shift", name="uq_session_org_date_shift"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    date: Mapped[_date] = mapped_column(Date, nullable=False)
    # "Morning" / "Afternoon" — free text rather than an enum: the label is
    # printed verbatim on the docket and differs per centre.
    shift: Mapped[str] = mapped_column(String(50), nullable=False)
    # Wall-clock times of the sitting ("11 -- 2" on the workbook's dockets).
    # Nullable: the shift name alone is enough to identify the session.
    start_time: Mapped[_time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[_time | None] = mapped_column(Time, nullable=True)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # A student enrolled in >=2 papers of this session (PUT .../papers
    # detects this on save — §15.2 step 4). Each entry:
    # {"student_id", "roll_number", "exam_codes": [...], "acknowledged": bool}.
    # Publishing (F04) is refused while any entry here is unacknowledged —
    # not yet enforced since publishing doesn't exist yet, but the storage
    # shape is decided now so F04 doesn't have to re-litigate it.
    clashes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)


class SessionPaper(Base):
    """Which papers sit in one session's slot — the M:N join between
    ExamSession and SubjectOffering (§13.2, §15.2 step 3). The session's
    roster is `Enrollment ⋈ SessionPaper`.

    Carries its own `id` and `org_id` rather than being a pure association
    table, matching Enrollment (the codebase's existing join-table precedent):
    §13.1 rule 3 wants org_id NOT NULL on every table so Gate M's tenant
    filter only ever adds a WHERE, never a column, and a surrogate key keeps
    the row addressable by a single id from the API layer.
    """

    __tablename__ = "session_papers"
    __table_args__ = (
        UniqueConstraint("session_id", "offering_id", name="uq_session_paper"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("exam_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    offering_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subject_offerings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )


class OutputFile(Base):
    __tablename__ = "output_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False, default="xlsx")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    filepath: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size_kb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    job: Mapped["Job"] = relationship("Job", back_populates="output_files")
