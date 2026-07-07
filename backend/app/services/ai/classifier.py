import logging

from app.schemas.schemas import AIInsight, SubjectEntry
from app.services.ai.groq_client import get_groq_client

logger = logging.getLogger(__name__)

_VALID_DOC_TYPES = {
    "attestation_sheet",
    "roll_list",
    "hall_ticket",
    "seating_arrangement",
    "attendance_sheet",
    "result_sheet",
    "excel_data",
    "unknown",
}

_SYSTEM_PROMPT = """You are a document classifier for Indian college/university exam department records.

Analyze the provided document text and return ONLY valid JSON — no explanation, no markdown.

Classify into exactly one document type:
- "attestation_sheet": lists students and their enrolled subjects for attestation
- "roll_list": roll number lists with student names
- "hall_ticket": individual student exam admit cards showing schedule
- "seating_arrangement": exam hall seating plans
- "attendance_sheet": attendance records marking students present/absent
- "result_sheet": result or mark sheets with scores or grades
- "excel_data": structured tabular data from spreadsheets
- "unknown": cannot determine

Detect ALL subject/paper codes (patterns like MBAN301, CS401, BBA201, PHY101, ENGG201, etc.).

Respond ONLY with this exact JSON structure:
{
  "document_type": "<one of the types above>",
  "course": "<full course name or null>",
  "semester": "<semester string e.g. '3rd Semester' or null>",
  "exam_name": "<exam identifier string or null>",
  "university": "<university name or null>",
  "total_students": <integer count estimate>,
  "subjects": [
    {"code": "<subject code>", "name": "<full subject name>"}
  ],
  "confidence": <float 0.0-1.0>,
  "notes": "<observations about the document, e.g. quality, unusual structure>",
  "suggested_outputs": ["<output type 1>", "<output type 2>"]
}"""


def classify_document(text_sample: str, filename: str) -> AIInsight:
    client = get_groq_client()
    snippet = text_sample[:3000]
    user_prompt = f"Filename: {filename}\n\nDocument text (first 3000 characters):\n{snippet}"

    result = client.complete_json(_SYSTEM_PROMPT, user_prompt)

    if not result:
        logger.warning("Classifier returned empty result for '%s'", filename)

    doc_type = result.get("document_type", "unknown")
    if doc_type not in _VALID_DOC_TYPES:
        logger.warning("Unknown doc_type '%s' from AI, defaulting to 'unknown'", doc_type)
        doc_type = "unknown"

    subjects: list[SubjectEntry] = []
    for s in result.get("subjects", []):
        if isinstance(s, dict) and s.get("code"):
            subjects.append(
                SubjectEntry(code=str(s["code"]).strip(), name=str(s.get("name", "")).strip())
            )

    confidence = float(result.get("confidence", 0.0))
    confidence = max(0.0, min(1.0, confidence))

    total_students = result.get("total_students", 0)
    try:
        total_students = int(total_students)
    except (ValueError, TypeError):
        total_students = 0

    return AIInsight(
        document_type=doc_type,
        course=result.get("course") or None,
        semester=result.get("semester") or None,
        exam_name=result.get("exam_name") or None,
        total_students=total_students,
        subjects_detected=subjects,
        confidence=confidence,
        notes=str(result.get("notes", "")),
        suggested_outputs=result.get("suggested_outputs", []),
    )
