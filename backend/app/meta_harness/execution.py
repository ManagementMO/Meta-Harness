"""Execution backend boundary shared by fixed and future recursive runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.meta_harness.harness import CodingAgentHarness
from app.meta_harness.inner import run_inner_loop


@dataclass(frozen=True)
class ChildBudget:
    max_depth: int = 0
    max_children: int = 0
    max_tokens: int = 0
    max_cost_usd: float = 0.0
    max_wall_seconds: float = 0.0
    max_concurrency: int = 0


class ExecutionBackend(Protocol):
    name: str

    async def execute(
        self,
        harness: CodingAgentHarness,
        *,
        task_dict: dict[str, Any],
        workspace: Path,
        trace_dir: Path,
        thread_id: str,
        checkpointer: Any,
        child_budget: ChildBudget,
    ) -> dict[str, Any]: ...


class FixedLangGraphBackend:
    name = "fixed-langgraph-v1"

    async def execute(
        self,
        harness: CodingAgentHarness,
        *,
        task_dict: dict[str, Any],
        workspace: Path,
        trace_dir: Path,
        thread_id: str,
        checkpointer: Any,
        child_budget: ChildBudget,
    ) -> dict[str, Any]:
        if child_budget.max_children or child_budget.max_depth:
            raise ValueError("fixed-langgraph-v1 does not admit child agents")
        return await run_inner_loop(
            harness,
            task_dict=task_dict,
            workspace=workspace,
            trace_dir=trace_dir,
            thread_id=thread_id,
            checkpointer=checkpointer,
        )


_BACKENDS: dict[str, ExecutionBackend] = {
    FixedLangGraphBackend.name: FixedLangGraphBackend(),
}


def register_execution_backend(backend: ExecutionBackend) -> None:
    if not backend.name:
        raise ValueError("execution backend name is required")
    _BACKENDS[backend.name] = backend


def get_execution_backend(name: str) -> ExecutionBackend:
    try:
        return _BACKENDS[name]
    except KeyError as exc:
        raise ValueError(f"execution backend is unavailable: {name}") from exc
