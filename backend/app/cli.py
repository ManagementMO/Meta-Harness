"""Meta-Harness CLI entry — ``meta-harness <subcommand>``.

Real subcommands land progressively across BUILD_ORDER steps. The
``meta-harness inner`` command (step 3) runs one inner-loop trial on a
single eval task. The ``loop``, ``benchmark``, ``fork``, ``resume``,
``init``, and ``memory`` subcommands land at later steps.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv

# The meta-harness CLI imports ``agents.<n>`` dynamically at runtime.
# ``agents/`` lives at the repo root, so we add it to sys.path before
# importing anything that depends on it.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load .env from the repo root so ANTHROPIC_API_KEY / POSTGRES_DSN are
# available before any subcommand instantiates a harness or a saver.
load_dotenv(REPO_ROOT / ".env")


app = typer.Typer(
    name="meta-harness",
    help="Meta-Harness — LangGraph-native substrate for self-improving agent harnesses.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Show the Meta-Harness version."""
    from app import __version__

    typer.echo(f"meta-harness {__version__}")


@app.command()
def inner(
    task: str = typer.Option(
        ...,
        "--task",
        help="Task id (e.g. task-001-fix-typo)",
    ),
    candidate: str = typer.Option(
        "baseline",
        "--candidate",
        help="Candidate harness module name under agents/ (default: baseline)",
    ),
    run_name: str = typer.Option(
        "inner-test",
        "--run-name",
        help="Run name for trace output dir (runs/{run_name}/...)",
    ),
    holdout: bool = typer.Option(
        False,
        "--holdout",
        help="Resolve task from eval/holdout/ instead of eval/tasks/",
    ),
) -> None:
    """Run ONE inner-loop trial on a single task (async)."""
    import asyncio
    import importlib

    from app.meta_harness.harness import CodingAgentHarness
    from app.meta_harness.inner import run_inner_loop
    from app.meta_harness.sandbox import sandbox_for

    eval_root = REPO_ROOT / "eval"
    task_dir = (eval_root / ("holdout" if holdout else "tasks")) / task
    if not task_dir.exists():
        typer.echo(f"task not found: {task_dir}", err=True)
        raise typer.Exit(1)
    task_spec = json.loads((task_dir / "task.json").read_text())

    if candidate == "baseline":
        from agents.baseline import BaselineHarness

        harness_class: type[CodingAgentHarness] = BaselineHarness
    else:
        try:
            mod = importlib.import_module(f"agents.{candidate}")
        except ImportError as exc:
            typer.echo(f"failed to import agents.{candidate}: {exc}", err=True)
            raise typer.Exit(1) from None
        cls = _find_harness_class(mod)
        if cls is None:
            typer.echo(
                f"agents.{candidate} does not export a CodingAgentHarness subclass",
                err=True,
            )
            raise typer.Exit(1)
        harness_class = cls

    harness = harness_class()

    trace_dir = (
        REPO_ROOT
        / "runs"
        / run_name
        / "candidates"
        / candidate
        / "traces"
        / f"{task}-trial-1"
    )

    async def _run() -> dict[str, Any]:
        with sandbox_for(task_dir / "workspace") as sandbox:
            final_state = await run_inner_loop(
                harness,
                task_dict=task_spec,
                workspace=sandbox,
                trace_dir=trace_dir,
            )
        return final_state

    final_state = asyncio.run(_run())

    typer.echo(
        json.dumps(
            {
                "task": task,
                "candidate": candidate,
                "score": final_state.get("score"),
                "passed": (final_state.get("score") or 0.0) >= 1.0,
                "turn_count": final_state.get("turn_count"),
                "verify_attempts": final_state.get("verify_attempts"),
                "trace_dir": str(trace_dir),
            },
            indent=2,
        )
    )


@app.command()
def benchmark(
    candidate: str = typer.Option(
        "baseline",
        "--candidate",
        help="Candidate harness module name under agents/",
    ),
    trials: int = typer.Option(
        5,
        "--trials",
        help="Trials per task (default: 5, matches Appendix C §C.11)",
    ),
    workers: int = typer.Option(
        5,
        "--workers",
        help="Parallel workers across (task × trial) tuples",
    ),
    run_name: str = typer.Option(
        None,
        "--run-name",
        help="Run dir under runs/. Auto-generated if omitted.",
    ),
    holdout: bool = typer.Option(
        False,
        "--holdout",
        help="Resolve tasks from eval/holdout/ instead of eval/tasks/",
    ),
) -> None:
    """Run a candidate × N trials × M tasks. Writes eval-result.json
    under runs/{run_name}/candidates/{candidate}/eval-result.json (async)."""
    import asyncio
    import datetime
    import importlib
    import time

    from app.meta_harness.harness import CodingAgentHarness
    from app.meta_harness.inner import run_inner_loop
    from app.meta_harness.sandbox import sandbox_for

    eval_root = REPO_ROOT / "eval"
    tasks_root = eval_root / ("holdout" if holdout else "tasks")
    task_dirs = sorted(d for d in tasks_root.iterdir() if d.is_dir() and (d / "task.json").exists())
    if not task_dirs:
        typer.echo(f"no tasks found in {tasks_root}", err=True)
        raise typer.Exit(1)

    if run_name is None:
        run_name = "bench-" + datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )

    if candidate == "baseline":
        from agents.baseline import BaselineHarness

        harness_class: type[CodingAgentHarness] = BaselineHarness
    else:
        try:
            mod = importlib.import_module(f"agents.{candidate}")
        except ImportError as exc:
            typer.echo(f"failed to import agents.{candidate}: {exc}", err=True)
            raise typer.Exit(1) from None
        cls = _find_harness_class(mod)
        if cls is None:
            typer.echo(
                f"agents.{candidate} does not export a CodingAgentHarness subclass",
                err=True,
            )
            raise typer.Exit(1)
        harness_class = cls

    work: list[tuple[Path, dict, int]] = []
    for task_dir in task_dirs:
        spec = json.loads((task_dir / "task.json").read_text())
        for trial_idx in range(1, trials + 1):
            work.append((task_dir, spec, trial_idx))

    typer.echo(
        f"benchmark: candidate={candidate}, tasks={len(task_dirs)}, "
        f"trials={trials}, total={len(work)}, workers={workers}, run={run_name}"
    )

    started = time.monotonic()
    results: dict[str, list[bool]] = {d.name: [False] * trials for d in task_dirs}

    sem = asyncio.Semaphore(workers)
    n_done = 0

    async def _one_trial(task_dir: Path, spec: dict, trial_idx: int) -> tuple[str, int, bool]:
        nonlocal n_done
        task_id = task_dir.name
        trace_dir = (
            REPO_ROOT
            / "runs"
            / run_name
            / "candidates"
            / candidate
            / "traces"
            / f"{task_id}-trial-{trial_idx}"
        )
        async with sem:
            harness = harness_class()
            with sandbox_for(task_dir / "workspace") as sandbox:
                final = await run_inner_loop(
                    harness,
                    task_dict=spec,
                    workspace=sandbox,
                    trace_dir=trace_dir,
                    thread_id=f"bench-{candidate}-{task_id}-trial-{trial_idx}",
                )
        passed = (final.get("score") or 0.0) >= 1.0
        n_done += 1
        mark = "✓" if passed else "✗"
        typer.echo(f"  [{n_done}/{len(work)}] {mark} {task_id} trial-{trial_idx}")
        return task_id, trial_idx, passed

    async def _run_all() -> list[tuple[str, int, bool]]:
        return await asyncio.gather(
            *[_one_trial(td, spec, t) for td, spec, t in work]
        )

    trial_results = asyncio.run(_run_all())
    for task_id, trial_idx, passed in trial_results:
        results[task_id][trial_idx - 1] = passed

    elapsed = time.monotonic() - started
    total_passes = sum(sum(v) for v in results.values())
    accuracy = total_passes / len(work) if work else 0.0

    eval_result = {
        "candidate": candidate,
        "n_tasks": len(task_dirs),
        "n_trials_per_task": trials,
        "accuracy": round(accuracy, 4),
        "per_task": {
            task_id: {
                "pass_rate": round(sum(trial_results) / len(trial_results), 4),
                "trials": trial_results,
            }
            for task_id, trial_results in results.items()
        },
        "tokens": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "cost_usd": 0.0,
        "wall_time_s": round(elapsed, 2),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    out_dir = REPO_ROOT / "runs" / run_name / "candidates" / candidate
    out_dir.mkdir(parents=True, exist_ok=True)
    eval_result_path = out_dir / "eval-result.json"
    eval_result_path.write_text(json.dumps(eval_result, indent=2))

    typer.echo("")
    typer.echo(json.dumps(eval_result, indent=2))
    typer.echo(f"\nwrote {eval_result_path}")


@app.command()
def loop(
    proposer: str = typer.Option(
        "claude",
        "--proposer",
        help="Proposer mode: 'claude' (real subprocess) or 'mock' (deterministic stub)",
    ),
    budget: int = typer.Option(
        5,
        "--budget",
        help="Number of outer-loop iterations",
    ),
    trials: int = typer.Option(
        5,
        "--trials",
        help="Trials per task during benchmark phase",
    ),
    workers: int = typer.Option(
        3,
        "--workers",
        help="Parallel workers for benchmark phase",
    ),
    fresh: bool = typer.Option(
        False,
        "--fresh",
        help="Wipe runs/<run-name>/ before starting",
    ),
    run_name: str = typer.Option(
        None,
        "--run-name",
        help="Run dir under runs/. Auto-generated if omitted.",
    ),
    domain: str = typer.Option(
        "coding-agent",
        "--domain",
        help="SKILL.md domain name (resolved to skills/meta-harness-<domain>/SKILL.md)",
    ),
    skill: str = typer.Option(
        None,
        "--skill",
        help="Override skill path (per INTERFACES.md §5.3)",
    ),
    mock_bench: bool = typer.Option(
        False,
        "--mock-bench",
        help=(
            "Synthesize scores instead of running the inner loop. Useful "
            "for fast outer-loop testing (BUILD_ORDER step 5 DoD)."
        ),
    ),
    holdout: bool = typer.Option(
        False,
        "--holdout",
        help="Use eval/holdout/ instead of eval/tasks/",
    ),
    persistent: bool = typer.Option(
        True,
        "--persistent/--no-persistent",
        help=(
            "Use AsyncPostgresSaver checkpointing (step 7). Disable to "
            "skip checkpoint persistence (in-memory; mock-test mode)."
        ),
    ),
) -> None:
    """Run the meta-harness outer loop (async).

    Step 5 DoD: ``meta-harness loop --proposer mock --mock-bench
    --budget 2 --fresh`` runs 2 iterations and writes
    pending_eval.json, frontier_val.json, evolution_summary.jsonl.
    Step 7 DoD: ``--persistent`` (default ON when POSTGRES_DSN
    resolves) checkpoints every transition; ``meta-harness resume
    <run-name>`` continues from the last checkpoint.
    """
    import asyncio
    import datetime as _dt

    from app.meta_harness.outer import run_outer_loop
    from app.meta_harness.persistence import persistence_layer
    from app.meta_harness.runs import make_run_dir

    if proposer not in {"claude", "mock"}:
        typer.echo(f"--proposer must be 'claude' or 'mock' (got {proposer!r})", err=True)
        raise typer.Exit(2)

    if run_name is None:
        run_name = "loop-" + _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    run_dir = make_run_dir(REPO_ROOT, run_name, fresh=fresh)
    eval_tasks_dir = REPO_ROOT / "eval" / ("holdout" if holdout else "tasks")

    skill_path: Path | None = None
    if proposer == "claude":
        if skill:
            sp = Path(skill)
            skill_path = sp if sp.is_absolute() else (REPO_ROOT / sp).resolve()
        else:
            skill_path = REPO_ROOT / "skills" / f"meta-harness-{domain}" / "SKILL.md"
        if not skill_path.exists():
            typer.echo(f"skill not found: {skill_path}", err=True)
            raise typer.Exit(2)

    async def _run() -> Any:
        from app.meta_harness.memory import memory_store as _mem_store

        if persistent:
            async with persistence_layer() as saver:
                try:
                    async with _mem_store() as mstore:
                        return await run_outer_loop(
                            run_dir=run_dir,
                            repo_root=REPO_ROOT,
                            eval_tasks_dir=eval_tasks_dir,
                            mock_proposer=(proposer == "mock"),
                            mock_bench=mock_bench,
                            trials=trials,
                            bench_workers=workers,
                            budget=budget,
                            skill_path=skill_path,
                            checkpointer=saver,
                            memory_store=mstore,
                        )
                except Exception:  # noqa: BLE001
                    # Fall back to no-memory if PostgresStore fails.
                    return await run_outer_loop(
                        run_dir=run_dir,
                        repo_root=REPO_ROOT,
                        eval_tasks_dir=eval_tasks_dir,
                        mock_proposer=(proposer == "mock"),
                        mock_bench=mock_bench,
                        trials=trials,
                        bench_workers=workers,
                        budget=budget,
                        skill_path=skill_path,
                        checkpointer=saver,
                    )
        return await run_outer_loop(
            run_dir=run_dir,
            repo_root=REPO_ROOT,
            eval_tasks_dir=eval_tasks_dir,
            mock_proposer=(proposer == "mock"),
            mock_bench=mock_bench,
            trials=trials,
            bench_workers=workers,
            budget=budget,
            skill_path=skill_path,
            checkpointer=None,
        )

    final_state = asyncio.run(_run())

    typer.echo(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "iterations_completed": final_state["iteration"],
                "budget_remaining": final_state["budget_remaining"],
                "best_candidate": final_state.get("best_candidate"),
                "n_candidates": len(final_state.get("candidates") or []),
                "frontier": final_state.get("frontier"),
                "persistent": persistent,
            },
            indent=2,
        )
    )


@app.command()
def resume(
    run_name: str = typer.Argument(..., help="Run name to resume (under runs/)"),
) -> None:
    """Resume an interrupted ``meta-harness loop`` run from its last
    Postgres checkpoint. Reconstructs the run config from
    ``runs/{run_name}/manifest.json`` and continues with the same
    proposer / mock_bench / trials settings.
    """
    import asyncio

    from app.meta_harness.outer import resume_outer_loop
    from app.meta_harness.persistence import persistence_layer

    run_dir = REPO_ROOT / "runs" / run_name
    if not run_dir.exists():
        typer.echo(f"run not found: {run_dir}", err=True)
        raise typer.Exit(1)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        typer.echo(f"manifest.json missing in {run_dir}; cannot resume", err=True)
        raise typer.Exit(1)

    eval_tasks_dir = REPO_ROOT / "eval" / "tasks"
    skill_path: Path | None = None
    skills_default = REPO_ROOT / "skills" / "meta-harness-coding-agent" / "SKILL.md"
    if skills_default.exists():
        skill_path = skills_default

    async def _run() -> Any:
        async with persistence_layer() as saver:
            return await resume_outer_loop(
                run_dir=run_dir,
                repo_root=REPO_ROOT,
                eval_tasks_dir=eval_tasks_dir,
                checkpointer=saver,
                skill_path=skill_path,
            )

    final_state = asyncio.run(_run())
    typer.echo(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "resumed": True,
                "iterations_completed": final_state["iteration"],
                "budget_remaining": final_state["budget_remaining"],
                "best_candidate": final_state.get("best_candidate"),
                "n_candidates": len(final_state.get("candidates") or []),
            },
            indent=2,
        )
    )


def _find_harness_class(mod) -> type | None:
    """Find the first ``CodingAgentHarness`` subclass exported by a module."""
    import inspect

    from app.meta_harness.harness import CodingAgentHarness

    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if (
            issubclass(obj, CodingAgentHarness)
            and obj is not CodingAgentHarness
            and obj.__module__ == mod.__name__
        ):
            return obj
    return None


# ── memory sub-app (step 8) ──────────────────────────────────────────

memory_app = typer.Typer(
    name="memory",
    help="Cross-run memory commands (PostgresStore).",
    no_args_is_help=True,
)
app.add_typer(memory_app, name="memory")


@memory_app.command("list")
def memory_list(
    namespace: str = typer.Option(
        "coding-agent",
        "--namespace",
        help="Domain namespace to list (e.g. 'coding-agent').",
    ),
    limit: int = typer.Option(50, "--limit", help="Max entries to return."),
) -> None:
    """List all learned patterns in a namespace."""
    import asyncio

    from app.meta_harness.memory import list_namespace, memory_store

    async def _run() -> list:
        async with memory_store() as store:
            return await list_namespace(store, domain=namespace, limit=limit)

    entries = asyncio.run(_run())
    if not entries:
        typer.echo(f"No patterns in namespace ('learned_patterns', '{namespace}').")
        return
    typer.echo(json.dumps(entries, indent=2, default=str))


def main() -> None:
    """Console-script entrypoint."""
    app()


if __name__ == "__main__":
    main()
