"""Proposer node body — claude_wrapper.py-shaped.

Two paths:
- ``mock`` mode (BUILD_ORDER step 5): generates a deterministic stub
  candidate file for fast outer-loop testing, no LLM calls.
- ``claude`` mode: spawns the ``claude`` CLI with the SKILL.md appended,
  parses stream-json, and reads a run-scoped proposal plus pending_eval.json.
  The outer loop materializes proposal bytes into immutable candidate bundles.

This module is the body of the outer state machine's ``propose`` node
(per Correction 1 — the proposer is graph-internal, not a separate
tier).
"""

from __future__ import annotations

import ast
import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.meta_harness.artifacts import atomic_write_json, atomic_write_text
from app.meta_harness.providers import (
    estimate_cost_usd,
    google_retry_delay,
    is_retryable_google_error,
    reserve_google_request,
)
from app.meta_harness.runs import validate_artifact_name


_MOCK_HARNESS_TEMPLATE = '''"""Mock candidate harness for outer-loop testing (iteration {iteration}).

Subclasses ``BaselineHarness`` with a hypothetical override that mock
benchmarking interprets as a pre-determined accuracy bump. Real
benchmark runs would actually exercise the override.
"""

from app.meta_harness.harness import CodingAgentHarness


class MockHarness_iter_{iteration}(CodingAgentHarness):
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
    """Generate a deterministic run-scoped candidate proposal."""
    name = f"_mock_iter_{iteration}"
    hypothesis = f"mock hypothesis #{iteration}: pretend we tweaked something"
    expected_delta = 0.05

    harness_src = _MOCK_HARNESS_TEMPLATE.format(
        iteration=iteration,
        hypothesis=hypothesis,
        hypothesis_repr=repr(hypothesis),
        expected_delta=expected_delta,
    )

    proposal_dir = run_dir / "proposals" / f"iter-{iteration}"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    harness_path = proposal_dir / f"{name}.py"
    harness_path.write_text(harness_src)
    try:
        source_path = harness_path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        source_path = str(harness_path.resolve())

    payload: dict[str, Any] = {
        "iteration": iteration,
        "candidates": [
            {
                "name": name,
                "source_path": source_path,
                "class_name": f"MockHarness_iter_{iteration}",
                "import_path": None,
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
                "cost_usd": None,
                "cost_measurement_status": "not_applicable",
                "synthetic": True,
                "files_written": {
                    source_path: {"lines_written": harness_src.count("\\n")}
                },
            },
            indent=2,
        )
    )
    return payload


class GeminiProposalResponse(BaseModel):
    name: str
    class_name: str
    source_code: str
    hypothesis: str
    axis: Literal["exploration", "exploitation"]
    expected_score_delta: float | None = Field(default=None, ge=-0.2, le=0.2)


def _bounded_evidence(
    *,
    run_dir: Path,
    parent_candidate_dir: Path,
    max_summary_chars: int = 16_000,
    max_trace_chars: int = 32_000,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "evolution_summary": "",
        "frontier": "",
        "raw_traces": [],
    }
    summary_path = run_dir / "evolution_summary.jsonl"
    if summary_path.exists():
        evidence["evolution_summary"] = summary_path.read_text()[-max_summary_chars:]
    frontier_path = run_dir / "frontier_val.json"
    if frontier_path.exists():
        evidence["frontier"] = frontier_path.read_text()[:max_summary_chars]
    traces_root = parent_candidate_dir / "traces"
    remaining = max_trace_chars
    if traces_root.exists():
        for path in sorted(
            item for item in traces_root.rglob("*") if item.is_file()
        ):
            if remaining <= 0 or path.suffix not in {
                ".json",
                ".jsonl",
                ".md",
                ".txt",
            }:
                continue
            content = path.read_text(errors="replace")[:remaining]
            evidence["raw_traces"].append(
                {
                    "path": path.relative_to(parent_candidate_dir).as_posix(),
                    "content": content,
                }
            )
            remaining -= len(content)
    return evidence


def gemini_propose(
    *,
    run_dir: Path,
    iteration: int,
    parent_name: str | None,
    repo_root: Path,
    skill_path: Path,
    parent_source_path: Path,
    parent_candidate_dir: Path,
    proposer_prior: str = "",
    model: str = "gemini-3.6-flash",
    seed: int | None = None,
) -> dict[str, Any]:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is required for the Gemini proposer")
    evidence = _bounded_evidence(
        run_dir=run_dir,
        parent_candidate_dir=parent_candidate_dir,
    )
    serialized_evidence = json.dumps(evidence, sort_keys=True).lower()
    if "eval/holdout" in serialized_evidence or "holdout-result" in serialized_evidence:
        raise RuntimeError("Gemini proposer evidence crossed the holdout boundary")
    parent_source = parent_source_path.read_text()
    system_prompt = (
        "You are the outer proposer in a controlled Meta-Harness research run. "
        "Return exactly one generalized CodingAgentHarness candidate through the "
        "provided JSON schema. Do not include task-specific filenames, task IDs, "
        "holdout knowledge, model changes, provider changes, or evaluator changes. "
        "Preserve the provider-agnostic call_llm boundary.\n\n"
        + skill_path.read_text()
    )
    prompt = (
        f"Iteration: {iteration}\n"
        f"Parent: {parent_name or 'baseline'}\n\n"
        "Parent candidate source:\n```python\n"
        f"{parent_source}\n```\n\n"
        "Bounded prior evidence from search tasks only:\n"
        f"{json.dumps(evidence, indent=2)}\n\n"
        f"Run-local proposer prior:\n{proposer_prior or '(none)'}\n\n"
        "Diagnose a recurring mechanism from the evidence, then produce one compact "
        "candidate source module. Override at most three documented harness hooks."
    )
    sess_dir = run_dir / "proposer-sessions" / f"iter-{iteration}"
    sess_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(sess_dir / "system_prompt.txt", system_prompt)
    atomic_write_text(sess_dir / "user_prompt.txt", prompt)
    started = time.monotonic()
    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_schema=GeminiProposalResponse,
        max_output_tokens=16_384,
        temperature=0.7,
        seed=seed,
        thinking_config=types.ThinkingConfig(
            thinking_level=types.ThinkingLevel.MEDIUM
        ),
    )
    response = None
    for attempt in range(5):
        try:
            time.sleep(reserve_google_request(model))
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            break
        except Exception as exc:
            if not is_retryable_google_error(exc) or attempt == 4:
                raise
            time.sleep(google_retry_delay(exc, attempt))
    if response is None:
        raise RuntimeError("Gemini proposer exhausted retries without a response")
    duration = time.monotonic() - started
    if isinstance(response.parsed, GeminiProposalResponse):
        proposal = response.parsed
    elif response.parsed is not None:
        proposal = GeminiProposalResponse.model_validate(response.parsed)
    elif response.text:
        proposal = GeminiProposalResponse.model_validate_json(response.text)
    else:
        raise RuntimeError("Gemini proposer returned no structured proposal")
    name = validate_artifact_name(proposal.name, kind="candidate")
    if not proposal.class_name.isidentifier():
        raise ValueError(f"invalid Gemini candidate class name: {proposal.class_name}")
    ast.parse(proposal.source_code, filename=f"{name}.py")
    proposal_dir = run_dir / "proposals" / f"iter-{iteration}"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    harness_path = proposal_dir / f"{name}.py"
    atomic_write_text(harness_path, proposal.source_code)
    try:
        source_path = harness_path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        source_path = str(harness_path.resolve())
    payload = {
        "schema_version": 1,
        "iteration": iteration,
        "candidates": [
            {
                "name": name,
                "source_path": source_path,
                "class_name": proposal.class_name,
                "parent": parent_name,
                "hypothesis": proposal.hypothesis,
                "axis": proposal.axis,
                "expected_score_delta": proposal.expected_score_delta,
            }
        ],
    }
    atomic_write_json(run_dir / "pending_eval.json", payload)
    usage = response.usage_metadata
    input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0) + int(
        getattr(usage, "thoughts_token_count", 0) or 0
    )
    cached_tokens = int(getattr(usage, "cached_content_token_count", 0) or 0)
    estimated_cost = estimate_cost_usd(
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
    )
    atomic_write_text(
        sess_dir / "transcript.txt",
        response.text or proposal.model_dump_json(indent=2),
    )
    atomic_write_json(
        sess_dir / "session.json",
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "gemini",
            "iteration": iteration,
            "model": str(response.model_version or model),
            "session_id": str(response.response_id or ""),
            "exit_code": 0,
            "duration_seconds": round(duration, 6),
            "token_usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_tokens": cached_tokens,
            },
            "token_usage_measurement_status": "measured",
            "estimated_cost_usd": estimated_cost[0] if estimated_cost else None,
            "estimated_cost_measurement_status": (
                "measured" if estimated_cost else "unknown"
            ),
            "estimated_cost_source": estimated_cost[1] if estimated_cost else None,
            "billed_cost_usd": None,
            "billed_cost_measurement_status": "unknown",
            "random_seed": seed,
            "synthetic": False,
            "evidence_access": [
                "bounded_evolution_summary",
                "frontier",
                "candidate_source",
                "bounded_raw_traces",
            ],
            "files_written": {
                source_path: {"lines_written": proposal.source_code.count("\n")}
            },
        },
    )
    return payload


# ──────────────────────────────────────────────────────────────────────
# Real proposer: ``claude`` CLI subprocess, Stanford-shape.
# ──────────────────────────────────────────────────────────────────────


_PROPOSER_ALLOWED_TOOLS = ["Read", "Glob", "Grep", "Edit", "Write", "Bash"]


def _render_proposer_prompt(
    iteration: int,
    run_dir: Path,
    repo_root: Path,
    parent_name: str | None,
    parent_source_path: str | None = None,
) -> str:
    """Render the user-message prompt for the proposer subprocess."""
    rel_run = run_dir.resolve().relative_to(repo_root.resolve())
    parent_line = (
        f"Parent candidate: `{parent_source_path}`. Read it, then evolve from it."
        if parent_name and parent_source_path
        else "No evaluated parent source was provided. Read `agents/baseline.py`."
    )
    proposal_dir = f"{rel_run}/proposals/iter-{iteration}"
    return (
        f"Run iteration {iteration} of the meta-harness coding-agent evolution loop.\n\n"
        f"## Run directory\n"
        f"All logs/results for this run are under `{rel_run}/`.\n"
        f"- `{rel_run}/evolution_summary.jsonl` — past candidates and scores.\n"
        f"- `{rel_run}/frontier_val.json` — current Pareto frontier.\n"
        f"- `{rel_run}/candidates/<candidate-id>/traces/` — per-trial traces.\n"
        f"- Write `pending_eval.json` to: `{rel_run}/pending_eval.json`.\n\n"
        f"## Existing candidates\n"
        f"`agents/baseline.py` is the checked-in seed. {parent_line}\n"
        f"Write the new source to `{proposal_dir}/<descriptive-name>.py`.\n"
        f"Register its repo-relative `source_path` and `class_name` in pending_eval.json.\n"
        f"It must subclass `CodingAgentHarness` from `app.meta_harness.harness`.\n\n"
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
    parent_source_path: str | None = None,
    research_mode: bool = True,
    timeout_seconds: int = 2400,
    model: str = "opus",
) -> dict[str, Any]:
    """Spawn the ``claude`` CLI subprocess with the SKILL.md
    ``--append-system-prompt``'d. Parse stream-json. Log
    session.json/transcript.txt/system_prompt.txt/events.jsonl. Read
    pending_eval.json that the proposer wrote. Return the parsed payload.

    Mirrors Stanford's reference ``claude_wrapper.run`` shape. The child
    inherits the configured Claude authentication environment explicitly.
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
    prompt = _render_proposer_prompt(
        iteration,
        run_dir,
        repo_root,
        parent_name,
        parent_source_path,
    )

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
    token_usage: dict[str, int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
    }
    token_usage_available = False
    cost_usd: float | None = None
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
                    if event.get("type") == "assistant" and (
                        event.get("message", {}).get("usage") is not None
                    ):
                        token_usage_available = True
                    if event.get("type") == "result":
                        session_id = event.get("session_id", session_id)
                        raw_cost = event.get("total_cost_usd")
                        if raw_cost is not None:
                            cost_usd = float(raw_cost)
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
                "cost_usd": round(cost_usd, 4) if cost_usd is not None else None,
                "cost_measurement_status": (
                    "measured" if cost_usd is not None else "unknown"
                ),
                "token_usage": token_usage if token_usage_available else None,
                "token_usage_measurement_status": (
                    "measured" if token_usage_available else "unknown"
                ),
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

    policy_violations = _research_policy_violations(tool_calls)
    if research_mode and policy_violations:
        (sess_dir / "policy-violations.json").write_text(
            json.dumps({"violations": policy_violations}, indent=2)
        )
        raise RuntimeError(
            "proposer violated research task visibility policy; "
            f"see {sess_dir}/policy-violations.json"
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
        token_usage["cached_tokens"] += int(
            usage.get("cache_read_input_tokens", 0) or 0
        ) + int(usage.get("cache_creation_input_tokens", 0) or 0)
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


def _research_policy_violations(
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for call in tool_calls:
        serialized = json.dumps(call.get("input", {}), sort_keys=True).lower()
        if "eval/holdout" in serialized or "holdout-result" in serialized:
            violations.append(
                {
                    "tool": str(call.get("name", "unknown")),
                    "reason": "holdout path or result access",
                }
            )
    return violations


def _brief_tool_arg(inp: dict[str, Any]) -> str:
    for key in ("file_path", "path", "command", "pattern", "description"):
        if key in inp:
            return f"{key}={str(inp[key])[:80]}"
    return ""
