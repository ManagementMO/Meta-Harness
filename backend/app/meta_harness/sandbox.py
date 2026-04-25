"""Process-isolated sandbox for inner-loop tool execution.

Per Appendix C §C.6.3:
- Each task gets a fresh ``/tmp/meta-harness-task-{uuid}/`` directory.
- Commands run with ``subprocess.run(..., cwd=task_dir, timeout=...)``.
- rlimit 512MB RAM + 60s CPU on Unix via ``resource.setrlimit`` in a
  ``preexec_fn``.
- **Process isolation only** — no Docker, no network restriction, no
  binary allowlist. These are honest limits we surface in user-facing
  docs; production-grade isolation is roadmap, not 36-hour scope.

The two layers:
- ``make_sandbox_dir`` / ``populate_sandbox`` / ``cleanup_sandbox`` /
  ``sandbox_for`` — sandbox lifecycle (create, copy task workspace, clean).
- ``run_in_sandbox`` — low-level exec used by ``tools.run_bash`` and
  by the inner loop's verify phase to invoke ``pytest``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# rlimit support is Unix-only; on other platforms we no-op.
try:
    import resource as _resource

    _HAS_RLIMIT = True
except ImportError:  # Windows
    _resource = None  # type: ignore[assignment]
    _HAS_RLIMIT = False


SANDBOX_PREFIX = "meta-harness-task-"
DEFAULT_RLIMIT_RAM = 512 * 1024 * 1024  # 512 MB
DEFAULT_RLIMIT_CPU = 60  # seconds


def make_sandbox_dir() -> Path:
    """Create a fresh ``/tmp/meta-harness-task-{uuid}/`` and return it."""
    sandbox = Path("/tmp") / f"{SANDBOX_PREFIX}{uuid.uuid4().hex}"
    sandbox.mkdir(parents=True, exist_ok=False)
    return sandbox


def populate_sandbox(sandbox_dir: Path, source_workspace: Path) -> None:
    """Copy a task's pristine workspace into the sandbox."""
    if not source_workspace.is_dir():
        raise ValueError(f"source workspace is not a directory: {source_workspace}")
    for entry in source_workspace.iterdir():
        target = sandbox_dir / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)


def cleanup_sandbox(sandbox_dir: Path) -> None:
    """Remove a sandbox directory. Idempotent and tolerant of missing dir."""
    shutil.rmtree(sandbox_dir, ignore_errors=True)


@contextmanager
def sandbox_for(source_workspace: Path) -> Iterator[Path]:
    """Context manager: fresh sandbox, populated from ``source_workspace``,
    cleaned up on exit.
    """
    sandbox = make_sandbox_dir()
    try:
        populate_sandbox(sandbox, source_workspace)
        yield sandbox
    finally:
        cleanup_sandbox(sandbox)


def _apply_rlimits() -> None:
    """preexec_fn: apply rlimits before exec'ing the child.

    Best-effort. Each setrlimit is wrapped so a single failure doesn't
    abort the exec. macOS's ``RLIMIT_AS`` enforcement is unreliable for
    Python child processes (Python's own address-space footprint can
    already exceed the cap before the child runs anything), so we skip
    it on Darwin and rely on the wall-clock timeout from
    ``subprocess.run`` instead.
    """
    if not _HAS_RLIMIT or _resource is None:
        return
    if sys.platform != "darwin":
        try:
            _resource.setrlimit(
                _resource.RLIMIT_AS,
                (DEFAULT_RLIMIT_RAM, DEFAULT_RLIMIT_RAM),
            )
        except (ValueError, OSError):
            pass
    try:
        _resource.setrlimit(
            _resource.RLIMIT_CPU,
            (DEFAULT_RLIMIT_CPU, DEFAULT_RLIMIT_CPU),
        )
    except (ValueError, OSError):
        pass


def run_in_sandbox(
    sandbox_dir: Path,
    command: str,
    *,
    timeout_sec: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run a shell command in the sandbox.

    Caller handles ``subprocess.TimeoutExpired``. ``preexec_fn`` applies
    rlimits on Unix only; ``sys.platform == "win32"`` skips them.
    """
    return subprocess.run(  # noqa: S602 — controlled command in sandbox
        command,
        shell=True,
        cwd=sandbox_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
        preexec_fn=_apply_rlimits if _HAS_RLIMIT and sys.platform != "win32" else None,
    )
