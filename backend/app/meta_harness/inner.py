"""Inner-loop state machine: ``orient → plan → act → verify → submit``.

Per Appendix C §C.8 / INTERFACES.md §1.2. **All nodes are async** so
the inner graph can be checkpointed via ``AsyncPostgresSaver`` (step 7)
and forks can run concurrently via ``asyncio.create_task`` (step 9).

Node bodies still issue some sync subprocess calls (``find``, ``pytest``)
because their wall time is short and bounded; we accept the brief
event-loop block. Use ``asyncio.to_thread`` if a future change makes
these long-running.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.meta_harness.harness import PLAN_TOOL_SCHEMA, CodingAgentHarness
from app.meta_harness.state import CodingAgentState
from app.meta_harness.tools import TOOL_SCHEMAS, execute_tool

ACT_TOOLS = TOOL_SCHEMAS  # all 6 fixed tools incl. task_complete


# ──────────────────────────────────────────────────────────────────────
# Phase 1 — orient
# ──────────────────────────────────────────────────────────────────────


def _depth_limited_tree(workspace: Path, max_depth: int = 3) -> str:
    """Build a depth-limited workspace tree (best-effort, sync)."""
    try:
        proc = subprocess.run(
            [
                "find",
                ".",
                "-maxdepth",
                str(max_depth),
                "-not",
                "-path",
                "*/__pycache__/*",
                "-not",
                "-path",
                "*/.*",
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return proc.stdout
    except (subprocess.SubprocessError, OSError):
        return ""


async def orient(state: CodingAgentState, harness: CodingAgentHarness) -> dict[str, Any]:
    """Phase 1: build initial context for the planner."""
    workspace = Path(state["workspace_path"])
    tree = await asyncio.to_thread(_depth_limited_tree, workspace)

    has_python = (workspace / "pyproject.toml").exists() or any(
        workspace.rglob("*.py")
    )
    project_meta = {
        "lang": "python" if has_python else "unknown",
        "test_runner": "pytest" if has_python else "unknown",
    }

    tests: dict[str, str] = {}
    for test_file in list(workspace.rglob("test_*.py"))[:10]:
        if test_file.is_file():
            try:
                tests[str(test_file.relative_to(workspace))] = test_file.read_text()[
                    :4000
                ]
            except OSError:
                pass

    configs: dict[str, str] = {}
    for cfg_name in ["README.md", "pyproject.toml", "package.json", "Makefile"]:
        cfg_path = workspace / cfg_name
        if (
            cfg_path.exists()
            and cfg_path.is_file()
            and cfg_path.stat().st_size < 4000
        ):
            try:
                configs[cfg_name] = cfg_path.read_text()
            except OSError:
                pass

    summary = {
        "tree": tree[:2000],
        "project": project_meta,
        "configs": configs,
        "tests": tests,
    }

    trace_dir = _trace_dir_or_none(state)
    if trace_dir is not None:
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / "orient.json").write_text(json.dumps(summary, indent=2))

    return {"orient_summary": summary}


# ──────────────────────────────────────────────────────────────────────
# Phase 2 — plan
# ──────────────────────────────────────────────────────────────────────


async def plan(state: CodingAgentState, harness: CodingAgentHarness) -> dict[str, Any]:
    """Phase 2: produce a structured plan via forced tool call (async)."""
    orient_summary = state["orient_summary"] or {}
    summary = harness._build_initial_context(orient_summary)
    instruction = state["task"]["instruction"]

    prompt = harness.PLAN_PROMPT_TEMPLATE.format(
        instruction=instruction,
        tree=summary.get("tree", "")[:1500],
        lang=summary.get("project", {}).get("lang", "unknown"),
        test_runner=summary.get("project", {}).get("test_runner", "unknown"),
        tests=json.dumps(
            {k: v[:500] for k, v in summary.get("tests", {}).items()}, indent=2
        ),
    )

    messages = [{"role": "user", "content": prompt}]
    response = await harness._call_llm(
        messages=messages,
        tools=[PLAN_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "submit_plan"},
    )

    plan_dict: dict[str, Any] = {}
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_plan":
            plan_dict = dict(block.input)
            break

    trace_dir = _trace_dir_or_none(state)
    if trace_dir is not None:
        (trace_dir / "plan.json").write_text(json.dumps(plan_dict, indent=2))

    return {"plan": plan_dict}


# ──────────────────────────────────────────────────────────────────────
# Phase 3 — act (bounded ReAct, async)
# ──────────────────────────────────────────────────────────────────────


def _serialize_block(block: Any) -> dict[str, Any]:
    """Convert an Anthropic SDK content block into a plain dict."""
    btype = getattr(block, "type", None)
    if btype == "text":
        return {"type": "text", "text": block.text}
    if btype == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": dict(block.input),
        }
    return {"type": str(btype), "raw": str(block)}


async def act(state: CodingAgentState, harness: CodingAgentHarness) -> dict[str, Any]:
    """Phase 3: bounded ReAct over the 6 fixed tools (async)."""
    workspace = Path(state["workspace_path"])
    plan_dict = state["plan"] or {}
    trace_dir = _trace_dir_or_none(state)
    tool_log_path = (trace_dir / "act-tools.jsonl") if trace_dir else None

    messages = list(state.get("messages") or [])
    if not messages:
        messages.append(
            {"role": "user", "content": harness._compose_act_prompt(plan_dict)}
        )

    turn_count = state.get("turn_count", 0)
    act_complete = False

    while turn_count < harness.MAX_ACT_TURNS:
        if len(messages) > 40:
            messages = harness._summarize_for_overflow(messages)

        response = await harness._call_llm(messages, ACT_TOOLS)

        assistant_blocks: list[dict[str, Any]] = []
        tool_uses: list[Any] = []
        for block in response.content:
            assistant_blocks.append(_serialize_block(block))
            if getattr(block, "type", None) == "tool_use":
                tool_uses.append(block)

        messages.append({"role": "assistant", "content": assistant_blocks})

        if not tool_uses:
            break

        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            if tu.name == "task_complete":
                act_complete = True
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": "Task marked complete; running verify.",
                    }
                )
                if tool_log_path is not None:
                    _append_tool_log(
                        tool_log_path,
                        turn=turn_count + 1,
                        tool="task_complete",
                        tool_input={},
                        output_summary="complete",
                        is_error=False,
                    )
                continue

            # Tool dispatch is sync (subprocess-based). Wrap in
            # to_thread so we don't block the event loop on long
            # bash commands.
            result = await asyncio.to_thread(
                execute_tool, tu.name, workspace, **dict(tu.input)
            )
            formatted = harness._format_tool_result(tu.name, result)
            is_error = result.get("status") == "error"
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": formatted,
                    "is_error": is_error,
                }
            )
            if tool_log_path is not None:
                _append_tool_log(
                    tool_log_path,
                    turn=turn_count + 1,
                    tool=tu.name,
                    tool_input=dict(tu.input),
                    output_summary=formatted[:400],
                    is_error=is_error,
                )

        messages.append({"role": "user", "content": tool_results})
        turn_count += 1

        if act_complete:
            break

    if trace_dir is not None:
        msg_path = trace_dir / "act-messages.jsonl"
        with msg_path.open("w") as f:
            for m in messages:
                f.write(json.dumps(m, default=str) + "\n")

    return {"messages": messages, "turn_count": turn_count}


def _append_tool_log(
    path: Path,
    *,
    turn: int,
    tool: str,
    tool_input: dict[str, Any],
    output_summary: str,
    is_error: bool,
) -> None:
    entry = {
        "turn": turn,
        "tool": tool,
        "input": tool_input,
        "output_summary": output_summary,
        "is_error": is_error,
    }
    with path.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ──────────────────────────────────────────────────────────────────────
# Phase 4 — verify
# ──────────────────────────────────────────────────────────────────────


def _run_verify_subprocess(workspace: Path, test_command: str) -> tuple[bool, str]:
    """Sync helper for verify (called via asyncio.to_thread)."""
    try:
        proc = subprocess.run(  # noqa: S602 — test_command from task spec
            test_command,
            shell=True,
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        return proc.returncode == 0, (proc.stdout + "\n" + proc.stderr)[-2000:]
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout.decode("utf-8", "replace") if exc.stdout else "") + (
            exc.stderr.decode("utf-8", "replace") if exc.stderr else ""
        )
        return False, (out + "\n[timeout]")[-2000:]


async def verify(state: CodingAgentState, harness: CodingAgentHarness) -> dict[str, Any]:
    """Phase 4: run the task's test_command + persist verify.json."""
    workspace = Path(state["workspace_path"])
    test_command = state["task"].get("test_command", "pytest -q")

    tests_pass, output = await asyncio.to_thread(
        _run_verify_subprocess, workspace, test_command
    )

    verify_result = {
        "tests_pass": tests_pass,
        "tests_failed": [],
        "test_output": output,
        "lint_pass": True,
        "lint_errors": [],
        "out_of_plan_changes": [],
    }

    trace_dir = _trace_dir_or_none(state)
    if trace_dir is not None:
        (trace_dir / "verify.json").write_text(json.dumps(verify_result, indent=2))

    return {
        "verify_result": verify_result,
        "verify_attempts": state.get("verify_attempts", 0) + 1,
    }


# ──────────────────────────────────────────────────────────────────────
# Phase 5 — submit
# ──────────────────────────────────────────────────────────────────────


async def submit(state: CodingAgentState, harness: CodingAgentHarness) -> dict[str, Any]:
    """Phase 5: snapshot workspace, write score.json + summary.md +
    final-files.json."""
    workspace = Path(state["workspace_path"])
    verify_result = state.get("verify_result") or {}
    score = 1.0 if verify_result.get("tests_pass") else 0.0

    final_files: dict[str, str] = {}
    for f in workspace.rglob("*"):
        if f.is_file() and f.stat().st_size < 50_000:
            try:
                final_files[str(f.relative_to(workspace))] = f.read_text()
            except (OSError, UnicodeDecodeError):
                pass

    trace_dir = _trace_dir_or_none(state)
    if trace_dir is not None:
        (trace_dir / "final-files.json").write_text(
            json.dumps(final_files, indent=2)
        )
        (trace_dir / "score.json").write_text(
            json.dumps(
                {
                    "passed": bool(verify_result.get("tests_pass")),
                    "score": score,
                    "why": (
                        "all tests green"
                        if score == 1.0
                        else "tests failed after retries exhausted"
                    ),
                },
                indent=2,
            )
        )
        (trace_dir / "summary.md").write_text(
            f"""# Trial summary

- Task: {state["task"].get("id", "unknown")}
- Score: {score}
- Turns: {state.get("turn_count", 0)}
- Verify attempts: {state.get("verify_attempts", 0)}
- Tests pass: {verify_result.get("tests_pass", False)}
"""
        )

    return {"score": score, "final_files": final_files}


# ──────────────────────────────────────────────────────────────────────
# Routing + graph build + run
# ──────────────────────────────────────────────────────────────────────


def _route_after_verify(state: CodingAgentState, max_verify_retries: int = 3) -> str:
    """Conditional edge: loop back to act on test failure if budget remains."""
    verify_result = state.get("verify_result") or {}
    if verify_result.get("tests_pass", False):
        return "submit"
    if state.get("verify_attempts", 0) >= max_verify_retries:
        return "submit"
    return "act"


def _route_after_verify_for_harness(
    state: CodingAgentState, harness: CodingAgentHarness
) -> str:
    """Conditional edge using the harness' retry policy."""
    verify_result = state.get("verify_result") or {}
    if verify_result.get("tests_pass", False):
        return "submit"
    if state.get("verify_attempts", 0) >= harness.MAX_VERIFY_RETRIES:
        return "submit"
    return "act" if harness.should_loop_back_to_act(verify_result) else "submit"


def build_inner_graph(harness: CodingAgentHarness, *, checkpointer: Any = None) -> Any:
    """Compile the inner-loop ``StateGraph``. ``checkpointer`` is passed
    through to ``compile()``; ``None`` means no checkpointer (in-memory
    only, used by tests and by mock-bench).

    Wraps each phase function in an async closure that captures
    ``harness`` — sync lambdas would return coroutines without awaiting,
    which LangGraph rejects as ``InvalidUpdateError``.
    """

    async def _orient(s: CodingAgentState) -> dict[str, Any]:
        return await orient(s, harness)

    async def _plan(s: CodingAgentState) -> dict[str, Any]:
        return await plan(s, harness)

    async def _act(s: CodingAgentState) -> dict[str, Any]:
        return await act(s, harness)

    async def _verify(s: CodingAgentState) -> dict[str, Any]:
        return await verify(s, harness)

    async def _submit(s: CodingAgentState) -> dict[str, Any]:
        return await submit(s, harness)

    g: StateGraph = StateGraph(CodingAgentState)
    g.add_node("orient", _orient)
    g.add_node("plan", _plan)
    g.add_node("act", _act)
    g.add_node("verify", _verify)
    g.add_node("submit", _submit)

    g.add_edge(START, "orient")
    g.add_edge("orient", "plan")
    g.add_edge("plan", "act")
    g.add_edge("act", "verify")
    g.add_conditional_edges(
        "verify",
        lambda s: _route_after_verify_for_harness(s, harness),
        {"act": "act", "submit": "submit"},
    )
    g.add_edge("submit", END)
    return g.compile(checkpointer=checkpointer) if checkpointer else g.compile()


def _trace_dir_or_none(state: CodingAgentState) -> Path | None:
    raw = state["task"].get("_trace_dir")
    return Path(raw) if raw else None


async def run_inner_loop(
    harness: CodingAgentHarness,
    *,
    task_dict: dict[str, Any],
    workspace: Path,
    trace_dir: Path | None = None,
    thread_id: str = "inner-trial-1",
    checkpointer: Any = None,
) -> CodingAgentState:
    """Run one inner-loop trial. Async."""
    if trace_dir is not None:
        trace_dir.mkdir(parents=True, exist_ok=True)
        task_dict = dict(task_dict)
        task_dict["_trace_dir"] = str(trace_dir)

    initial_state: CodingAgentState = {
        "task": task_dict,
        "workspace_path": str(workspace),
        "orient_summary": None,
        "plan": None,
        "messages": [],
        "turn_count": 0,
        "verify_attempts": 0,
        "verify_result": None,
        "final_files": None,
        "score": None,
    }

    graph = build_inner_graph(harness, checkpointer=checkpointer)
    final_state = await graph.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": thread_id}, "recursion_limit": 100},
    )
    return final_state  # type: ignore[return-value]
