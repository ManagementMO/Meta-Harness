"""Proposer node body — claude_wrapper.py-shaped.

Two paths:
- ``mock`` mode (BUILD_ORDER step 5): generates a deterministic stub
  candidate file for fast outer-loop testing, no LLM calls.
- ``claude`` mode (BUILD_ORDER step 6): spawns the ``claude`` CLI
  subprocess with the SKILL.md ``--append-system-prompt``'d, parses
  stream-json, parses the resulting agents/<name>.py + pending_eval.json.
  Mirrors Stanford's reference ``claude_wrapper.py`` shape.

This module is the body of the outer state machine's ``propose`` node
(per Correction 1 — the proposer is graph-internal, not a separate
tier).
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_MOCK_HARNESS_TEMPLATE = '''"""Mock candidate harness for outer-loop testing (iteration {iteration}).

Subclasses ``BaselineHarness`` with a hypothetical override that mock
benchmarking interprets as a pre-determined accuracy bump. Real
benchmark runs would actually exercise the override.
"""

from agents.baseline import BaselineHarness


class MockHarness_iter_{iteration}(BaselineHarness):
    """Mock candidate. Hypothesis: {hypothesis}"""

    HYPOTHESIS = {hypothesis_repr}
    EXPECTED_DELTA = {expected_delta}
'''


def mock_propose(
    *,
    run_dir: Path,
    iteration: int,
    parent_name: str | None,
    repo_root: Path,
) -> dict[str, Any]:
    """Generate a mock candidate. Writes the harness file under
    ``agents/_mock_iter_{N}.py`` and ``pending_eval.json`` under the run
    directory. Returns the pending_eval payload."""
    name = f"_mock_iter_{iteration}"
    hypothesis = f"mock hypothesis #{iteration}: pretend we tweaked something"
    expected_delta = 0.05

    harness_src = _MOCK_HARNESS_TEMPLATE.format(
        iteration=iteration,
        hypothesis=hypothesis,
        hypothesis_repr=repr(hypothesis),
        expected_delta=expected_delta,
    )

    agents_dir = repo_root / "agents"
    agents_dir.mkdir(exist_ok=True)
    harness_path = agents_dir / f"{name}.py"
    harness_path.write_text(harness_src)

    payload: dict[str, Any] = {
        "iteration": iteration,
        "candidates": [
            {
                "name": name,
                "import_path": f"agents.{name}:MockHarness_iter_{iteration}",
                "parent": parent_name,
                "hypothesis": hypothesis,
                "axis": "exploitation",
                "expected_score_delta": expected_delta,
            }
        ],
    }
    (run_dir / "pending_eval.json").write_text(json.dumps(payload, indent=2))

    sess_dir = run_dir / "proposer-sessions" / f"iter-{iteration}"
    sess_dir.mkdir(parents=True, exist_ok=True)
    (sess_dir / "session.json").write_text(
        json.dumps(
            {
                "mode": "mock",
                "iteration": iteration,
                "exit_code": 0,
                "duration_seconds": 0.0,
                "cost_usd": 0.0,
                "files_written": {f"agents/{name}.py": {"lines_written": harness_src.count("\\n")}},
            },
            indent=2,
        )
    )
    return payload


# ──────────────────────────────────────────────────────────────────────
# Real proposer: ``claude`` CLI subprocess, Stanford-shape.
# ──────────────────────────────────────────────────────────────────────


_PROPOSER_ALLOWED_TOOLS = ["Read", "Glob", "Grep", "Edit", "Write", "Bash"]


def _render_proposer_prompt(
    iteration: int, run_dir: Path, repo_root: Path, parent_name: str | None
) -> str:
    """Render the user-message prompt for the proposer subprocess."""
    rel_run = run_dir.resolve().relative_to(repo_root.resolve())
    parent_line = (
        f"Parent candidate: `agents/{parent_name}.py`. Read it, then evolve from it."
        if parent_name
        else "No parent yet — this is iteration 1. Read `agents/baseline.py` and evolve from it."
    )
    return (
        f"Run iteration {iteration} of the meta-harness coding-agent evolution loop.\n\n"
        f"## Run directory\n"
        f"All logs/results for this run are under `{rel_run}/`.\n"
        f"- `{rel_run}/evolution_summary.jsonl` — past candidates and scores.\n"
        f"- `{rel_run}/frontier_val.json` — current Pareto frontier.\n"
        f"- `{rel_run}/candidates/<name>/traces/` — per-trial inner-loop traces.\n"
        f"- Write `pending_eval.json` to: `{rel_run}/pending_eval.json`.\n\n"
        f"## Existing candidates\n"
        f"`agents/baseline.py` is the immutable starting point. {parent_line}\n"
        f"Your new candidate goes in `agents/<descriptive-snake-case-name>.py` and must\n"
        f"subclass `CodingAgentHarness` from `app.meta_harness.harness`.\n\n"
        f"Follow the meta-harness-coding-agent skill workflow exactly. Produce ONE\n"
        f"candidate. Self-critique before writing."
    )


def _build_claude_command(
    *,
    prompt: str,
    system_prompt: str,
    model: str = "opus",
    tools: list[str] | None = None,
    plugin_dir: Path,
) -> list[str]:
    """Build the ``claude`` CLI command list, mirroring Stanford's
    claude_wrapper.build_command()."""
    tools = tools or _PROPOSER_ALLOWED_TOOLS
    return [
        "claude",
        "--dangerously-skip-permissions",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--setting-sources",
        "",
        "--allowedTools",
        *tools,
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--plugin-dir",
        str(plugin_dir),
        "--append-system-prompt",
        system_prompt,
    ]


def _enqueue_lines(pipe, q: queue.Queue, stream_name: str) -> None:
    """Reader thread: push (stream_name, line) tuples to the queue."""
    try:
        for line in iter(pipe.readline, ""):
            q.put((stream_name, line))
    finally:
        pipe.close()


def claude_propose(
    *,
    run_dir: Path,
    iteration: int,
    parent_name: str | None,
    repo_root: Path,
    skill_path: Path,
    proposer_prior: str = "",
    timeout_seconds: int = 2400,
    model: str = "opus",
) -> dict[str, Any]:
    """Spawn the ``claude`` CLI subprocess with the SKILL.md
    ``--append-system-prompt``'d. Parse stream-json. Log
    session.json/transcript.txt/system_prompt.txt/events.jsonl. Read
    pending_eval.json that the proposer wrote. Return the parsed payload.

    Mirrors Stanford's reference ``claude_wrapper.run`` shape; uses
    subscription auth by stripping ``ANTHROPIC_API_KEY`` before exec.
    """
    sess_dir = run_dir / "proposer-sessions" / f"iter-{iteration}"
    sess_dir.mkdir(parents=True, exist_ok=True)

    # 1) Build the system prompt: SKILL.md + (optional) proposer_prior.
    skill_text = skill_path.read_text()
    system_prompt_parts = [f"## Skill: {skill_path.parent.name}\n{skill_text}"]
    if proposer_prior:
        system_prompt_parts.append(f"## Proposer prior\n{proposer_prior}")
    system_prompt = "Follow these skill instructions:\n\n" + "\n\n".join(
        system_prompt_parts
    )

    # 2) Build the user-message prompt.
    prompt = _render_proposer_prompt(iteration, run_dir, repo_root, parent_name)

    # 3) Empty plugin dir for hermeticity.
    empty_plugin_dir = run_dir / ".empty_plugins"
    empty_plugin_dir.mkdir(exist_ok=True)

    cmd = _build_claude_command(
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        plugin_dir=empty_plugin_dir,
    )

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    # Persist the exact prompt + system prompt for debugging.
    (sess_dir / "system_prompt.txt").write_text(system_prompt)
    (sess_dir / "user_prompt.txt").write_text(prompt)

    started = time.monotonic()
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    raw_events: list[dict[str, Any]] = []
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    tool_call_map: dict[str, dict[str, Any]] = {}
    files_read: dict[str, dict[str, int]] = {}
    files_written: dict[str, dict[str, int]] = {}
    token_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
    cost_usd = 0.0
    session_id = ""
    exit_code = 0

    try:
        proc = subprocess.Popen(  # noqa: S603 — controlled command
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(repo_root),
            env=env,
        )
        deadline = started + timeout_seconds
        q: queue.Queue = queue.Queue()
        threading.Thread(
            target=_enqueue_lines, args=(proc.stdout, q, "stdout"), daemon=True
        ).start()
        threading.Thread(
            target=_enqueue_lines, args=(proc.stderr, q, "stderr"), daemon=True
        ).start()

        while True:
            if time.monotonic() > deadline:
                proc.kill()
                stderr_lines.append(f"\n[timed out after {timeout_seconds}s]\n")
                exit_code = 124
                break
            try:
                stream, line = q.get(timeout=0.2)
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue
            if stream == "stdout":
                stdout_lines.append(line)
                try:
                    event = json.loads(line)
                    raw_events.append(event)
                    _accumulate_event(
                        event,
                        text_parts,
                        tool_calls,
                        tool_call_map,
                        token_usage,
                        files_read,
                        files_written,
                    )
                    if event.get("type") == "result":
                        session_id = event.get("session_id", session_id)
                        cost_usd = float(event.get("total_cost_usd", cost_usd) or 0.0)
                except (json.JSONDecodeError, ValueError):
                    pass
            else:
                stderr_lines.append(line)
        proc.wait()
        if exit_code == 0:
            exit_code = proc.returncode
    except FileNotFoundError as exc:
        stderr_lines.append(str(exc))
        exit_code = 127

    duration = time.monotonic() - started

    # 4) Persist logs.
    (sess_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e, default=str) for e in raw_events) + "\n"
    )
    (sess_dir / "transcript.txt").write_text("".join(text_parts))
    (sess_dir / "session.json").write_text(
        json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": "claude",
                "iteration": iteration,
                "model": model,
                "session_id": session_id,
                "exit_code": exit_code,
                "duration_seconds": round(duration, 2),
                "cost_usd": round(cost_usd, 4),
                "token_usage": token_usage,
                "command": cmd[:8] + ["...", "--append-system-prompt", "<skill>"],
                "cwd": str(repo_root),
                "skill": [
                    {"path": str(skill_path), "name": skill_path.parent.name}
                ],
                "files_read": files_read,
                "files_written": files_written,
                "tool_summary": [
                    f"{tc['name']}({_brief_tool_arg(tc.get('input', {}))})"
                    for tc in tool_calls
                ],
                "stderr": "".join(stderr_lines)[-2000:] if stderr_lines else "",
            },
            indent=2,
            default=str,
        )
    )

    if exit_code != 0:
        reason = " ".join(text_parts).strip() or "".join(stderr_lines).strip()
        reason_suffix = f": {reason[:300]}" if reason else ""
        raise RuntimeError(
            f"proposer subprocess failed (exit_code={exit_code}){reason_suffix}; "
            f"see {sess_dir}/session.json"
        )

    # 5) Read pending_eval.json that the proposer wrote.
    pending_path = run_dir / "pending_eval.json"
    if not pending_path.exists():
        raise RuntimeError(
            f"proposer exited 0 but did not write {pending_path}; "
            f"see {sess_dir}/transcript.txt"
        )
    return json.loads(pending_path.read_text())


def _accumulate_event(
    event: dict[str, Any],
    text_parts: list[str],
    tool_calls: list[dict[str, Any]],
    tool_call_map: dict[str, dict[str, Any]],
    token_usage: dict[str, int],
    files_read: dict[str, dict[str, int]],
    files_written: dict[str, dict[str, int]],
) -> None:
    """Update accumulators from one stream-json event."""
    etype = event.get("type")
    if etype == "assistant":
        msg = event.get("message", {})
        usage = msg.get("usage", {}) or {}
        token_usage["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
        token_usage["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
        for block in msg.get("content", []) or []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", "") + "\n")
            elif btype == "tool_use":
                tc = {
                    "name": block.get("name", ""),
                    "id": block.get("id", ""),
                    "input": block.get("input", {}) or {},
                }
                tool_calls.append(tc)
                tool_call_map[tc["id"]] = tc
                _track_file_op(tc, files_read, files_written)
    elif etype == "user":
        msg = event.get("message", {})
        for block in msg.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tid = block.get("tool_use_id", "")
                tc = tool_call_map.get(tid)
                if tc:
                    tc["output"] = str(block.get("content", ""))


def _track_file_op(
    tc: dict[str, Any],
    files_read: dict[str, dict[str, int]],
    files_written: dict[str, dict[str, int]],
) -> None:
    """Record file-read/write counts for the session log."""
    name = tc["name"]
    inp = tc.get("input", {}) or {}
    path = inp.get("file_path") or inp.get("path") or ""
    if not path:
        return
    if name in {"Read", "read_file"}:
        e = files_read.setdefault(path, {"reads": 0})
        e["reads"] += 1
    elif name in {"Write", "Edit", "write_file", "apply_patch"}:
        e = files_written.setdefault(path, {"writes": 0})
        e["writes"] += 1


def _brief_tool_arg(inp: dict[str, Any]) -> str:
    for key in ("file_path", "path", "command", "pattern", "description"):
        if key in inp:
            return f"{key}={str(inp[key])[:80]}"
    return ""
