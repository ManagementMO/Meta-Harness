"""Task runtime adapters shared by orientation, verification, and finalization."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.meta_harness.artifacts import canonical_json_bytes, sha256_bytes, sha256_file
from app.meta_harness.contracts import TaskSpec
from app.meta_harness.sandbox import run_in_sandbox


@dataclass(frozen=True)
class VerificationOutcome:
    passed: bool
    command: str
    exit_code: int | None
    output: str
    timed_out: bool = False


class TaskRuntimeAdapter(Protocol):
    name: str

    def inspect(self, workspace: Path) -> dict[str, Any]: ...

    def verify(
        self,
        workspace: Path,
        task: dict[str, Any],
        *,
        timeout_sec: int,
    ) -> VerificationOutcome: ...


class PythonPytestAdapter:
    name = "python-pytest-v1"

    def inspect(self, workspace: Path) -> dict[str, Any]:
        tests: dict[str, str] = {}
        for test_file in list(workspace.rglob("test_*.py"))[:10]:
            if not test_file.is_file():
                continue
            try:
                tests[str(test_file.relative_to(workspace))] = test_file.read_text()[
                    :4000
                ]
            except (OSError, UnicodeDecodeError):
                pass
        configs: dict[str, str] = {}
        for cfg_name in ("README.md", "pyproject.toml", "package.json", "Makefile"):
            cfg_path = workspace / cfg_name
            if not cfg_path.is_file() or cfg_path.stat().st_size >= 4000:
                continue
            try:
                configs[cfg_name] = cfg_path.read_text()
            except (OSError, UnicodeDecodeError):
                pass
        return {
            "project": {"lang": "python", "test_runner": "pytest"},
            "configs": configs,
            "tests": tests,
        }

    def verify(
        self,
        workspace: Path,
        task: dict[str, Any],
        *,
        timeout_sec: int,
    ) -> VerificationOutcome:
        command = str(task.get("test_command") or "pytest -q")
        return _run_command(workspace, command, timeout_sec=timeout_sec)


class GenericCommandAdapter:
    name = "generic-command-v1"

    def inspect(self, workspace: Path) -> dict[str, Any]:
        configs: dict[str, str] = {}
        for cfg_name in ("README.md", "pyproject.toml", "package.json", "Makefile"):
            cfg_path = workspace / cfg_name
            if not cfg_path.is_file() or cfg_path.stat().st_size >= 4000:
                continue
            try:
                configs[cfg_name] = cfg_path.read_text()
            except (OSError, UnicodeDecodeError):
                pass
        return {
            "project": {"lang": "unknown", "test_runner": "command"},
            "configs": configs,
            "tests": {},
        }

    def verify(
        self,
        workspace: Path,
        task: dict[str, Any],
        *,
        timeout_sec: int,
    ) -> VerificationOutcome:
        command = str(task.get("test_command") or "")
        if not command:
            return VerificationOutcome(
                passed=False,
                command="",
                exit_code=None,
                output="[missing test_command]",
            )
        return _run_command(workspace, command, timeout_sec=timeout_sec)


_ADAPTERS: dict[str, TaskRuntimeAdapter] = {
    PythonPytestAdapter.name: PythonPytestAdapter(),
    GenericCommandAdapter.name: GenericCommandAdapter(),
}


def register_runtime_adapter(adapter: TaskRuntimeAdapter) -> None:
    if not adapter.name:
        raise ValueError("runtime adapter name is required")
    _ADAPTERS[adapter.name] = adapter


def get_runtime_adapter(name: str | None) -> TaskRuntimeAdapter:
    resolved = name or PythonPytestAdapter.name
    try:
        return _ADAPTERS[resolved]
    except KeyError as exc:
        raise ValueError(f"unknown runtime adapter: {resolved}") from exc


def _run_command(
    workspace: Path,
    command: str,
    *,
    timeout_sec: int,
) -> VerificationOutcome:
    try:
        proc = run_in_sandbox(workspace, command, timeout_sec=timeout_sec)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return VerificationOutcome(
            passed=False,
            command=command,
            exit_code=None,
            output=(stdout + "\n" + stderr + "\n[timeout]")[-8000:],
            timed_out=True,
        )
    return VerificationOutcome(
        passed=proc.returncode == 0,
        command=command,
        exit_code=proc.returncode,
        output=(proc.stdout + "\n" + proc.stderr)[-8000:],
    )


def _workspace_hash(workspace: Path) -> str:
    rows: list[dict[str, Any]] = []
    for path in sorted(p for p in workspace.rglob("*") if p.is_file()):
        relative = path.relative_to(workspace)
        if any(
            part in {"__pycache__", ".pytest_cache", ".git"}
            for part in relative.parts
        ) or path.suffix in {".pyc", ".pyo"}:
            continue
        rows.append(
            {
                "path": relative.as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return sha256_bytes(canonical_json_bytes(rows))


def load_task_spec(
    task_dir: Path,
    *,
    visibility: str,
) -> TaskSpec:
    raw = json.loads((task_dir / "task.json").read_text())
    runtime_adapter = str(raw.get("runtime_adapter") or PythonPytestAdapter.name)
    get_runtime_adapter(runtime_adapter)
    identity = {
        "task": raw,
        "workspace_sha256": _workspace_hash(task_dir / "workspace"),
        "visibility": visibility,
    }
    return TaskSpec.model_validate(
        {
            **raw,
            "runtime_adapter": runtime_adapter,
            "visibility": visibility,
            "source_path": str(task_dir.resolve()),
            "sha256": sha256_bytes(canonical_json_bytes(identity)),
        }
    )


def discover_tasks(tasks_root: Path, *, visibility: str) -> list[TaskSpec]:
    return [
        load_task_spec(task_dir, visibility=visibility)
        for task_dir in sorted(tasks_root.iterdir())
        if task_dir.is_dir() and (task_dir / "task.json").is_file()
    ]
