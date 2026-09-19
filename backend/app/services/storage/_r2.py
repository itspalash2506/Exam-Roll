"""Cloudflare R2 backend, via its S3-compatible API (DECISIONS.md, 2026-09-20).

boto3 is sync, so every public function wraps its actual client call in
asyncio.to_thread() — the same pattern already used elsewhere in this
codebase for other blocking I/O (Groq, PDF parsing), rather than pulling in
a separate async S3 library.

A fresh client is built per call rather than cached: call volume here is low
(occasional uploads/downloads, not a high-QPS path), and a fresh client
avoids any risk of a stale cached client holding onto credentials from
before a settings change — relevant for tests, which monkeypatch R2 settings
per-test.
"""

import asyncio

import boto3
from botocore.config import Config as BotoConfig

from app.config import get_settings


def _client():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.r2_endpoint_url,
        aws_access_key_id=s.r2_access_key_id,
        aws_secret_access_key=s.r2_secret_access_key,
        # R2 requires "auto" — it isn't a real AWS region, just what
        # Cloudflare's S3-compatible API expects here.
        region_name="auto",
        config=BotoConfig(signature_version="s3v4"),
    )


def _bucket() -> str:
    return get_settings().r2_bucket_name


async def upload_local_file(local_path: str, key: str) -> None:
    def _do():
        _client().upload_file(local_path, _bucket(), key)

    await asyncio.to_thread(_do)


async def upload_bytes(data: bytes, key: str) -> None:
    def _do():
        _client().put_object(Bucket=_bucket(), Key=key, Body=data)

    await asyncio.to_thread(_do)


async def download_bytes(key: str) -> bytes:
    def _do() -> bytes:
        resp = _client().get_object(Bucket=_bucket(), Key=key)
        return resp["Body"].read()

    return await asyncio.to_thread(_do)


async def object_exists(key: str) -> bool:
    def _do() -> bool:
        from botocore.exceptions import ClientError

        try:
            _client().head_object(Bucket=_bucket(), Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return False
            raise

    return await asyncio.to_thread(_do)


async def delete_object(key: str) -> None:
    def _do():
        _client().delete_object(Bucket=_bucket(), Key=key)

    await asyncio.to_thread(_do)


async def delete_prefix(prefix: str) -> None:
    """List then batch-delete every object under `prefix`, paginating —
    delete_objects only accepts up to 1000 keys per call."""
    def _do():
        client = _client()
        bucket = _bucket()
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if keys:
                client.delete_objects(Bucket=bucket, Delete={"Objects": keys})

    await asyncio.to_thread(_do)
