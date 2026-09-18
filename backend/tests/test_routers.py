import pytest
from app.config import get_settings


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """GET /health returns 200 with status ok and connected DB."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert "version" in data
    assert "environment" in data


@pytest.mark.asyncio
async def test_upload_happy_path(client, make_pdf_pages):
    """POST /api/v1/upload succeeds with valid PDF, processes inline, and persists completed job."""
    with make_pdf_pages():
        files = [
            ("files", ("attestation.pdf", b"%PDF-1.4 dummy content", "application/pdf"))
        ]
        response = await client.post("/api/v1/upload", files=files)
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert "uploaded" in data["message"]

        job_id = data["job_id"]
        job_res = await client.get(f"/api/v1/jobs/{job_id}")
        assert job_res.status_code == 200
        job_data = job_res.json()
        assert job_data["status"] == "completed"
        assert job_data["progress"] == 100
        assert job_data["total_students"] == 2
        assert job_data["extracted_data"] is not None


@pytest.mark.asyncio
async def test_upload_xls_rejected(client):
    """POST /api/v1/upload rejects legacy .xls files with 400 Bad Request."""
    files = [("files", ("students.xls", b"legacy excel bytes", "application/vnd.ms-excel"))]
    response = await client.post("/api/v1/upload", files=files)
    assert response.status_code == 400
    data = response.json()
    assert "Unsupported file type" in data["detail"]
    assert ".xls" in data["detail"]


@pytest.mark.asyncio
async def test_upload_max_file_size_rejected(client, monkeypatch):
    """POST /api/v1/upload rejects files exceeding max_file_size_mb with 400 Bad Request."""
    settings = get_settings()
    monkeypatch.setattr(settings, "max_file_size_mb", 0)

    files = [("files", ("oversized.pdf", b"%PDF-1.4 1234567890", "application/pdf"))]
    response = await client.post("/api/v1/upload", files=files)
    assert response.status_code == 400
    assert "limit" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_max_batch_files_rejected(client):
    """POST /api/v1/upload rejects batches larger than max_batch_files with 400 Bad Request."""
    settings = get_settings()
    max_batch = settings.max_batch_files
    files = [
        ("files", (f"file_{i}.pdf", b"%PDF-1.4 test", "application/pdf"))
        for i in range(max_batch + 1)
    ]
    response = await client.post("/api/v1/upload", files=files)
    assert response.status_code == 400
    assert f"exceeds the {max_batch}-file batch limit" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_jobs_list(client, make_pdf_pages):
    """GET /api/v1/jobs returns a list of jobs."""
    with make_pdf_pages():
        files = [("files", ("job_list_test.pdf", b"%PDF-1.4 content", "application/pdf"))]
        await client.post("/api/v1/upload", files=files)

    response = await client.get("/api/v1/jobs")
    assert response.status_code == 200
    jobs = response.json()
    assert isinstance(jobs, list)
    assert len(jobs) >= 1


@pytest.mark.asyncio
async def test_get_job_not_found(client):
    """GET /api/v1/jobs/{job_id} returns 404 for unknown job id."""
    response = await client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


@pytest.mark.asyncio
async def test_delete_job(client, make_pdf_pages):
    """DELETE /api/v1/jobs/{job_id} returns 204 and removes the job."""
    with make_pdf_pages():
        files = [("files", ("to_delete.pdf", b"%PDF-1.4 content", "application/pdf"))]
        res = await client.post("/api/v1/upload", files=files)
        job_id = res.json()["job_id"]

    del_res = await client.delete(f"/api/v1/jobs/{job_id}")
    assert del_res.status_code == 204

    get_res = await client.get(f"/api/v1/jobs/{job_id}")
    assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_export_happy_path(client, make_pdf_pages):
    """POST /api/v1/export produces valid .xlsx spreadsheet for completed job."""
    with make_pdf_pages():
        files = [("files", ("export_test.pdf", b"%PDF-1.4 content", "application/pdf"))]
        res = await client.post("/api/v1/upload", files=files)
        job_id = res.json()["job_id"]

    export_req = {
        "job_id": job_id,
        "filename": "Final_Roster",
    }
    response = await client.post("/api/v1/export", json=export_req)
    assert response.status_code == 200
    assert (
        response.headers.get("content-type")
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    # XLSX files are zip archives starting with 'PK\x03\x04'
    assert response.content.startswith(b"PK")


@pytest.mark.asyncio
async def test_download_export_not_found(client):
    """GET /api/v1/export/{job_id}/download/{file_id} returns 404 for unknown file/job."""
    response = await client.get("/api/v1/export/bogus-job-id/download/bogus-file-id")
    assert response.status_code == 404
    assert response.json()["detail"] == "Output file not found"
