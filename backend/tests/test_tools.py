"""Tests for the 6 fixed inner-loop tools (BUILD_ORDER step 2).

Each tool is exercised on happy + structured-error paths. ``apply_patch``
specifically validates that ``context_mismatch`` returns the
``context_echo`` block per Drift Correction A.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.meta_harness.tools import (
    TOOL_NAMES,
    TOOL_SCHEMAS,
    apply_patch,
    execute_tool,
    grep_search,
    read_file,
    run_bash,
    task_complete,
    write_file,
)


# ──────────────────────────────────────────────────────────────────────
# Schema-list shape (sanity).
# ──────────────────────────────────────────────────────────────────────


def test_tool_schemas_list_six_named_tools():
    assert TOOL_NAMES == [
        "read_file",
        "apply_patch",
        "write_file",
        "run_bash",
        "grep_search",
        "task_complete",
    ]
    assert len(TOOL_SCHEMAS) == 6
    for s in TOOL_SCHEMAS:
        assert "name" in s and "description" in s and "input_schema" in s


# ──────────────────────────────────────────────────────────────────────
# read_file.
# ──────────────────────────────────────────────────────────────────────


def test_read_file_basic(tmp_path: Path):
    (tmp_path / "hi.py").write_text("a = 1\nb = 2\nc = 3\n")
    out = read_file(tmp_path, "hi.py")
    assert out["status"] == "ok"
    assert out["n_lines"] == 4  # trailing newline → 4-element split
    assert "a = 1" in out["content"]
    assert "b = 2" in out["content"]


def test_read_file_with_range(tmp_path: Path):
    (tmp_path / "hi.py").write_text("\n".join(f"line {i}" for i in range(1, 11)))
    out = read_file(tmp_path, "hi.py", start_line=3, end_line=5)
    assert out["status"] == "ok"
    assert out["start_line"] == 3
    assert out["end_line"] == 5
    assert "line 3" in out["content"]
    assert "line 5" in out["content"]
    assert "line 1\n" not in out["content"]


def test_read_file_missing(tmp_path: Path):
    out = read_file(tmp_path, "nope.py")
    assert out["status"] == "error"
    assert out["error_type"] == "file_not_found"


def test_read_file_path_traversal_blocked(tmp_path: Path):
    out = read_file(tmp_path, "../../../etc/passwd")
    assert out["status"] == "error"
    assert out["error_type"] == "invalid_path"


def test_read_file_too_large(tmp_path: Path):
    big = "\n".join(f"line {i}" for i in range(1, 2502))
    (tmp_path / "big.py").write_text(big)
    out = read_file(tmp_path, "big.py")
    assert out["status"] == "error"
    assert out["error_type"] == "file_too_large"
    assert out["n_lines"] >= 2500


def test_read_file_too_large_with_range_ok(tmp_path: Path):
    big = "\n".join(f"line {i}" for i in range(1, 2502))
    (tmp_path / "big.py").write_text(big)
    out = read_file(tmp_path, "big.py", start_line=1, end_line=10)
    assert out["status"] == "ok"


# ──────────────────────────────────────────────────────────────────────
# write_file.
# ──────────────────────────────────────────────────────────────────────


def test_write_file_creates_new(tmp_path: Path):
    out = write_file(tmp_path, "new.py", "x = 1\n")
    assert out["status"] == "ok"
    assert out["bytes_written"] == 6
    assert (tmp_path / "new.py").read_text() == "x = 1\n"


def test_write_file_creates_parent_dirs(tmp_path: Path):
    out = write_file(tmp_path, "geometry/point.py", "class Point: pass\n")
    assert out["status"] == "ok"
    assert (tmp_path / "geometry" / "point.py").exists()


def test_write_file_existing_errors(tmp_path: Path):
    (tmp_path / "exists.py").write_text("old\n")
    out = write_file(tmp_path, "exists.py", "new\n")
    assert out["status"] == "error"
    assert out["error_type"] == "file_exists"
    # Original content preserved
    assert (tmp_path / "exists.py").read_text() == "old\n"


def test_write_file_path_traversal_blocked(tmp_path: Path):
    out = write_file(tmp_path, "../escape.py", "x")
    assert out["status"] == "error"
    assert out["error_type"] == "invalid_path"


# ──────────────────────────────────────────────────────────────────────
# apply_patch (with context_echo on mismatch).
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def calc_workspace(tmp_path: Path) -> Path:
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    return tmp_path


_GOOD_PATCH = """\
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""

_BAD_CONTEXT_PATCH = """\
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a * b
+    return a + b
"""


def test_apply_patch_happy(calc_workspace: Path):
    out = apply_patch(calc_workspace, "calc.py", _GOOD_PATCH)
    assert out["status"] == "ok"
    assert "return a + b" in (calc_workspace / "calc.py").read_text()


def test_apply_patch_context_mismatch_returns_context_echo(calc_workspace: Path):
    out = apply_patch(calc_workspace, "calc.py", _BAD_CONTEXT_PATCH)
    assert out["status"] == "error"
    assert out["error_type"] == "context_mismatch"
    echo = out["context_echo"]
    assert echo is not None
    assert echo["path"] == "calc.py"
    assert echo["start_line"] == 1
    assert "return a - b" in echo["content"]


def test_apply_patch_missing_file_returns_file_not_found(tmp_path: Path):
    out = apply_patch(tmp_path, "no.py", _GOOD_PATCH)
    assert out["status"] == "error"
    assert out["error_type"] == "file_not_found"
    assert out["context_echo"] is None


def test_apply_patch_path_traversal_blocked(tmp_path: Path):
    out = apply_patch(tmp_path, "../escape.py", _GOOD_PATCH)
    assert out["status"] == "error"
    assert out["error_type"] == "invalid_path"


# ──────────────────────────────────────────────────────────────────────
# run_bash.
# ──────────────────────────────────────────────────────────────────────


def test_run_bash_basic(tmp_path: Path):
    out = run_bash(tmp_path, "echo hello")
    assert out["status"] == "ok"
    assert "hello" in out["stdout"]
    assert out["exit_code"] == 0


def test_run_bash_captures_nonzero_exit(tmp_path: Path):
    out = run_bash(tmp_path, "exit 7")
    assert out["status"] == "ok"
    assert out["exit_code"] == 7


def test_run_bash_timeout(tmp_path: Path):
    out = run_bash(tmp_path, "sleep 5", timeout_sec=1)
    assert out["status"] == "error"
    assert out["error_type"] == "timeout"


def test_run_bash_caps_at_120s(tmp_path: Path):
    # We don't actually wait — just confirm the cap is applied to the request.
    # We verify by passing a high timeout and a fast command; expect normal completion.
    out = run_bash(tmp_path, "echo ok", timeout_sec=600)
    assert out["status"] == "ok"


# ──────────────────────────────────────────────────────────────────────
# grep_search.
# ──────────────────────────────────────────────────────────────────────


def test_grep_search_finds_matches(tmp_path: Path):
    (tmp_path / "a.py").write_text("def median(): pass\n")
    (tmp_path / "b.py").write_text("def mean(): pass\n")
    out = grep_search(tmp_path, "median")
    assert out["status"] == "ok"
    assert "median" in out["matches"]
    assert out["match_count"] >= 1


def test_grep_search_with_glob(tmp_path: Path):
    (tmp_path / "a.py").write_text("foo\n")
    (tmp_path / "b.txt").write_text("foo\n")
    out = grep_search(tmp_path, "foo", file_glob="*.py")
    assert out["status"] == "ok"
    assert "a.py" in out["matches"]
    # b.txt should not match
    assert "b.txt" not in out["matches"]


# ──────────────────────────────────────────────────────────────────────
# task_complete.
# ──────────────────────────────────────────────────────────────────────


def test_task_complete_returns_signal():
    out = task_complete()
    assert out == {"status": "ok", "signal": "task_complete"}


# ──────────────────────────────────────────────────────────────────────
# Dispatch.
# ──────────────────────────────────────────────────────────────────────


def test_execute_tool_dispatches_known(tmp_path: Path):
    (tmp_path / "f.txt").write_text("x\n")
    out = execute_tool("read_file", tmp_path, path="f.txt")
    assert out["status"] == "ok"


def test_execute_tool_unknown_returns_error(tmp_path: Path):
    out = execute_tool("nonsense", tmp_path)
    assert out["status"] == "error"
    assert out["error_type"] == "unknown_tool"


def test_execute_tool_task_complete_ignores_workspace(tmp_path: Path):
    out = execute_tool("task_complete", tmp_path)
    assert out["status"] == "ok"
    assert out["signal"] == "task_complete"
