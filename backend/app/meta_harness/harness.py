"""``CodingAgentHarness`` — base class with the 11 override points (the
search space).

Per Appendix C §C.9 / INTERFACES.md §4. The 6 fixed inner-loop tools
are not overridable. The default phase graph is replaceable only through
the explicit structural hook.

Candidates subclass ``CodingAgentHarness`` and override any subset of
the 11 marked points. Override 11 is the ``build_inner_graph()`` method,
which delegates to the fixed default graph unless a candidate replaces it.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import anthropic


_DEFAULT_SYSTEM_PROMPT = """\
You are a careful coding assistant. You have access to tools to read,
edit, and execute code in a sandboxed workspace. Solve the user's task
by:

1. Reading relevant files first — especially tests, when present.
2. Following the plan you were given.
3. Making targeted edits with apply_patch (preferred) or write_file
   (only for files that don't yet exist).
4. Running tests to verify your work.
5. Calling task_complete when you're confident the task is solved AND
   all tests pass.

Prefer minimal, surgical changes. Do not modify code unrelated to the
task. Use unified-diff patches that match the file's exact current
content; on context_mismatch, the tool returns the file's actual
content at the failed range — re-issue a corrected patch.
"""


_DEFAULT_PLAN_PROMPT_TEMPLATE = """\
You are about to solve a coding task. Build a structured plan first.

**Task:**
{instruction}

**Workspace tree (depth-limited):**
{tree}

**Project info:**
- Language: {lang}
- Test runner: {test_runner}

**Tests already in place (read these as a contract):**
{tests}

Call ``submit_plan`` now with:
- ``summary``: one-line description of what you'll do.
- ``steps``: ordered list of ``{{action, target, why}}`` entries.
- ``expected_files_changed``: which files you intend to touch.
- ``tests_to_run``: which tests to verify.
- ``risk_factors``: edge cases or gotchas to watch.
"""


PLAN_TOOL_SCHEMA: dict[str, Any] = {
    "name": "submit_plan",
    "description": "Submit your structured plan for the task.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "target": {"type": "string"},
                        "why": {"type": "string"},
                    },
                    "required": ["action", "target"],
                },
            },
            "expected_files_changed": {
                "type": "array",
                "items": {"type": "string"},
            },
            "tests_to_run": {
                "type": "array",
                "items": {"type": "string"},
            },
            "risk_factors": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["summary", "steps"],
    },
}


class HarnessTelemetry:
    def __init__(self) -> None:
        self.model_calls: list[dict[str, Any]] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_tokens = 0
        self.usage_available = True

    def record(
        self,
        response: Any,
        *,
        started_at: float,
        finished_at: float,
        error: str | None = None,
    ) -> None:
        usage = getattr(response, "usage", None) if response is not None else None
        if usage is None:
            self.usage_available = False
            input_tokens = output_tokens = cached_tokens = 0
        else:
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            cached_tokens = int(
                getattr(usage, "cache_read_input_tokens", 0) or 0
            ) + int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.cached_tokens += cached_tokens
        self.model_calls.append(
            {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_tokens": cached_tokens,
                "model": (
                    getattr(response, "model", None)
                    if response is not None
                    else None
                ),
                "wall_seconds": round(finished_at - started_at, 6),
                "error": error,
            }
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "model_calls": list(self.model_calls),
            "model_call_count": len(self.model_calls),
            "input_tokens": self.input_tokens if self.usage_available else None,
            "output_tokens": self.output_tokens if self.usage_available else None,
            "cached_tokens": self.cached_tokens if self.usage_available else None,
            "usage_available": self.usage_available,
        }


class CodingAgentHarness:
    """Base inner-loop harness. Override any of the marked points."""

    # Override 1 — system prompt
    SYSTEM_PROMPT: str = _DEFAULT_SYSTEM_PROMPT
    # Override 2 — plan prompt template
    PLAN_PROMPT_TEMPLATE: str = _DEFAULT_PLAN_PROMPT_TEMPLATE
    # Override 3 — turn budget for the act phase
    MAX_ACT_TURNS: int = 25
    # Override 4 — verify→act retry budget
    MAX_VERIFY_RETRIES: int = 3

    # Model knobs (not strict override points but candidates may tune).
    # Default = Haiku 4.5: rate-limit-friendly for parallel benchmarks,
    # ~10× cheaper than Sonnet, capable enough for the 5 calibration
    # tasks. Override with ``META_HARNESS_INNER_MODEL`` for Sonnet/Opus.
    MODEL: str = os.environ.get(
        "META_HARNESS_INNER_MODEL", "claude-haiku-4-5-20251001"
    )
    MAX_TOKENS: int = 4096

    def __init__(self, *, api_key: str | None = None) -> None:
        self.telemetry = HarnessTelemetry()
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to .env or export it "
                "before running the inner loop."
            )
        # Async client — required for use inside LangGraph async nodes
        # (see Appendix A §A.4 Gotcha 1: sync I/O inside async nodes
        # blocks the event loop). All node bodies in inner.py and
        # outer.py are async; ``_call_llm`` is awaited.
        self._client = anthropic.AsyncAnthropic(api_key=self.api_key)

    def _telemetry(self) -> HarnessTelemetry:
        telemetry = getattr(self, "telemetry", None)
        if not isinstance(telemetry, HarnessTelemetry):
            telemetry = HarnessTelemetry()
            self.telemetry = telemetry
        return telemetry

    async def call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        tool_choice: dict[str, Any] | None = None,
    ) -> Any:
        started_at = time.monotonic()
        try:
            response = await self._call_llm(
                messages,
                tools,
                tool_choice=tool_choice,
            )
        except Exception as exc:
            self._telemetry().record(
                None,
                started_at=started_at,
                finished_at=time.monotonic(),
                error=type(exc).__name__,
            )
            raise
        self._telemetry().record(
            response,
            started_at=started_at,
            finished_at=time.monotonic(),
        )
        return response

    # ──────────────────────────────────────────────────────────────────
    # Override points 5–10 (methods).
    # ──────────────────────────────────────────────────────────────────

    # Override 5
    def _build_initial_context(self, orient_summary: dict[str, Any]) -> dict[str, Any]:
        """Project orient_summary into the structure the planner sees."""
        return orient_summary

    # Override 6
    def _format_tool_result(self, name: str, result: dict[str, Any]) -> str:
        """How tool outputs are rendered back to the model."""
        formatted = json.dumps(result, indent=2, default=str)
        if len(formatted) > 4000:
            formatted = (
                formatted[:1500]
                + f"\n[... truncated {len(formatted) - 3000} chars ...]\n"
                + formatted[-1500:]
            )
        return formatted

    # Override 7
    def _compose_act_prompt(self, plan: dict[str, Any]) -> str:
        """How the plan is injected into the act phase's first user turn."""
        return (
            "Execute this plan. Use the tools to read, edit, and verify. "
            "Call task_complete when all tests pass.\n\n"
            f"{json.dumps(plan, indent=2)}"
        )

    # Override 8 — the actual API call (now async; see Appendix A §A.4)
    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        tool_choice: dict[str, Any] | None = None,
    ) -> Any:
        """The Anthropic API call. Override for caching, ordering, etc."""
        kwargs: dict[str, Any] = {}
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        return await self._client.messages.create(
            model=self.MODEL,
            max_tokens=self.MAX_TOKENS,
            messages=messages,
            tools=tools,
            system=self.SYSTEM_PROMPT,
            **kwargs,
        )

    # Override 9 — control whether to retry act after verify failure
    def should_loop_back_to_act(self, verify_result: dict[str, Any]) -> bool:
        """Default: loop back if tests didn't pass."""
        return not verify_result.get("tests_pass", False)

    # Override 10 — context-overflow strategy
    def _summarize_for_overflow(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """When messages would exceed model context, trim. Default: keep
        the first 2 (system framing) and the last 18 messages."""
        if len(messages) <= 20:
            return messages
        return (
            messages[:2]
            + [
                {
                    "role": "user",
                    "content": "[earlier turns elided to fit context]",
                }
            ]
            + messages[-18:]
        )

    def build_inner_graph(self, *, checkpointer: Any = None) -> Any:
        from app.meta_harness.inner import build_default_inner_graph

        return build_default_inner_graph(self, checkpointer=checkpointer)
