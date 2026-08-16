"""Reproducible provenance capture for runs and candidates."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.meta_harness.artifacts import canonical_json_bytes, sha256_bytes, sha256_file
from app.meta_harness.contracts import Provenance


def _git_output(repo_root: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def capture_git_state(repo_root: Path) -> tuple[str | None, bool | None]:
    commit = _git_output(repo_root, "rev-parse", "HEAD")
    status = _git_output(repo_root, "status", "--porcelain")
    return commit, None if status is None else bool(status)


def runtime_source_paths() -> tuple[str, ...]:
    return (
        "backend/app/meta_harness/artifacts.py",
        "backend/app/meta_harness/branches.py",
        "backend/app/meta_harness/candidates.py",
        "backend/app/meta_harness/contracts.py",
        "backend/app/meta_harness/evaluator.py",
        "backend/app/meta_harness/execution.py",
        "backend/app/meta_harness/experiments.py",
        "backend/app/meta_harness/frontier.py",
        "backend/app/meta_harness/harness.py",
        "backend/app/meta_harness/inner.py",
        "backend/app/meta_harness/ledger.py",
        "backend/app/meta_harness/memory.py",
        "backend/app/meta_harness/outer.py",
        "backend/app/meta_harness/persistence.py",
        "backend/app/meta_harness/proposer.py",
        "backend/app/meta_harness/provenance.py",
        "backend/app/meta_harness/refinements.py",
        "backend/app/meta_harness/reports.py",
        "backend/app/meta_harness/runs.py",
        "backend/app/meta_harness/runtime.py",
        "backend/app/meta_harness/skill_contract.py",
        "backend/app/meta_harness/state.py",
        "backend/app/meta_harness/sandbox.py",
        "backend/app/meta_harness/tools.py",
    )


def capture_runtime_sha256(repo_root: Path) -> str:
    rows = []
    for relative in runtime_source_paths():
        path = repo_root / relative
        if path.is_file():
            rows.append({"path": relative, "sha256": sha256_file(path)})
    return sha256_bytes(canonical_json_bytes(rows))


def capture_provenance(
    repo_root: Path,
    *,
    authorization_profile: str,
    proposer_session_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Provenance:
    commit, dirty = capture_git_state(repo_root)
    return Provenance(
        git_commit=commit,
        git_dirty=dirty,
        runtime_sha256=capture_runtime_sha256(repo_root),
        dependency_lock_sha256=(
            sha256_file(repo_root / "uv.lock")
            if (repo_root / "uv.lock").is_file()
            else None
        ),
        proposer_session_id=proposer_session_id,
        authorization_profile=authorization_profile,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        environment={
            key: os.environ[key]
            for key in (
                "META_HARNESS_INNER_MODEL",
                "META_HARNESS_API_PERSISTENT",
            )
            if key in os.environ
        },
        **(extra or {}),
    )
