"""Sandbox lifecycle tests (BUILD_ORDER step 2)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.meta_harness.sandbox import (
    SANDBOX_PREFIX,
    cleanup_sandbox,
    make_sandbox_dir,
    populate_sandbox,
    run_in_sandbox,
    sandbox_for,
)


def test_make_sandbox_dir_creates_unique_temp_dir():
    a = make_sandbox_dir()
    b = make_sandbox_dir()
    try:
        assert a.exists() and a.is_dir()
        assert b.exists() and b.is_dir()
        assert a != b
        assert a.name.startswith(SANDBOX_PREFIX)
        assert str(a).startswith("/tmp/")
    finally:
        cleanup_sandbox(a)
        cleanup_sandbox(b)


def test_cleanup_sandbox_is_idempotent():
    sandbox = make_sandbox_dir()
    cleanup_sandbox(sandbox)
    assert not sandbox.exists()
    cleanup_sandbox(sandbox)  # second call must not raise


def test_populate_sandbox_copies_workspace(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("x = 1\n")
    (src / "tests").mkdir()
    (src / "tests" / "test_a.py").write_text("def test(): pass\n")

    sandbox = make_sandbox_dir()
    try:
        populate_sandbox(sandbox, src)
        assert (sandbox / "a.py").read_text() == "x = 1\n"
        assert (sandbox / "tests" / "test_a.py").exists()
    finally:
        cleanup_sandbox(sandbox)


def test_sandbox_for_context_manager_cleans_up(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text("hello\n")
    captured: Path | None = None
    with sandbox_for(src) as sb:
        captured = sb
        assert (sb / "f.txt").exists()
    assert captured is not None and not captured.exists()


def test_run_in_sandbox_captures_stdout_stderr_exit_code():
    sandbox = make_sandbox_dir()
    try:
        proc = run_in_sandbox(sandbox, "echo hello && echo err 1>&2 && exit 3")
        assert proc.returncode == 3
        assert "hello" in proc.stdout
        assert "err" in proc.stderr
    finally:
        cleanup_sandbox(sandbox)


def test_run_in_sandbox_enforces_timeout():
    sandbox = make_sandbox_dir()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run_in_sandbox(sandbox, "sleep 5", timeout_sec=1)
    finally:
        cleanup_sandbox(sandbox)
