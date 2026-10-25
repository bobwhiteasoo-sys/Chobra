"""Closed object storage with immutable keys (local directory standing in for S3)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chobra_engine.canonical import canonical_dumps, sha256_bytes

from .config import settings


def _path(key: str) -> Path:
    if ".." in key or key.startswith("/"):
        raise ValueError("bad object key")
    return settings.objects_dir / key


def put_bytes(key: str, data: bytes) -> dict[str, Any]:
    path = _path(key)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"object key is immutable: {key}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    return {"key": key, "size": len(data), "sha256": sha256_bytes(data)}


def put_json(key: str, value: Any) -> dict[str, Any]:
    return put_bytes(key, canonical_dumps(value).encode("utf-8"))


def get_bytes(key: str) -> bytes:
    return _path(key).read_bytes()


def get_json(key: str) -> Any:
    return json.loads(get_bytes(key))


def exists(key: str) -> bool:
    return _path(key).exists()


def file_path(key: str) -> Path:
    return _path(key)
