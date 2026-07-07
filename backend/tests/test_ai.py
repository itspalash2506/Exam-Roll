import pytest
from unittest.mock import patch


def test_classify_document_returns_dict():
    mock_response = '{"doc_type": "roll_list", "confidence": 0.95, "reason": "contains roll numbers"}'
    with patch("app.services.ai.groq_client.chat_completion", return_value=mock_response):
        from app.services.ai.classifier import classify_document
        result = classify_document("Roll No: 001 Subject: Maths")
    assert result["doc_type"] == "roll_list"
    assert result["confidence"] == 0.95


def test_extract_roll_subjects_returns_list():
    mock_response = '[{"roll_no": "001", "subject": "Mathematics"}]'
    with patch("app.services.ai.groq_client.chat_completion", return_value=mock_response):
        from app.services.ai.extractor import extract_roll_subjects
        result = extract_roll_subjects("001 Mathematics")
    assert len(result) == 1
    assert result[0]["roll_no"] == "001"
