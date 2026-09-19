from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.room_capacity import (
    DEFAULT_SEATS_PER_BENCH,
    SEATS_PER_BENCH_CHOICES,
    as_mappings,
    find_duplicate_blocked_seats,
    find_invalid_blocked_seats,
    room_capacity,
)


# ── Core extracted data ─────────────────────────────────────────────────────

class StudentStatus(StrEnum):
    """Candidate category on an attestation sheet (FUTURE.md §14.1).

    `other` is the sink for spellings the allowlist does not know — it is never
    a silent default: the pipeline records a warning naming the count, because
    a silent default is the P0-1 failure class over again.
    """

    REGULAR = "regular"
    EX = "ex"
    ATKT = "atkt"
    PRIVATE = "private"
    OTHER = "other"


class SubjectEntry(BaseModel):
    code: str
    name: str
    # §14.2 — optional at extraction time; the code → exam_code mapping is
    # entered once per exam in the Paper setup screen (Gate F) when the sheet
    # carries only the subject code.
    exam_code: str | None = None
    paper_no: str | None = None
    group_label: str | None = None


class StudentRecord(BaseModel):
    roll_number: str
    subjects: list[str]
    # §14.1 — name is optional on outputs (Q11), so a missing one is an empty
    # string with no warning. A missing status is NOT silent; see StudentStatus.
    name: str = ""
    status: StudentStatus = StudentStatus.REGULAR
    admission_year: int | None = None
    # False when the sheet carried no status text for this student and `status`
    # is therefore the `regular` default. The pipeline counts these and warns;
    # §14.1 is explicit that a silent default is the P0-1 failure class again.
    status_explicit: bool = True


class SubjectConflict(BaseModel):
    """Same code, two different names within one batch (FUTURE.md §14.4).

    Neither name is picked. The conflict is recorded so the review step can
    show both and let the user choose; auto-picking the longer name (the old
    behaviour) silently renamed subjects in the delivered workbook.
    """

    code: str
    names: list[str]

    def as_warning(self) -> str:
        shown = " / ".join(f"'{n}'" for n in self.names)
        return (
            f"Subject {self.code} has conflicting names ({shown}) — "
            f"none was chosen; confirm the correct name before export."
        )


class ExtractedDataSchema(BaseModel):
    students: list[StudentRecord]
    subjects: list[SubjectEntry]
    source_file: str
    total_students: int
    document_type: str
    course: str | None = None
    semester: str | None = None
    exam_name: str | None = None
    ai_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    ai_notes: str | None = None


# ── Export ──────────────────────────────────────────────────────────────────

class StyleConfig(BaseModel):
    header_bg_color: str = "#1F4E79"
    header_font_color: str = "#FFFFFF"
    alt_row_color: str = "#D6E4F0"
    count_row_color: str = "#FFD700"
    font_name: str = "Arial"
    font_size: int = 10
    column_width: int = 26


class ExportRequest(BaseModel):
    job_id: str
    style_config: StyleConfig = Field(default_factory=StyleConfig)
    filename: str = "Subject-wise-Roll-Number-List"


# ── Job responses ───────────────────────────────────────────────────────────

class JobResponse(BaseModel):
    id: str
    filename: str
    status: str
    progress: int
    document_type: str | None = None
    total_students: int | None = None
    created_at: str
    error_message: str | None = None
    file_count: int = 1
    source_files: list[str] = []


class JobDetailResponse(JobResponse):
    extracted_data: ExtractedDataSchema | None = None
    output_files: list[dict] = []
    warnings: list[str] = []


# ── AI insight / upload ─────────────────────────────────────────────────────

class AIInsight(BaseModel):
    document_type: str
    course: str | None = None
    semester: str | None = None
    exam_name: str | None = None
    total_students: int
    subjects_detected: list[SubjectEntry]
    confidence: float
    notes: str
    suggested_outputs: list[str]


class UploadResponse(BaseModel):
    job_id: str
    message: str
    ai_insight: AIInsight | None = None


# ── Rooms (seating planner, WS-H, FUTURE_UNIFIED.md §15.1) ─────────────────
# The validation boundary for the room model. Everything downstream — the
# capacity chip in the editor, the "required seats / available seats" bar in
# session setup (§15.2), the allocator (§15.4) — assumes a room's JSON is
# internally consistent. It is consistent because it could not be saved
# otherwise; that assumption is made true HERE and nowhere else.


class SeatColumnSpec(BaseModel):
    """One physical column of benches. `seats` counts benches down the
    column; `label` is what the centre calls it on the printed chart
    ("Row 1" — the sheet's rows ARE columns, see Room's docstring)."""

    label: str = ""
    seats: int

    @field_validator("seats")
    @classmethod
    def at_least_one_seat(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                f"a seat column must have at least 1 seat, got {v} — "
                "remove the column instead of giving it zero seats"
            )
        return v


class BlockedSeatSpec(BaseModel):
    """A bench taken out of service (the `x` cells in the source workbook).

    **1-based on both axes**: `{"col": 1, "seat": 1}` is the first seat of
    the first column. The allocator reads these with the same base — see
    utils/room_capacity.py.
    """

    col: int = Field(ge=1)
    seat: int = Field(ge=1)


class RoomCreate(BaseModel):
    """Create/replace payload for a Room. Both creation routes in §15.1 —
    the "generate N identical rooms" dialog and the per-room editor — produce
    this same shape; there is one room model, not two."""

    name: str = Field(min_length=1, max_length=200)
    building: str | None = None
    is_active: bool = True
    sort_priority: int = 0
    seat_columns: list[SeatColumnSpec]
    blocked_seats: list[BlockedSeatSpec] = []
    seats_per_bench: int = DEFAULT_SEATS_PER_BENCH
    notes: str | None = None

    @field_validator("seat_columns")
    @classmethod
    def at_least_one_column(cls, v: list[SeatColumnSpec]) -> list[SeatColumnSpec]:
        if not v:
            raise ValueError(
                "seat_columns must not be empty — a room with no columns has "
                "no seats and cannot hold an exam"
            )
        return v

    @field_validator("seats_per_bench")
    @classmethod
    def known_bench_size(cls, v: int) -> int:
        if v not in SEATS_PER_BENCH_CHOICES:
            allowed = ", ".join(str(c) for c in SEATS_PER_BENCH_CHOICES)
            raise ValueError(f"seats_per_bench must be one of {allowed}, got {v}")
        return v

    @model_validator(mode="after")
    def blocked_seats_must_be_real_seats(self) -> "RoomCreate":
        """A blocked seat that names no real seat is silently lost capacity —
        it would subtract from the total without the allocator ever skipping
        anything — so it is rejected, naming the offending entry."""
        columns = as_mappings(self.seat_columns)
        blocked = as_mappings(self.blocked_seats)

        invalid = find_invalid_blocked_seats(columns, blocked)
        if invalid:
            counts = [c["seats"] for c in columns]
            detail = "; ".join(
                f"entry {position} (col {col}, seat {seat})"
                for position, (col, seat) in invalid
            )
            raise ValueError(
                f"blocked_seats references seats this room does not have: {detail}. "
                f"Columns are 1..{len(counts)} with seat counts {counts}; "
                "col and seat are both 1-based."
            )

        duplicates = find_duplicate_blocked_seats(blocked)
        if duplicates:
            detail = "; ".join(
                f"entry {position} (col {col}, seat {seat})"
                for position, (col, seat) in duplicates
            )
            raise ValueError(
                f"blocked_seats lists the same seat more than once: {detail}. "
                "A seat is either blocked or it is not; a repeat would make "
                "capacity disagree with the seats actually skipped."
            )
        return self

    @property
    def capacity(self) -> int:
        """The same arithmetic Room.capacity uses (one implementation, in
        utils/room_capacity.py), so the figure the editor shows before saving
        and the figure the saved room reports can never drift apart."""
        return room_capacity(
            as_mappings(self.seat_columns),
            as_mappings(self.blocked_seats),
            self.seats_per_bench,
        )


# ── Backward-compat aliases used by scaffold router stubs ──────────────────
# These will be replaced when Prompt 6 rewrites the routers.

class ApiResponse(BaseModel):
    data: Any = None
    error: str | None = None


class JobOut(JobDetailResponse):
    pass


class JobListOut(JobResponse):
    pass
