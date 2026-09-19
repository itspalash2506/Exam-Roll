"""Organization.ai_processing_enabled must actually gate Groq calls, not just
exist as an unread column (P10, FUTURE_UNIFIED.md §8.4 item 2)."""

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_settings_get_defaults_to_ai_enabled(client):
    res = await client.get("/api/v1/settings")
    assert res.status_code == 200
    assert res.json()["ai_processing_enabled"] is True


@pytest.mark.asyncio
async def test_settings_patch_toggles_ai_opt_out(client):
    res = await client.patch("/api/v1/settings", json={"ai_processing_enabled": False})
    assert res.status_code == 200
    assert res.json()["ai_processing_enabled"] is False

    res = await client.get("/api/v1/settings")
    assert res.json()["ai_processing_enabled"] is False


@pytest.mark.asyncio
async def test_ai_disabled_org_never_calls_groq(client, make_pdf_pages):
    await client.patch("/api/v1/settings", json={"ai_processing_enabled": False})
    make_pdf_pages()

    with patch("app.services.pipeline.processor.classify_document") as mock_classify, \
         patch("app.services.pipeline.processor.extract_students_ai") as mock_extract_ai:
        files = [("files", ("test.pdf", b"%PDF-1.4 dummy", "application/pdf"))]
        res = await client.post("/api/v1/upload", files=files)
        assert res.status_code == 200
        job_id = res.json()["job_id"]

    mock_classify.assert_not_called()
    mock_extract_ai.assert_not_called()

    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert job["document_type"] == "unknown"
    assert "AI disabled" in job["extracted_data"]["ai_notes"]


@pytest.mark.asyncio
async def test_ai_enabled_org_still_calls_groq(client, make_pdf_pages):
    """Control case — a default (opted-in) org's upload still goes through
    classify_document (mocked to a fixed insight by conftest.py's autouse
    mock_classifier), proving the opt-out check doesn't disable AI globally."""
    make_pdf_pages()

    files = [("files", ("test.pdf", b"%PDF-1.4 dummy", "application/pdf"))]
    res = await client.post("/api/v1/upload", files=files)
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert job["document_type"] == "attestation_sheet"  # mock_classifier's fixed insight
