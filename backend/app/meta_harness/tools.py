"""The 6 fixed inner-loop tools (``INTERFACES.md`` §3).

Tools are the contract with the evaluator and **cannot be overridden**
by candidates. Each function takes the workspace ``Path`` plus tool-
specific args and returns a structured dict (``{"status": ...}``).

The ``TOOL_SCHEMAS`` list is the JSON Schema dict passed to the
Anthropic API as ``tools=...``; ``TOOL_DISPATCH`` maps tool names to
the Python implementation.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from app.meta_harness.sandbox import run_in_sandbox

# Any output captured beyond these limits is truncated. Matches the
# truncation thresholds discussed in Appendix C §C.5 (Finding 6).
_STDOUT_LIMIT = 8000
_STDERR_LIMIT = 2000
_FILE_LINE_HARD_LIMIT = 2000  # Read errors over this without explicit range
_GREP_OUTPUT_LIMIT = 8000


# ──────────────────────────────────────────────────────────────────────
# JSON schemas (verbatim from INTERFACES.md §3, kept in sync there).
# ──────────────────────────────────────────────────────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "Read a file from the workspace, with optional line range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "default": 1},
                "end_line": {"type": "integer", "description": "Inclusive; -1 = EOF"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "apply_patch",
        "description": (
            "Apply a unified-diff patch to a file. Patches are surgical and preserve "
            "unchanged lines exactly. Use this to make targeted edits rather than "
            "rewriting whole files. The patch must apply cleanly; fuzz matching is "
            "disabled."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "patch": {
                    "type": "string",
                    "description": "Unified diff format (the same format as `git diff`).",
                },
            },
            "required": ["path", "patch"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Create a new file. Errors if the file already exists — use apply_patch "
            "to modify existing files. Use this only for files that do not yet exist "
            "in the workspace."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_bash",
        "description": (
            "Run a bash command in the sandboxed workspace. Returns stdout, stderr, "
            "exit_code, and duration_ms. Commands run with a 30s default timeout "
            "(max 120s). The workspace is reset between tasks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_sec": {"type": "integer", "default": 30, "maximum": 120},
            },
            "required": ["command"],
        },
    },
    {
        "name": "grep_search",
        "description": (
            "Search files in the workspace using ripgrep. Returns file paths and "
            "matching lines with line numbers. Prefer this over reading many files "
            "individually."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern."},
                "path": {"type": "string", "default": "."},
                "file_glob": {"type": "string", "description": "e.g. '*.py'"},
                "context_lines": {"type": "integer", "default": 2, "maximum": 10},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "task_complete",
        "description": (
            "Signal that the task is done. Call this when you believe the task is "
            "solved AND tests pass. The harness will run final verification."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]

TOOL_NAMES = [s["name"] for s in TOOL_SCHEMAS]


# ──────────────────────────────────────────────────────────────────────
# Implementations.
# ──────────────────────────────────────────────────────────────────────


def _resolve_in_workspace(workspace: Path, path: str) -> Path | None:
    """Resolve ``path`` against ``workspace`` and return the absolute path.

    Returns None if the resolved path escapes the workspace (path
    traversal protection).
    """
    workspace = workspace.resolve()
    resolved = (workspace / path).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError:
        return None
    return resolved


def read_file(
    workspace: Path,
    path: str,
    *,
    start_line: int = 1,
    end_line: int = -1,
) -> dict[str, Any]:
    """Read a file. Returns line-numbered content. Errors on >2000 lines
    when no explicit range is given."""
    target = _resolve_in_workspace(workspace, path)
    if target is None:
        return {
            "status": "error",
            "error_type": "invalid_path",
            "error_message": f"path '{path}' escapes the workspace",
        }
    if not target.exists():
        return {
            "status": "error",
            "error_type": "file_not_found",
            "error_message": f"file not found: {path}",
        }
    if not target.is_file():
        return {
            "status": "error",
            "error_type": "not_a_file",
            "error_message": f"not a regular file: {path}",
        }

    text = target.read_text()
    lines = text.split("\n")
    n = len(lines)

    explicit_range = (start_line != 1) or (end_line not in (-1, n))
    if not explicit_range and n > _FILE_LINE_HARD_LIMIT:
        return {
            "status": "error",
            "error_type": "file_too_large",
            "error_message": (
                f"file has {n} lines (>{_FILE_LINE_HARD_LIMIT}); specify a "
                "range or use grep_search to find the relevant section"
            ),
            "n_lines": n,
        }

    if end_line == -1:
        end_line = n
    if start_line < 1 or start_line > n:
        return {
            "status": "error",
            "error_type": "invalid_range",
            "error_message": f"start_line {start_line} out of [1, {n}]",
        }
    if end_line < start_line:
        return {
            "status": "error",
            "error_type": "invalid_range",
            "error_message": f"end_line {end_line} < start_line {start_line}",
        }

    selected = lines[start_line - 1 : end_line]
    numbered = "\n".join(
        f"{start_line + i:6}→{line}" for i, line in enumerate(selected)
    )
    return {
        "status": "ok",
        "path": path,
        "start_line": start_line,
        "end_line": end_line,
        "n_lines": n,
        "content": numbered,
    }


def write_file(workspace: Path, path: str, content: str) -> dict[str, Any]:
    """Create a new file. Errors if file already exists."""
    target = _resolve_in_workspace(workspace, path)
    if target is None:
        return {
            "status": "error",
            "error_type": "invalid_path",
            "error_message": f"path '{path}' escapes the workspace",
        }
    if target.exists():
        return {
            "status": "error",
            "error_type": "file_exists",
            "error_message": (
                f"file '{path}' already exists. Use apply_patch to modify it."
            ),
        }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    except OSError as exc:
        return {
            "status": "error",
            "error_type": "write_failed",
            "error_message": str(exc),
        }
    return {
        "status": "ok",
        "path": path,
        "bytes_written": len(content.encode("utf-8")),
    }


_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", re.MULTILINE)


def _workspace_relative_path(workspace: Path, target: Path) -> str:
    """Return a normalized POSIX path for ``target`` relative to workspace."""
    return target.resolve().relative_to(workspace.resolve()).as_posix()


def _normalize_patch_header_path(raw: str) -> str | None:
    """Normalize a path from a unified-diff file header.

    Returns ``None`` for ``/dev/null``. Rejects absolute paths and path
    traversal; the caller compares the result against the tool's declared
    ``path`` argument before invoking ``git apply``.
    """
    path = raw.strip()
    if "\t" in path:
        path = path.split("\t", 1)[0]
    if path == "/dev/null":
        return None
    if path.startswith(("a/", "b/")):
        path = path[2:]
    posix = PurePosixPath(path)
    if posix.is_absolute() or ".." in posix.parts:
        raise ValueError(f"patch header path escapes workspace: {raw!r}")
    return posix.as_posix()


def _patch_header_paths(patch_text: str) -> set[str]:
    """Return file paths mentioned by ``---`` / ``+++`` patch headers."""
    paths: set[str] = set()
    for line in patch_text.splitlines():
        if not (line.startswith("--- ") or line.startswith("+++ ")):
            continue
        normalized = _normalize_patch_header_path(line[4:])
        if normalized is not None:
            paths.add(normalized)
    return paths


def _validate_single_file_patch(
    workspace: Path,
    target: Path,
    patch_text: str,
) -> dict[str, Any] | None:
    """Return an error dict if ``patch_text`` edits anything but target."""
    try:
        patch_paths = _patch_header_paths(patch_text)
    except ValueError as exc:
        return {
            "status": "error",
            "error_type": "invalid_patch_path",
            "error_message": str(exc),
            "context_echo": None,
        }
    expected = _workspace_relative_path(workspace, target)
    if patch_paths and patch_paths != {expected}:
        return {
            "status": "error",
            "error_type": "path_mismatch",
            "error_message": (
                f"patch headers target {sorted(patch_paths)!r}, but tool path is "
                f"{expected!r}. apply_patch only accepts single-file patches "
                "for the declared path."
            ),
            "context_echo": None,
        }
    return None


def _extract_context_echo(
    workspace: Path, path: str, patch_text: str
) -> dict[str, Any] | None:
    """On a patch context_mismatch, read the file at the first hunk's
    expected range and return ``{path, start_line, end_line, content}``.

    Returns None if we can't parse the hunk header or read the file.
    """
    target = _resolve_in_workspace(workspace, path)
    if target is None or not target.exists() or not target.is_file():
        return None
    match = _HUNK_HEADER.search(patch_text)
    if not match:
        return None
    start = int(match.group(1))
    length = int(match.group(2) or "1")
    if length == 0:
        length = 1
    end = start + length - 1
    file_lines = target.read_text().split("\n")
    if start < 1 or start > len(file_lines):
        return None
    end = min(end, len(file_lines))
    snippet = "\n".join(file_lines[start - 1 : end])
    return {
        "path": path,
        "start_line": start,
        "end_line": end,
        "content": snippet,
    }


def apply_patch(workspace: Path, path: str, patch: str) -> dict[str, Any]:
    """Apply a unified-diff patch via ``git apply``. Returns
    ``context_echo`` on context_mismatch."""
    target = _resolve_in_workspace(workspace, path)
    if target is None:
        return {
            "status": "error",
            "error_type": "invalid_path",
            "error_message": f"path '{path}' escapes the workspace",
            "context_echo": None,
        }
    if not target.exists():
        return {
            "status": "error",
            "error_type": "file_not_found",
            "error_message": (
                f"file '{path}' not found. Use write_file to create new files."
            ),
            "context_echo": None,
        }
    patch_error = _validate_single_file_patch(workspace, target, patch)
    if patch_error is not None:
        return patch_error

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".patch", delete=False
    ) as patch_file:
        patch_file.write(patch)
        patch_path = patch_file.name

    try:
        check = subprocess.run(  # noqa: S603,S607 — git is on PATH
            ["git", "apply", "--check", patch_path],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check.returncode != 0:
            stderr = check.stderr.strip()
            if "patch does not apply" in stderr or "while searching for" in stderr:
                error_type = "context_mismatch"
                context_echo = _extract_context_echo(workspace, path, patch)
                if context_echo is not None:
                    msg = (
                        f"Patch context did not match at lines "
                        f"{context_echo['start_line']}-{context_echo['end_line']}. "
                        f"The file currently reads:\n{context_echo['content']}\n"
                        "Edit the patch to match this and retry."
                    )
                else:
                    msg = stderr or "patch context did not match"
                return {
                    "status": "error",
                    "error_type": error_type,
                    "error_message": msg,
                    "context_echo": context_echo,
                }
            return {
                "status": "error",
                "error_type": "invalid_patch",
                "error_message": stderr or "git apply --check failed",
                "context_echo": None,
            }

        apply_proc = subprocess.run(  # noqa: S603,S607
            ["git", "apply", patch_path],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if apply_proc.returncode != 0:
            return {
                "status": "error",
                "error_type": "invalid_patch",
                "error_message": apply_proc.stderr.strip()
                or "git apply failed after passing --check",
                "context_echo": None,
            }
        return {"status": "ok", "path": path, "patch_applied": True}
    finally:
        Path(patch_path).unlink(missing_ok=True)


def run_bash(
    workspace: Path,
    command: str,
    *,
    timeout_sec: int = 30,
) -> dict[str, Any]:
    """Run a bash command in the sandbox. Returns stdout/stderr/exit_code/
    duration_ms. Capped at 120s."""
    timeout_sec = min(max(1, timeout_sec), 120)
    started = time.monotonic()
    try:
        proc = run_in_sandbox(workspace, command, timeout_sec=timeout_sec)
        duration_ms = int((time.monotonic() - started) * 1000)
        return {
            "status": "ok",
            "stdout": proc.stdout[-_STDOUT_LIMIT:],
            "stderr": proc.stderr[-_STDERR_LIMIT:],
            "exit_code": proc.returncode,
            "duration_ms": duration_ms,
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        out = exc.stdout or b""
        err = exc.stderr or b""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return {
            "status": "error",
            "error_type": "timeout",
            "error_message": f"command timed out after {timeout_sec}s",
            "stdout": out[-_STDOUT_LIMIT:],
            "stderr": err[-_STDERR_LIMIT:],
            "duration_ms": duration_ms,
        }


def grep_search(
    workspace: Path,
    pattern: str,
    *,
    path: str = ".",
    file_glob: str | None = None,
    context_lines: int = 2,
) -> dict[str, Any]:
    """Search using ripgrep (or ``grep -rn`` fallback)."""
    context_lines = max(0, min(context_lines, 10))
    target = _resolve_in_workspace(workspace, path)
    if target is None:
        return {
            "status": "error",
            "error_type": "invalid_path",
            "error_message": f"path '{path}' escapes the workspace",
        }

    rg_path = shutil.which("rg")
    if rg_path:
        cmd: list[str] = ["rg", "-n", "-C", str(context_lines), pattern, str(target)]
        if file_glob:
            cmd += ["-g", file_glob]
    else:
        cmd = ["grep", "-rn", f"-C{context_lines}", "-E"]
        if file_glob:
            cmd.append(f"--include={file_glob}")
        cmd += [pattern, str(target)]

    proc = subprocess.run(  # noqa: S603 — controlled command
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    matches = proc.stdout[-_GREP_OUTPUT_LIMIT:]
    return {
        "status": "ok",
        "matches": matches,
        "match_count": matches.count("\n"),
        "exit_code": proc.returncode,
        "command": " ".join(cmd),
    }


def task_complete() -> dict[str, Any]:
    """Sentinel — signals task is done. No-op return."""
    return {"status": "ok", "signal": "task_complete"}


# ──────────────────────────────────────────────────────────────────────
# Dispatch.
# ──────────────────────────────────────────────────────────────────────


TOOL_DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "read_file": read_file,
    "write_file": write_file,
    "apply_patch": apply_patch,
    "run_bash": run_bash,
    "grep_search": grep_search,
    "task_complete": task_complete,
}


def execute_tool(name: str, workspace: Path, **kwargs: Any) -> dict[str, Any]:
    """Dispatch a tool call by name. ``task_complete`` ignores ``workspace``."""
    if name not in TOOL_DISPATCH:
        return {
            "status": "error",
            "error_type": "unknown_tool",
            "error_message": f"unknown tool: {name}",
        }
    fn = TOOL_DISPATCH[name]
    if name == "task_complete":
        return fn()
    return fn(workspace, **kwargs)
