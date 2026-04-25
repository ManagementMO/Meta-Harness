"""TypedDict state schemas + Candidate dataclass.

Verbatim from INTERFACES.md §1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages


@dataclass
class Candidate:
    """A candidate harness moving through the outer-loop pipeline."""

    name: str
    import_path: str
    parent: str | None
    hypothesis: str
    axis: Literal["exploration", "exploitation"]
    expected_score_delta: float | None
    iteration: int
    traces_dir: Path
    status: Literal[
        "pending", "smoke_failed", "evaluated", "rejected", "accepted"
    ] = "pending"
    scores: dict[str, Any] | None = None
    delta: float | None = None
    cost_usd: float | None = None


class MetaHarnessState(TypedDict):
    """Outer-loop state. ``run_id`` doubles as the parent ``thread_id``."""

    run_id: str
    iteration: int
    budget_remaining: int
    candidates: list[Candidate]
    frontier: list[str]
    best_candidate: str | None
    proposer_prior: str


class CodingAgentState(TypedDict):
    """Inner-loop state for the 5-phase coding agent."""

    task: dict[str, Any]
    workspace_path: str
    orient_summary: dict[str, Any] | None
    plan: dict[str, Any] | None
    messages: Annotated[list[Any], add_messages]
    turn_count: int
    verify_attempts: int
    verify_result: dict[str, Any] | None
    final_files: dict[str, str] | None
    score: float | None
