"""``CodingAgentHarness`` — base class with the 11 override points (the
search space).

Per Appendix C §C.9 / INTERFACES.md §4. The 6 fixed inner-loop tools
and the 5 phase boundaries are NOT overridable; everything below is.

Candidates subclass ``CodingAgentHarness`` and override any subset of
the 11 marked points. Override 11 (structural) is implemented by
overriding ``build_inner_graph()`` in ``app.meta_harness.inner``.
"""

from __future__ import annotations

import json
import os
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

    # Model knobs (not strict override points but candidates may tune)
    MODEL: str = "claude-sonnet-4-6"
    MAX_TOKENS: int = 4096

    def __init__(self, *, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to .env or export it "
                "before running the inner loop."
            )
        self._client = anthropic.Anthropic(api_key=self.api_key)

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

    # Override 8 — the actual API call
    def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        """The Anthropic API call. Override for caching, ordering, etc."""
        return self._client.messages.create(
            model=self.MODEL,
            max_tokens=self.MAX_TOKENS,
            messages=messages,
            tools=tools,
            system=self.SYSTEM_PROMPT,
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

    # Override 11 (structural) is implemented by overriding the
    # build_inner_graph() function in app.meta_harness.inner; nothing to
    # define on the class itself.
