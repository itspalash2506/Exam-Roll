from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field


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


# ── Backward-compat aliases used by scaffold router stubs ──────────────────
# These will be replaced when Prompt 6 rewrites the routers.

class ApiResponse(BaseModel):
    data: Any = None
    error: str | None = None


class JobOut(JobDetailResponse):
    pass


class JobListOut(JobResponse):
    pass
