"""Time-travel branch tests (BUILD_ORDER step 9)."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.meta_harness.branches import (  # noqa: E402
    cancel_branch,
    clear_branch_state,
    get_checkpoint_state,
    get_state_history,
    list_branches,
    reconstruct_trajectory,
    worktree_add,
)
from app.meta_harness.persistence import healthcheck, persistence_layer  # noqa: E402


def async_test(fn):
    """Run an async test body without relying on pytest-asyncio."""

    def _run():
        return asyncio.run(fn())

    return _run


class BranchTestState(TypedDict, total=False):
    iteration: int
    budget_remaining: int
    proposer_prior: str
    delay_s: float


async def _tick(state: BranchTestState) -> dict:
    delay = state.get("delay_s", 0.0)
    if delay:
        await asyncio.sleep(delay)
    return {
        "iteration": state.get("iteration", 0) + 1,
        "budget_remaining": state.get("budget_remaining", 0) - 1,
    }


def _route(state: BranchTestState) -> str:
    return "tick" if state.get("budget_remaining", 0) > 0 else "end"


def _build_graph(checkpointer=None):
    graph = StateGraph(BranchTestState)
    graph.add_node("tick", _tick)
    graph.add_edge(START, "tick")
    graph.add_conditional_edges("tick", _route, {"tick": "tick", "end": END})
    return graph.compile(checkpointer=checkpointer or MemorySaver())


async def _run_parent(graph, *, thread_id: str, budget: int = 2) -> None:
    await graph.ainvoke(
        {
            "iteration": 0,
            "budget_remaining": budget,
            "proposer_prior": "parent",
            "delay_s": 0.0,
        },
        config={"configurable": {"thread_id": thread_id}, "recursion_limit": 50},
    )


async def _checkpoint_after_first_tick(graph, thread_id: str) -> str:
    history = await get_state_history(graph, thread_id=thread_id)
    for record in history:
        if record.iteration == 1 and record.next == ("tick",):
            return record.checkpoint_id
    raise AssertionError("missing checkpoint after first tick")


async def _checkpoint_before_first_tick(graph, thread_id: str) -> str:
    history = await get_state_history(graph, thread_id=thread_id)
    for record in history:
        if record.iteration == 0 and record.next == ("tick",):
            return record.checkpoint_id
    raise AssertionError("missing checkpoint before first tick")


@pytest.fixture(autouse=True)
def _clean_branch_state():
    clear_branch_state()
    yield
    clear_branch_state()


@async_test
async def test_get_state_history_projects_checkpoints():
    graph = _build_graph()
    await _run_parent(graph, thread_id="history-root", budget=2)

    history = await get_state_history(graph, thread_id="history-root")

    assert len(history) >= 4
    assert all(record.thread_id == "history-root" for record in history)
    assert all(record.checkpoint_id for record in history)
    assert any(record.node == "tick" for record in history)
    assert history[0].iteration == 2
    assert history[0].values_summary["budget_remaining"] == 0


@async_test
async def test_worktree_add_creates_branch_and_applies_mods():
    graph = _build_graph()
    parent_thread_id = "fork-root"
    await _run_parent(graph, thread_id=parent_thread_id, budget=2)
    parent_checkpoint_id = await _checkpoint_after_first_tick(graph, parent_thread_id)

    metadata, task = await worktree_add(
        graph,
        run_id=parent_thread_id,
        parent_thread_id=parent_thread_id,
        parent_checkpoint_id=parent_checkpoint_id,
        mods={"proposer_prior": "forked-prior"},
        name="forked prior",
    )

    done, pending = await asyncio.wait({task}, timeout=3)
    assert not pending
    for finished in done:
        await finished

    assert metadata.status == "completed"
    assert metadata.parent_thread_id == parent_thread_id
    assert metadata.parent_checkpoint_id == parent_checkpoint_id
    assert metadata.mods == {"proposer_prior": "forked-prior"}

    final_state = await graph.aget_state(
        {"configurable": {"thread_id": metadata.thread_id}}
    )
    assert final_state.values["iteration"] == 2
    assert final_state.values["budget_remaining"] == 0
    assert final_state.values["proposer_prior"] == "forked-prior"

    state_at_parent = await get_checkpoint_state(
        graph,
        thread_id=parent_thread_id,
        checkpoint_id=parent_checkpoint_id,
    )
    assert state_at_parent["iteration"] == 1

    branches = list_branches(run_id=parent_thread_id)
    assert [b.thread_id for b in branches] == [metadata.thread_id]

    trajectory = reconstruct_trajectory(parent_thread_id)
    assert {node["thread_id"] for node in trajectory["threads"]} == {
        parent_thread_id,
        metadata.thread_id,
    }
    assert trajectory["edges"] == [
        {
            "source": parent_thread_id,
            "target": metadata.thread_id,
            "parent_checkpoint_id": parent_checkpoint_id,
        }
    ]


@async_test
async def test_two_branches_run_concurrently():
    graph = _build_graph()
    parent_thread_id = "concurrent-root"
    await _run_parent(graph, thread_id=parent_thread_id, budget=1)
    parent_checkpoint_id = await _checkpoint_before_first_tick(graph, parent_thread_id)

    started = time.monotonic()
    first, first_task = await worktree_add(
        graph,
        run_id=parent_thread_id,
        parent_thread_id=parent_thread_id,
        parent_checkpoint_id=parent_checkpoint_id,
        mods={"proposer_prior": "first", "delay_s": 0.4},
    )
    second, second_task = await worktree_add(
        graph,
        run_id=parent_thread_id,
        parent_thread_id=parent_thread_id,
        parent_checkpoint_id=parent_checkpoint_id,
        mods={"proposer_prior": "second", "delay_s": 0.4},
    )

    done, pending = await asyncio.wait({first_task, second_task}, timeout=2)
    elapsed = time.monotonic() - started
    assert not pending
    for finished in done:
        await finished

    assert elapsed < 0.75, f"branches appear sequential; elapsed={elapsed:.3f}s"
    assert first.status == "completed"
    assert second.status == "completed"


@async_test
async def test_cancel_branch_marks_running_task_cancelled():
    graph = _build_graph()
    parent_thread_id = "cancel-root"
    await _run_parent(graph, thread_id=parent_thread_id, budget=1)
    parent_checkpoint_id = await _checkpoint_before_first_tick(graph, parent_thread_id)

    metadata, task = await worktree_add(
        graph,
        run_id=parent_thread_id,
        parent_thread_id=parent_thread_id,
        parent_checkpoint_id=parent_checkpoint_id,
        mods={"delay_s": 5.0},
    )

    await asyncio.sleep(0.05)
    cancelled = await cancel_branch(metadata.thread_id)

    assert cancelled.status == "cancelled"
    assert cancelled.cancelled_at is not None
    assert cancelled.finished_at is not None
    assert task.cancelled()


_PG_OK = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
    healthcheck()
)


@pytest.mark.skipif(
    not _PG_OK,
    reason="Postgres not reachable at configured DSN; bring up via docker compose",
)
@async_test
async def test_two_branches_complete_with_shared_async_postgres_saver():
    graph_id = f"pg-branches-{int(time.time() * 1000)}"
    async with persistence_layer() as saver:
        graph = _build_graph(checkpointer=saver)
        await _run_parent(graph, thread_id=graph_id, budget=1)
        parent_checkpoint_id = await _checkpoint_before_first_tick(graph, graph_id)

        first, first_task = await worktree_add(
            graph,
            run_id=graph_id,
            parent_thread_id=graph_id,
            parent_checkpoint_id=parent_checkpoint_id,
            mods={"proposer_prior": "pg-first", "delay_s": 0.1},
        )
        second, second_task = await worktree_add(
            graph,
            run_id=graph_id,
            parent_thread_id=graph_id,
            parent_checkpoint_id=parent_checkpoint_id,
            mods={"proposer_prior": "pg-second", "delay_s": 0.1},
        )

        done, pending = await asyncio.wait({first_task, second_task}, timeout=5)
        assert not pending
        for finished in done:
            await finished

        assert first.status == "completed"
        assert second.status == "completed"

        first_history = await get_state_history(graph, thread_id=first.thread_id)
        second_history = await get_state_history(graph, thread_id=second.thread_id)
        assert first_history[0].values_summary["proposer_prior"] == "pg-first"
        assert second_history[0].values_summary["proposer_prior"] == "pg-second"
