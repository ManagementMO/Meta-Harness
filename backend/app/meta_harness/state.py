"""LangGraph checkpoint-boundary state schemas."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class MetaHarnessState(TypedDict):
    """Outer-loop state. ``run_id`` doubles as the parent ``thread_id``."""

    run_id: str
    iteration: int
    budget_remaining: int
    candidates: list[dict[str, Any]]
    frontier: list[str]
    best_candidate: str | None
    proposer_prior: str
    active_candidate_ids: NotRequired[list[str]]
    best_candidate_id: NotRequired[str | None]
    parent_policy: NotRequired[str]
    mode: NotRequired[str]
    evaluation_policy: NotRequired[dict[str, Any]]
    random_seed: NotRequired[int | None]


class CodingAgentState(TypedDict):
    """Inner-loop state for the 5-phase coding agent."""

    task: dict[str, Any]
    workspace_path: str
    orient_summary: dict[str, Any] | None
    plan: dict[str, Any] | None
    messages: list[dict[str, Any]]
    turn_count: int
    verify_attempts: int
    verify_result: dict[str, Any] | None
    final_files: dict[str, str] | None
    score: float | None
    tool_events: NotRequired[list[dict[str, Any]]]
    telemetry: NotRequired[dict[str, Any]]
