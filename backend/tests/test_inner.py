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

requires_anthropic = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set; live LLM test skipped",
)


def test_route_after_verify_uses_harness_retry_budget():
    from app.meta_harness.inner import _route_after_verify  # noqa: PLC0415

    state = {"verify_result": {"tests_pass": False}, "verify_attempts": 4}
    assert _route_after_verify(state, max_verify_retries=5) == "act"
    assert _route_after_verify(state, max_verify_retries=4) == "submit"
    assert _route_after_verify({"verify_result": {"tests_pass": True}}, 5) == "submit"


def test_route_after_verify_delegates_harness_policy():
    from app.meta_harness.harness import CodingAgentHarness  # noqa: PLC0415
    from app.meta_harness.inner import _route_after_verify_for_harness  # noqa: PLC0415

    class NoRetryHarness(CodingAgentHarness):
        MAX_VERIFY_RETRIES = 5

        def __init__(self) -> None:
            pass

        def should_loop_back_to_act(self, verify_result: dict) -> bool:
            return False

    state = {"verify_result": {"tests_pass": False}, "verify_attempts": 1}

    assert _route_after_verify_for_harness(state, NoRetryHarness()) == "submit"


async def test_plan_uses_harness_initial_context_override():
    from app.meta_harness.harness import CodingAgentHarness  # noqa: PLC0415
    from app.meta_harness.inner import plan  # noqa: PLC0415

    class FakeClient:
        seen_prompt = ""

        class Messages:
            async def create(self, **kwargs):
                FakeClient.seen_prompt = kwargs["messages"][0]["content"]

                class Block:
                    type = "tool_use"
                    name = "submit_plan"
                    input = {"steps": ["ok"]}

                class Response:
                    content = [Block()]

                return Response()

        messages = Messages()

    class ContextHarness(CodingAgentHarness):
        _client = FakeClient()

        def __init__(self) -> None:
            pass

        def _build_initial_context(self, orient_summary: dict) -> dict:
            return {
                "tree": "OVERRIDDEN_TREE",
                "project": {"lang": "python", "test_runner": "pytest"},
                "tests": {"test_custom.py": "def test_custom(): pass"},
            }

    state = {
        "task": {"instruction": "do it"},
        "orient_summary": {
            "tree": "ORIGINAL_TREE",
            "project": {"lang": "unknown", "test_runner": "unknown"},
            "tests": {},
        },
    }

    await plan(state, ContextHarness())

    assert "OVERRIDDEN_TREE" in FakeClient.seen_prompt
    assert "ORIGINAL_TREE" not in FakeClient.seen_prompt


@requires_anthropic
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
