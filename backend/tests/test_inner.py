"""Live inner-loop test on task-001 (BUILD_ORDER step 3 DoD).

Skipped automatically when ``ANTHROPIC_API_KEY`` is not set — the full
end-to-end test requires a real LLM call.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set; live LLM test skipped",
)


async def test_inner_loop_runs_end_to_end_on_task_001(tmp_path: Path):
    """Run the baseline harness on task-001 and assert all trace files exist."""
    from agents.baseline import BaselineHarness  # noqa: PLC0415

    from app.meta_harness.inner import run_inner_loop  # noqa: PLC0415
    from app.meta_harness.sandbox import sandbox_for  # noqa: PLC0415

    task_dir = REPO_ROOT / "eval" / "tasks" / "task-001-fix-typo"
    task_spec = json.loads((task_dir / "task.json").read_text())

    harness = BaselineHarness()
    trace_dir = tmp_path / "traces"

    with sandbox_for(task_dir / "workspace") as sandbox:
        final_state = await run_inner_loop(
            harness,
            task_dict=task_spec,
            workspace=sandbox,
            trace_dir=trace_dir,
        )

    # Score is one of {0.0, 1.0} — this is a per-trial pass/fail.
    assert final_state.get("score") in (0.0, 1.0)

    # Every trace artifact from INTERFACES.md §2.7-2.11 is present.
    for fname in (
        "orient.json",
        "plan.json",
        "act-messages.jsonl",
        "act-tools.jsonl",
        "verify.json",
        "score.json",
        "summary.md",
        "final-files.json",
    ):
        assert (trace_dir / fname).exists(), f"missing trace artifact: {fname}"
