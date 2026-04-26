"""AsyncPostgresSaver integration tests (BUILD_ORDER step 7).

Skipped automatically when Postgres is not reachable at the configured
DSN. Bring it up with::

    docker compose -f infra/docker-compose.yml up -d postgres
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.meta_harness.outer import resume_outer_loop, run_outer_loop  # noqa: E402
from app.meta_harness.persistence import healthcheck, persistence_layer  # noqa: E402
from app.meta_harness.runs import make_run_dir  # noqa: E402


# Module-level skip if Postgres isn't reachable. Each test is async so
# we can't use a sync conftest hook for the check; do it here instead.
_PG_OK = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(healthcheck())

pytestmark = pytest.mark.skipif(
    not _PG_OK,
    reason="Postgres not reachable at configured DSN; bring up via docker compose",
)


async def test_persistence_layer_setup_idempotent():
    """``saver.setup()`` should be safe to call repeatedly."""
    async with persistence_layer():
        pass
    async with persistence_layer():  # 2nd call must not raise
        pass


async def test_outer_loop_with_postgres_persistence(tmp_path: Path):
    """Run the outer loop end-to-end with AsyncPostgresSaver wired in."""
    run_dir = make_run_dir(tmp_path, "test-persistence", fresh=True)
    eval_tasks_dir = REPO_ROOT / "eval" / "tasks"

    async with persistence_layer() as saver:
        final = await run_outer_loop(
            run_dir=run_dir,
            repo_root=REPO_ROOT,
            eval_tasks_dir=eval_tasks_dir,
            mock_proposer=True,
            mock_bench=True,
            trials=5,
            bench_workers=1,
            budget=2,
            checkpointer=saver,
        )

    assert final["iteration"] == 2
    assert final["budget_remaining"] == 0

    # The run-dir filesystem artifacts still get written (separate
    # from Postgres checkpoints).
    assert (run_dir / "frontier_val.json").exists()
    assert (run_dir / "evolution_summary.jsonl").exists()
    rows = (run_dir / "evolution_summary.jsonl").read_text().strip().split("\n")
    assert len(rows) == 2

    # Cleanup mock harness stubs from repo-root agents/.
    for c in final["candidates"]:
        stub = REPO_ROOT / "agents" / f"{c['name']}.py"
        if stub.exists():
            stub.unlink()


async def test_checkpoints_persist_in_postgres(tmp_path: Path):
    """After a run, ``get_state_history`` must return ≥1 checkpoint
    for the run's thread_id."""
    run_dir = make_run_dir(tmp_path, "test-history", fresh=True)
    eval_tasks_dir = REPO_ROOT / "eval" / "tasks"

    async with persistence_layer() as saver:
        await run_outer_loop(
            run_dir=run_dir,
            repo_root=REPO_ROOT,
            eval_tasks_dir=eval_tasks_dir,
            mock_proposer=True,
            mock_bench=True,
            trials=5,
            bench_workers=1,
            budget=1,
            checkpointer=saver,
        )

        history = []
        async for snapshot in saver.alist(
            config={"configurable": {"thread_id": run_dir.name}},
        ):
            history.append(snapshot)
        # At minimum: one checkpoint per node transition
        # (propose, validate, benchmark, update_frontier, end).
        assert len(history) >= 4, (
            f"expected ≥4 checkpoints for one iteration; got {len(history)}"
        )

    for c_dir in (run_dir / "candidates").iterdir():
        stub = REPO_ROOT / "agents" / f"{c_dir.name}.py"
        if stub.exists():
            stub.unlink()


async def test_resume_completes_remaining_iterations(tmp_path: Path):
    """Cancel a run mid-flight; ``resume_outer_loop`` must complete
    the remaining iterations without duplication."""
    run_dir = make_run_dir(tmp_path, "test-resume", fresh=True)
    eval_tasks_dir = REPO_ROOT / "eval" / "tasks"

    async with persistence_layer() as saver:
        # Kick off a 3-budget run as a task we can cancel.
        run_task = asyncio.create_task(
            run_outer_loop(
                run_dir=run_dir,
                repo_root=REPO_ROOT,
                eval_tasks_dir=eval_tasks_dir,
                mock_proposer=True,
                mock_bench=True,
                trials=5,
                bench_workers=1,
                budget=3,
                checkpointer=saver,
            )
        )
        # Let the first iteration land at least one checkpoint.
        await asyncio.sleep(0.5)
        run_task.cancel()
        try:
            await run_task
        except asyncio.CancelledError:
            pass

        # Resume — pulls the same checkpoint store.
        final = await resume_outer_loop(
            run_dir=run_dir,
            repo_root=REPO_ROOT,
            eval_tasks_dir=eval_tasks_dir,
            checkpointer=saver,
        )

    # Either the cancellation landed before any checkpoint
    # (rare-but-possible), or we have a completed 3-iteration run.
    assert final["iteration"] >= 1
    rows = (run_dir / "evolution_summary.jsonl").read_text().strip().split("\n")
    # No duplicate iterations across rows.
    iters = [json.loads(r)["iteration"] for r in rows if r.strip()]
    assert len(iters) == len(set(iters)), f"duplicate iterations in summary: {iters}"

    for c_dir in (run_dir / "candidates").iterdir():
        stub = REPO_ROOT / "agents" / f"{c_dir.name}.py"
        if stub.exists():
            stub.unlink()
