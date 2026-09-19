"""Cross-tenant isolation (P0-4, DECISIONS.md 2026-09-19).

Before this phase, `Job` had no owner column at all — every job was
readable and deletable by anyone who could reach the API. This is the
dedicated test for the one thing that must never regress: an org must never
be able to read, delete, export, or even learn of the existence of another
org's job.
"""

import pytest


async def _create_job_for(anon_client, cookies, make_pdf_pages) -> str:
    with make_pdf_pages():
        files = [("files", ("tenancy_test.pdf", b"%PDF-1.4 content", "application/pdf"))]
        res = await anon_client.post("/api/v1/upload", files=files, cookies=cookies)
        assert res.status_code == 200, f"job setup failed: {res.text}"
        return res.json()["job_id"]


async def test_org_cannot_read_delete_or_export_another_orgs_job(
    anon_client, org_a, org_b, make_pdf_pages
):
    job_id = await _create_job_for(anon_client, org_a.cookies, make_pdf_pages)

    checks = [
        ("GET", f"/api/v1/jobs/{job_id}", None),
        ("POST", "/api/v1/export", {"job_id": job_id, "filename": "x"}),
        ("DELETE", f"/api/v1/jobs/{job_id}", None),
    ]
    for method, path, json_body in checks:
        r = await anon_client.request(
            method, path, cookies=org_b.cookies, json=json_body
        )
        assert r.status_code == 404, (
            f"{method} {path} leaked across tenants: got {r.status_code}, "
            f"expected 404 (never 403 — a 403 would confirm the job exists)"
        )

    # The listing must never even mention it.
    r = await anon_client.get("/api/v1/jobs", cookies=org_b.cookies)
    assert r.status_code == 200
    assert all(j["id"] != job_id for j in r.json())

    # And org_a — the actual owner — can still reach its own job. Proves the
    # 404s above are real tenant isolation, not a router-wide bug that
    # blocks everyone.
    r = await anon_client.get(f"/api/v1/jobs/{job_id}", cookies=org_a.cookies)
    assert r.status_code == 200


async def test_org_cannot_redownload_another_orgs_output_file(
    anon_client, org_a, org_b, make_pdf_pages
):
    job_id = await _create_job_for(anon_client, org_a.cookies, make_pdf_pages)
    export_res = await anon_client.post(
        "/api/v1/export",
        json={"job_id": job_id, "filename": "x"},
        cookies=org_a.cookies,
    )
    assert export_res.status_code == 200

    # org_a can list its own job with the output file recorded...
    detail = await anon_client.get(f"/api/v1/jobs/{job_id}", cookies=org_a.cookies)
    output_files = detail.json()["output_files"]
    assert len(output_files) == 1
    file_id = output_files[0]["id"]

    # ...but org_b cannot redownload it, even knowing the exact job_id/file_id.
    r = await anon_client.get(
        f"/api/v1/export/{job_id}/download/{file_id}", cookies=org_b.cookies
    )
    assert r.status_code == 404


async def test_unauthenticated_request_is_401_not_404_or_500(anon_client):
    """No cookie at all is a distinct case from a wrong-org cookie — both
    must be rejected, but the missing-auth case is 401, confirming
    require_org actually runs before anything else."""
    r = await anon_client.get("/api/v1/jobs")
    assert r.status_code == 401


async def test_new_upload_is_scoped_to_the_uploading_org(
    anon_client, org_a, org_b, make_pdf_pages
):
    """A job created by org_a must carry org_a's id, not leak into org_b's
    list even before any explicit cross-tenant request is made."""
    job_id = await _create_job_for(anon_client, org_a.cookies, make_pdf_pages)

    a_jobs = await anon_client.get("/api/v1/jobs", cookies=org_a.cookies)
    b_jobs = await anon_client.get("/api/v1/jobs", cookies=org_b.cookies)

    assert any(j["id"] == job_id for j in a_jobs.json())
    assert all(j["id"] != job_id for j in b_jobs.json())
