"""CLI smoke tests (BUILD_ORDER step 12).

These tests cover the typer subcommands without firing real LLM calls
or requiring Postgres beyond what the rest of the suite already needs.
The deeper integration coverage (live ``inner``, real ``loop`` with
the claude CLI) is exercised by ``test_inner.py`` and the demo
dry-run.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import app

REPO_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0, result.output
    assert "meta-harness" in result.output


def test_help_lists_all_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    for name in ("inner", "benchmark", "loop", "fork", "init", "resume", "memory", "version"):
        assert name in result.output, f"--help output missing subcommand: {name}"


def test_loop_mock_no_persistent_writes_artifacts(tmp_path: Path, monkeypatch) -> None:
    """``loop --proposer mock --mock-bench --no-persistent`` should run
    end-to-end and write the canonical artifacts."""
    # Run in the actual repo (not a temp root — agents/ + eval/tasks/
    # both live there), but use a fresh run_name under runs/.
    run_name = "test-cli-loop-" + tmp_path.name[-8:]
    result = runner.invoke(
        app,
        [
            "loop",
            "--proposer",
            "mock",
            "--mock-bench",
            "--budget",
            "1",
            "--fresh",
            "--no-persistent",
            "--run-name",
            run_name,
        ],
    )
    try:
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["iterations_completed"] == 1
        assert data["budget_remaining"] == 0
        run_dir = REPO_ROOT / "runs" / run_name
        assert (run_dir / "frontier_val.json").exists()
        assert (run_dir / "evolution_summary.jsonl").exists()
        assert (run_dir / "manifest.json").exists()
    finally:
        run_dir = REPO_ROOT / "runs" / run_name
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)
        for stub in (REPO_ROOT / "agents").glob("_mock_*.py"):
            stub.unlink()


def test_init_scaffolds_skill_md() -> None:
    """``init test-cli-domain`` must create skills/meta-harness-test-cli-domain/SKILL.md
    with renamed frontmatter."""
    domain = "test-cli-domain-" + str(abs(hash("seed")) % 100000)
    target_dir = REPO_ROOT / "skills" / f"meta-harness-{domain}"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    try:
        result = runner.invoke(app, ["init", domain])
        assert result.exit_code == 0, result.output
        skill_path = target_dir / "SKILL.md"
        assert skill_path.exists()
        first_lines = skill_path.read_text().splitlines()[:3]
        assert any(f"name: meta-harness-{domain}" in line for line in first_lines), (
            f"frontmatter name not rewritten: {first_lines}"
        )
        # Re-running without --force should error.
        result_again = runner.invoke(app, ["init", domain])
        assert result_again.exit_code != 0
        # With --force it should succeed.
        result_force = runner.invoke(app, ["init", domain, "--force"])
        assert result_force.exit_code == 0, result_force.output
    finally:
        if target_dir.exists():
            shutil.rmtree(target_dir)


def test_fork_unknown_run_errors_cleanly() -> None:
    """``fork`` on a missing run must exit non-zero with a clear error
    rather than crash."""
    result = runner.invoke(
        app,
        ["fork", "definitely-not-a-real-run-name", "--checkpoint", "x"],
    )
    assert result.exit_code != 0
    assert "run not found" in result.output


def test_fork_requires_mod_in_key_value_form() -> None:
    """``--mod`` without ``=`` must error with code 2."""
    # Use any run name; we'll fail at mod parsing before run-dir lookup
    # only if the run actually exists. Otherwise --mod check happens
    # after run-dir check. Test the path where the run dir exists:
    runs_dir = REPO_ROOT / "runs"
    runs_dir.mkdir(exist_ok=True)
    fake_run = runs_dir / "test-cli-fork-malformed-mod"
    fake_run.mkdir(exist_ok=True)
    (fake_run / "manifest.json").write_text("{}")
    try:
        result = runner.invoke(
            app,
            [
                "fork",
                fake_run.name,
                "--checkpoint",
                "x",
                "--mod",
                "no_equals_sign",
            ],
        )
        assert result.exit_code != 0
    finally:
        if fake_run.exists():
            shutil.rmtree(fake_run)


@pytest.mark.skipif(
    not (REPO_ROOT / "eval" / "holdout" / "task-006-fix-recursion").exists(),
    reason="holdout tasks not present",
)
def test_holdout_task_files_well_formed() -> None:
    """The two holdout tasks should have task.json + workspace/ + tests/."""
    for task in ("task-006-fix-recursion", "task-007-implement-stack"):
        task_dir = REPO_ROOT / "eval" / "holdout" / task
        assert (task_dir / "task.json").exists(), f"{task}/task.json missing"
        assert (task_dir / "workspace").is_dir(), f"{task}/workspace/ missing"
        spec = json.loads((task_dir / "task.json").read_text())
        assert spec["id"] == task
        assert "instruction" in spec
        assert "test_command" in spec
