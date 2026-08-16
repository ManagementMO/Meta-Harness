"""eval/score.py — score a workspace against a task's pytest contract.

Usage:
    python -m eval.score --task task-001-fix-typo
    python -m eval.score --task task-001-fix-typo --workspace /tmp/agent-output
    python -m eval.score --task task-006-... --holdout

When ``--workspace`` is omitted, the task's pristine workspace
(``eval/tasks/<id>/workspace/``) is copied to a temp directory and
scored as-is — this is what produces the baseline (failing) result for
unfixed tasks.

Returns: a JSON dict with task, passed, score, stdout (last 4000 chars),
stderr (last 2000 chars), exit_code. The script always exits 0; the JSON
is the result.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from app.meta_harness.runtime import get_runtime_adapter, load_task_spec

EVAL_ROOT = Path(__file__).resolve().parent
TASKS_DIR = EVAL_ROOT / "tasks"
HOLDOUT_DIR = EVAL_ROOT / "holdout"


def score_task(
    task_id: str,
    *,
    workspace_override: Path | None = None,
    holdout: bool = False,
    timeout_sec: int = 120,
) -> dict:
    """Run a task's tests and return a structured score dict."""
    task_dir = (HOLDOUT_DIR if holdout else TASKS_DIR) / task_id
    if not task_dir.exists():
        raise FileNotFoundError(f"task not found: {task_dir}")

    task_spec = load_task_spec(
        task_dir,
        visibility="holdout" if holdout else "search",
    )

    if workspace_override is None:
        with tempfile.TemporaryDirectory(prefix="meta-harness-eval-") as tmp:
            tmp_workspace = Path(tmp) / "workspace"
            shutil.copytree(task_dir / "workspace", tmp_workspace)
            return _run_in(tmp_workspace, task_spec.model_dump(mode="json"), timeout_sec)
    return _run_in(
        Path(workspace_override),
        task_spec.model_dump(mode="json"),
        timeout_sec,
    )


def _run_in(
    workspace: Path,
    task_spec: dict,
    timeout_sec: int = 120,
) -> dict:
    adapter = get_runtime_adapter(task_spec.get("runtime_adapter"))
    outcome = adapter.verify(
        workspace,
        task_spec,
        timeout_sec=timeout_sec,
    )
    return {
        "task": task_spec["id"],
        "passed": outcome.passed,
        "score": 1.0 if outcome.passed else 0.0,
        "exit_code": outcome.exit_code,
        "stdout": outcome.output[-4000:],
        "stderr": "",
        "timed_out": outcome.timed_out,
        "runtime_adapter": adapter.name,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="eval.score",
        description="Score a candidate workspace against a task's pytest contract.",
    )
    parser.add_argument("--task", required=True, help="task id (e.g. task-001-fix-typo)")
    parser.add_argument(
        "--workspace",
        help="override workspace dir (e.g. an agent's output dir). "
        "Omit to score the pristine task workspace as-is.",
    )
    parser.add_argument(
        "--holdout",
        action="store_true",
        help="resolve task from eval/holdout/ instead of eval/tasks/",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    workspace = Path(args.workspace) if args.workspace else None
    result = score_task(args.task, workspace_override=workspace, holdout=args.holdout)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
