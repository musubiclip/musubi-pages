"""Blob storage: a local folder or an S3 bucket, chosen per call from env PAGES_STORE."""
import json
import os
import random
import shutil
import tempfile
from pathlib import Path

from pages import config


def _backend():
    loc = os.environ.get("PAGES_STORE") or str(config.HOME / "store")
    if loc.startswith("s3://"):
        import boto3
        return boto3.client("s3", region_name="ap-south-1"), loc[5:].strip("/")
    return None, Path(loc)


def _local(where: Path, key: str) -> Path:
    # Keys come from URLs (/files/<key>); never let one escape the store root.
    root = where.resolve()
    p = (root / key).resolve()
    if not p.is_relative_to(root) or p == root:
        raise ValueError(f"key outside store: {key}")
    return p


def put(key: str, path) -> None:
    s3, where = _backend()
    if s3:
        s3.upload_file(str(path), where, key)
    else:
        _local(where, key).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, _local(where, key))


def get(key: str, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    s3, where = _backend()
    if s3:
        s3.download_file(where, key, str(path))
    else:
        shutil.copyfile(_local(where, key), path)
    return path


def exists(key: str) -> bool:
    s3, where = _backend()
    if s3:
        try:
            s3.head_object(Bucket=where, Key=key)
            return True
        except s3.exceptions.ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise
    return _local(where, key).is_file()


def music_bed(keys: list[str], folder) -> Path | None:
    """A random one of a page's music keys, fetched into folder; a key not uploaded yet is skipped, not fatal."""
    held = [k for k in keys if exists(k)]
    if not held:
        return None
    key = random.choice(held)
    return get(key, Path(folder) / Path(key).name)


def keys(prefix: str) -> list[str]:
    s3, where = _backend()
    if s3:
        out = []
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=where, Prefix=prefix):
            out += [o["Key"] for o in page.get("Contents", [])]
        return sorted(out)
    if not where.exists():
        return []
    return sorted(k for p in where.rglob("*") if p.is_file() and (k := p.relative_to(where).as_posix()).startswith(prefix))


def delete(key: str) -> None:
    s3, where = _backend()
    if s3:
        s3.delete_object(Bucket=where, Key=key)
    else:
        _local(where, key).unlink(missing_ok=True)


def put_json(key: str, value) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "v.json"
        f.write_text(json.dumps(value))
        put(key, f)


def get_json(key: str, default=None):
    if not exists(key):
        return default
    with tempfile.TemporaryDirectory() as tmp:
        return json.loads(get(key, Path(tmp) / "v.json").read_text())


def url(key: str, seconds: int = 3600) -> str:
    s3, where = _backend()
    if s3:
        return s3.generate_presigned_url("get_object", Params={"Bucket": where, "Key": key}, ExpiresIn=seconds)
    public = os.environ.get("PAGES_PUBLIC_URL", "").rstrip("/")
    if public and key.startswith("clips/"):
        # local publishing: a tunnel serves only the rendered clips folder, so Instagram can fetch the video
        return f"{public}/{key.removeprefix('clips/')}"
    return f"/files/{key}"
