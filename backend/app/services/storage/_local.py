"""Local-disk object storage backend — the fallback used whenever R2 isn't
configured (local dev, the test suite). Each `key` maps 1:1 onto a real file
under `settings.upload_dir`, preserving exactly the layout/behaviour that
existed before object storage did.
"""

import os
import shutil

from app.config import get_settings


def _path_for_key(key: str) -> str:
    # key is always forward-slash-separated (R2 convention); os.path.join
    # handles the platform-appropriate separator from there.
    return os.path.join(get_settings().upload_dir, *key.split("/"))


async def upload_local_file(local_path: str, key: str) -> None:
    dest = _path_for_key(key)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.abspath(local_path) != os.path.abspath(dest):
        shutil.copyfile(local_path, dest)


async def upload_bytes(data: bytes, key: str) -> None:
    dest = _path_for_key(key)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(data)


async def download_bytes(key: str) -> bytes:
    with open(_path_for_key(key), "rb") as fh:
        return fh.read()


async def object_exists(key: str) -> bool:
    return os.path.isfile(_path_for_key(key))


async def delete_object(key: str) -> None:
    path = _path_for_key(key)
    if os.path.isfile(path):
        os.remove(path)


async def delete_prefix(prefix: str) -> None:
    dir_path = _path_for_key(prefix.rstrip("/"))
    if os.path.isdir(dir_path):
        shutil.rmtree(dir_path, ignore_errors=True)
