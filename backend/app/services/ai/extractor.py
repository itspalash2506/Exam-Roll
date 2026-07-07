import json
import logging

from app.schemas.schemas import StudentRecord, SubjectEntry
from app.services.ai.groq_client import get_groq_client

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM_PROMPT = """You are a data extraction assistant for Indian college/university exam records.

Extract all student records from the document text provided.
For each student:
  - Find their roll number (e.g. 22131345, A2023001, 2024CS001, etc.)
  - List only the subject codes they are enrolled in, chosen from the provided known subject codes

Return ONLY a valid JSON array, no other text:
[
  {"roll_number": "22131345", "subjects": ["MBAN301", "MBAN302", "MBAN303"]},
  {"roll_number": "22131346", "subjects": ["MBAN301", "MBAN303"]},
  ...
]

Rules:
- Only use subject codes from the provided list — do not invent codes
- If a student appears multiple times, merge their subjects into one record
- If no students are found, return: []"""


def extract_students_ai(
    text_sample: str,
    document_type: str,
    detected_subjects: list[SubjectEntry],
) -> list[StudentRecord]:
    client = get_groq_client()
    valid_codes = {s.code for s in detected_subjects}
    subject_ref = "\n".join(f"  - {s.code}: {s.name}" for s in detected_subjects)
    snippet = text_sample[:8000]

    user_prompt = (
        f"Document type: {document_type}\n\n"
        f"Known subject codes:\n{subject_ref}\n\n"
        f"Extract all student records from this text:\n{snippet}"
    )

    raw = client.complete(_EXTRACT_SYSTEM_PROMPT, user_prompt)
    text = raw.strip()

    start = text.find("[")
    end = text.rfind("]") + 1
    if start == -1 or end == 0:
        logger.warning("No JSON array found in extractor response for doc_type '%s'", document_type)
        return []

    try:
        records_raw = json.loads(text[start:end])
    except json.JSONDecodeError as exc:
        logger.error("Extractor JSON parse error: %s | snippet: %.200s", exc, text[start:end])
        return []

    # Merge duplicate roll numbers and filter to known subject codes
    merged: dict[str, set[str]] = {}
    for item in records_raw:
        if not isinstance(item, dict):
            continue
        roll = str(item.get("roll_number", "")).strip()
        if not roll:
            continue
        subs = {
            str(c).strip()
            for c in item.get("subjects", [])
            if str(c).strip() in valid_codes
        }
        if subs:
            merged.setdefault(roll, set()).update(subs)

    return [
        StudentRecord(roll_number=roll, subjects=sorted(subs))
        for roll, subs in merged.items()
    ]


def validate_extraction(
    students: list[StudentRecord],
    expected_subjects: list[SubjectEntry],
) -> dict:
    warnings: list[str] = []
    valid_codes = {s.code for s in expected_subjects}

    roll_counts: dict[str, int] = {}
    students_without_subjects = 0
    unknown_codes: set[str] = set()

    for student in students:
        roll_counts[student.roll_number] = roll_counts.get(student.roll_number, 0) + 1
        if not student.subjects:
            students_without_subjects += 1
        for code in student.subjects:
            if code not in valid_codes:
                unknown_codes.add(code)

    duplicates = [roll for roll, count in roll_counts.items() if count > 1]

    if students_without_subjects:
        warnings.append(f"{students_without_subjects} student(s) have no subjects assigned")
    if duplicates:
        warnings.append(f"Duplicate roll numbers: {', '.join(duplicates[:5])}")
    if unknown_codes:
        warnings.append(f"Unknown subject codes: {', '.join(sorted(unknown_codes))}")

    subject_counts: dict[str, int] = {}
    for student in students:
        for code in student.subjects:
            subject_counts[code] = subject_counts.get(code, 0) + 1

    valid = not duplicates and students_without_subjects == 0

    return {
        "valid": valid,
        "warnings": warnings,
        "stats": {
            "total_students": len(students),
            "unique_roll_numbers": len(roll_counts),
            "duplicate_roll_numbers": len(duplicates),
            "students_without_subjects": students_without_subjects,
            "subjects_found": list(subject_counts.keys()),
            "student_count_per_subject": subject_counts,
        },
    }
