import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Multi-file batches: JSON array of the original uploaded filenames, and how
    # many files the job covers. `filename` keeps a human summary for back-compat
    # (the single filename, or "N files (first, …)" for a batch). All columns are
    # nullable so pre-existing SQLite rows keep working (init_db auto-adds them).
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
