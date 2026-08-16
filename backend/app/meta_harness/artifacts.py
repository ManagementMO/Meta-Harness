"""Atomic and content-addressed artifact helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.meta_harness.contracts import ArtifactRef


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp_path = Path(raw_tmp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def atomic_write_text(path: Path, content: str) -> None:
    atomic_write_bytes(path, content.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True, default=str))


def store_artifact(
    run_dir: Path,
    content: bytes,
    *,
    media_type: str = "application/octet-stream",
) -> ArtifactRef:
    digest = sha256_bytes(content)
    relative = Path("artifacts") / "sha256" / digest[:2] / digest
    target = run_dir / relative
    if target.exists():
        if sha256_file(target) != digest:
            raise ValueError(f"artifact hash mismatch at {target}")
    else:
        atomic_write_bytes(target, content)
    return ArtifactRef(
        sha256=digest,
        artifact_path=relative.as_posix(),
        media_type=media_type,
        size_bytes=len(content),
    )


def store_json_artifact(run_dir: Path, value: Any) -> ArtifactRef:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return store_artifact(
        run_dir,
        canonical_json_bytes(value),
        media_type="application/json",
    )


def verify_artifact(run_dir: Path, ref: ArtifactRef) -> Path:
    target = (run_dir / ref.artifact_path).resolve()
    try:
        target.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"artifact escapes run directory: {ref.artifact_path}") from exc
    if not target.is_file():
        raise FileNotFoundError(target)
    if target.stat().st_size != ref.size_bytes:
        raise ValueError(f"artifact size mismatch at {target}")
    if sha256_file(target) != ref.sha256:
        raise ValueError(f"artifact hash mismatch at {target}")
    return target
