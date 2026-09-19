"""Object storage (Cloudflare R2, DECISIONS.md 2026-09-20).

Two backends, both covered:
- Local disk (_local.py) — exercised directly against a tmp_path, and via
  the top-level dispatch (which is what the rest of the app calls) when
  R2 settings are unset — the normal state for the whole rest of this
  test suite.
- R2 (_r2.py) — exercised via `moto`, which mocks the S3 API in-process
  so the boto3 code path gets real automated coverage without live
  credentials. Live verification against a real R2 bucket happens
  separately, once real credentials exist.
"""

import pytest
from moto import mock_aws

from app.config import get_settings
from app.services import storage
from app.services.storage import _local, _r2


# ── Local-disk backend, direct ──────────────────────────────────────────────

async def test_local_upload_download_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    src = tmp_path / "source.txt"
    src.write_bytes(b"hello world")

    await _local.upload_local_file(str(src), "jobs/abc/source.txt")
    assert await _local.object_exists("jobs/abc/source.txt")
    assert await _local.download_bytes("jobs/abc/source.txt") == b"hello world"


async def test_local_delete_object(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    src = tmp_path / "source.txt"
    src.write_bytes(b"data")
    await _local.upload_local_file(str(src), "jobs/abc/source.txt")

    await _local.delete_object("jobs/abc/source.txt")
    assert not await _local.object_exists("jobs/abc/source.txt")


async def test_local_delete_prefix_removes_whole_job_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    src = tmp_path / "a.txt"
    src.write_bytes(b"a")
    await _local.upload_local_file(str(src), "jobs/abc/01_a.txt")
    await _local.upload_local_file(str(src), "jobs/abc/02_b.txt")

    await _local.delete_prefix("jobs/abc")
    assert not await _local.object_exists("jobs/abc/01_a.txt")
    assert not await _local.object_exists("jobs/abc/02_b.txt")


async def test_local_object_exists_false_for_missing_key(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    assert not await _local.object_exists("jobs/does-not-exist/x.txt")


# ── Dispatch: falls back to local disk when R2 isn't configured ────────────

async def test_dispatch_uses_local_backend_when_r2_unconfigured(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    # This test suite never sets R2 credentials, so object_storage_enabled
    # is already False — asserting it explicitly documents the assumption.
    assert settings.object_storage_enabled is False

    src = tmp_path / "source.txt"
    src.write_bytes(b"via dispatch")
    await storage.upload_local_file(str(src), "jobs/xyz/source.txt")
    assert await storage.download_bytes("jobs/xyz/source.txt") == b"via dispatch"


# ── R2 backend, via moto (mocks the S3 API in-process) ─────────────────────

@pytest.fixture
def r2_settings(monkeypatch):
    """Configure R2 settings so object_storage_enabled is True and _r2.py's
    boto3 client points at moto's mock endpoint instead of real R2."""
    settings = get_settings()
    monkeypatch.setattr(settings, "r2_account_id", "test-account")
    monkeypatch.setattr(settings, "r2_access_key_id", "test-key")
    monkeypatch.setattr(settings, "r2_secret_access_key", "test-secret")
    monkeypatch.setattr(settings, "r2_bucket_name", "test-bucket")
    return settings


@pytest.fixture
def moto_bucket(r2_settings, monkeypatch):
    """moto only intercepts boto3 calls made to a STANDARD AWS endpoint —
    verified empirically: pointing a client at R2's custom endpoint_url
    (as _r2.py's real _client() does) produces a genuine SSL handshake
    failure against a nonexistent host, not a moto-mocked response. moto's
    HTTP interception matches known AWS URL patterns and doesn't recognize
    an arbitrary custom domain like Cloudflare's.

    So _r2._client is patched to build a client with NO custom endpoint —
    moto intercepts that one correctly — while every function body under
    test (upload_local_file, download_bytes, object_exists, delete_object,
    delete_prefix's pagination/batch-delete) still runs unmodified. This is
    the actual logic that could have a bug; the endpoint_url/region_name
    wiring itself is a single f-string, verified separately against the
    real R2 bucket once live credentials exist.
    """
    with mock_aws():
        import boto3

        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=r2_settings.r2_bucket_name)
        monkeypatch.setattr(_r2, "_client", lambda: client)
        yield


async def test_r2_dispatch_is_used_when_configured(r2_settings):
    assert r2_settings.object_storage_enabled is True


async def test_r2_upload_download_roundtrip(tmp_path, moto_bucket):
    src = tmp_path / "source.txt"
    src.write_bytes(b"hello r2")
    await _r2.upload_local_file(str(src), "jobs/abc/source.txt")

    assert await _r2.object_exists("jobs/abc/source.txt")
    assert await _r2.download_bytes("jobs/abc/source.txt") == b"hello r2"


async def test_r2_delete_object(tmp_path, moto_bucket):
    src = tmp_path / "source.txt"
    src.write_bytes(b"data")
    await _r2.upload_local_file(str(src), "jobs/abc/source.txt")

    await _r2.delete_object("jobs/abc/source.txt")
    assert not await _r2.object_exists("jobs/abc/source.txt")


async def test_r2_delete_prefix_removes_every_matching_object(tmp_path, moto_bucket):
    src = tmp_path / "a.txt"
    src.write_bytes(b"a")
    await _r2.upload_local_file(str(src), "jobs/abc/01_a.txt")
    await _r2.upload_local_file(str(src), "jobs/abc/02_b.txt")
    # A sibling job must survive — prefix deletion must not over-match.
    await _r2.upload_local_file(str(src), "jobs/other-job/01_a.txt")

    await _r2.delete_prefix("jobs/abc")

    assert not await _r2.object_exists("jobs/abc/01_a.txt")
    assert not await _r2.object_exists("jobs/abc/02_b.txt")
    assert await _r2.object_exists("jobs/other-job/01_a.txt")


async def test_r2_object_exists_false_for_missing_key(moto_bucket):
    assert not await _r2.object_exists("jobs/does-not-exist/x.txt")


async def test_dispatch_uses_r2_backend_when_configured(tmp_path, moto_bucket):
    """The top-level storage module — what the rest of the app actually
    calls — routes to _r2.py once R2 settings are set, with no code change
    needed at any call site."""
    src = tmp_path / "source.txt"
    src.write_bytes(b"via r2 dispatch")
    await storage.upload_local_file(str(src), "jobs/xyz/source.txt")
    assert await storage.download_bytes("jobs/xyz/source.txt") == b"via r2 dispatch"
