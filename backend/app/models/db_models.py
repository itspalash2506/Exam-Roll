import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


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


class Job(Base):
    __tablename__ = "jobs"

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


class ExtractedData(Base):
    __tablename__ = "extracted_data"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=False)
    students_json: Mapped[str] = mapped_column(Text, nullable=False)
    subjects_json: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text_sample: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped["Job"] = relationship("Job", back_populates="extracted_data")


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
