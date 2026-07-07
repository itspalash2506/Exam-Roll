from typing import Any
from pydantic import BaseModel, Field


# ── Core extracted data ─────────────────────────────────────────────────────

class SubjectEntry(BaseModel):
    code: str
    name: str


class StudentRecord(BaseModel):
    roll_number: str
    subjects: list[str]


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
