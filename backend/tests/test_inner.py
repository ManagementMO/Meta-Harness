"""Live inner-loop test on task-001 (BUILD_ORDER step 3 DoD).

Skipped automatically when ``ANTHROPIC_API_KEY`` is not set — the full
end-to-end test requires a real LLM call.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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


def test_verify_subprocess_uses_shared_sandbox_executor(monkeypatch, tmp_path: Path):
    from app.meta_harness import inner  # noqa: PLC0415

    calls: dict[str, object] = {}

    def fake_run_in_sandbox(workspace: Path, command: str, *, timeout_sec: int):
        calls.update(
            workspace=workspace,
            command=command,
            timeout_sec=timeout_sec,
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="tests passed",
            stderr="",
        )

    monkeypatch.setattr(inner, "run_in_sandbox", fake_run_in_sandbox)

    passed, output = inner._run_verify_subprocess(tmp_path, "pytest -q")

    assert passed is True
    assert output == "tests passed\n"
    assert calls == {
        "workspace": tmp_path,
        "command": "pytest -q",
        "timeout_sec": 60,
    }


async def test_plan_uses_initial_context_and_harness_llm_call():
    from app.meta_harness.harness import CodingAgentHarness  # noqa: PLC0415
    from app.meta_harness.inner import plan  # noqa: PLC0415

    class _Block:
        type = "tool_use"
        name = "submit_plan"
        input = {"summary": "use custom context", "steps": []}

    class _Response:
        content = [_Block()]

    class _Harness(CodingAgentHarness):
        PLAN_PROMPT_TEMPLATE = "{instruction}|{tree}|{lang}|{test_runner}|{tests}"
        seen_messages = None
        seen_tools = None
        seen_tool_choice = None

        def __init__(self) -> None:
            pass

        def _build_initial_context(self, orient_summary: dict) -> dict:
            return {
                "tree": "custom-tree",
                "project": {"lang": "custom-lang", "test_runner": "custom-test"},
                "tests": {"tests/test_contract.py": "assert True"},
            }

        async def _call_llm(self, messages, tools, *, tool_choice=None):
            self.seen_messages = messages
            self.seen_tools = tools
            self.seen_tool_choice = tool_choice
            return _Response()

    harness = _Harness()
    result = await plan(
        {
            "task": {"instruction": "solve it"},
            "orient_summary": {"tree": "raw-tree"},
        },
        harness,  # type: ignore[arg-type]
    )

    assert result["plan"]["summary"] == "use custom context"
    assert "custom-tree" in harness.seen_messages[0]["content"]
    assert "raw-tree" not in harness.seen_messages[0]["content"]
    assert harness.seen_tools[0]["name"] == "submit_plan"
    assert harness.seen_tool_choice == {"type": "tool", "name": "submit_plan"}


async def test_verify_failure_feedback_reaches_retry_as_provider_dicts(
    tmp_path: Path,
):
    from app.meta_harness.harness import CodingAgentHarness  # noqa: PLC0415
    from app.meta_harness.inner import run_inner_loop  # noqa: PLC0415

    class RetryHarness(CodingAgentHarness):
        MAX_ACT_TURNS = 4
        MAX_VERIFY_RETRIES = 2

        def __init__(self) -> None:
            self.act_messages: list[list[dict]] = []

        async def _call_llm(self, messages, tools, *, tool_choice=None):
            usage = SimpleNamespace(
                input_tokens=10,
                output_tokens=2,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            )
            if tools[0]["name"] == "submit_plan":
                block = SimpleNamespace(
                    type="tool_use",
                    name="submit_plan",
                    id="plan",
                    input={"summary": "solve", "steps": []},
                )
                return SimpleNamespace(content=[block], usage=usage)
            self.act_messages.append(messages)
            feedback = any(
                isinstance(message.get("content"), str)
                and "Verification failed" in message["content"]
                for message in messages
            )
            if feedback and not (tmp_path / "solved").exists():
                block = SimpleNamespace(
                    type="tool_use",
                    name="write_file",
                    id="write",
                    input={"path": "solved", "content": "ok"},
                )
            else:
                block = SimpleNamespace(
                    type="tool_use",
                    name="task_complete",
                    id="done",
                    input={},
                )
            return SimpleNamespace(content=[block], usage=usage)

    harness = RetryHarness()
    final = await run_inner_loop(
        harness,
        task_dict={
            "id": "retry-test",
            "instruction": "create solved",
            "test_command": "test -f solved",
            "runtime_adapter": "generic-command-v1",
        },
        workspace=tmp_path,
    )

    assert final["score"] == 1.0
    assert final["verify_attempts"] == 2
    assert all(
        isinstance(message, dict)
        for messages in harness.act_messages
        for message in messages
    )
    assert any(
        "Verification failed" in str(message.get("content"))
        for messages in harness.act_messages
        for message in messages
    )


async def test_structural_graph_override_is_invoked(tmp_path: Path):
    from app.meta_harness.harness import CodingAgentHarness  # noqa: PLC0415
    from app.meta_harness.inner import build_default_inner_graph, run_inner_loop  # noqa: PLC0415

    class StructuralHarness(CodingAgentHarness):
        def __init__(self) -> None:
            self.graph_calls = 0

        def build_inner_graph(self, *, checkpointer=None):
            self.graph_calls += 1
            return build_default_inner_graph(self, checkpointer=checkpointer)

        async def _call_llm(self, messages, tools, *, tool_choice=None):
            usage = SimpleNamespace(
                input_tokens=1,
                output_tokens=1,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            )
            if tools[0]["name"] == "submit_plan":
                block = SimpleNamespace(
                    type="tool_use",
                    name="submit_plan",
                    id="plan",
                    input={"summary": "verify", "steps": []},
                )
            else:
                block = SimpleNamespace(
                    type="tool_use",
                    name="task_complete",
                    id="done",
                    input={},
                )
            return SimpleNamespace(content=[block], usage=usage)

    harness = StructuralHarness()
    final = await run_inner_loop(
        harness,
        task_dict={
            "id": "structural-test",
            "instruction": "finish",
            "test_command": "true",
            "runtime_adapter": "generic-command-v1",
        },
        workspace=tmp_path,
    )

    assert final["score"] == 1.0
    assert harness.graph_calls == 1
    assert final["telemetry"]["model_call_count"] == 2


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
