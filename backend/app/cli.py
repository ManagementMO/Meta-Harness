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
    """Run ONE inner-loop trial on a single task.

    Imports ``agents.<candidate>`` dynamically; the module must define a
    subclass of ``CodingAgentHarness`` (or any class with the same shape).
    """
    import importlib

    from app.meta_harness.harness import CodingAgentHarness
    from app.meta_harness.inner import run_inner_loop
    from app.meta_harness.sandbox import sandbox_for

    # Resolve task spec + workspace
    eval_root = REPO_ROOT / "eval"
    task_dir = (eval_root / ("holdout" if holdout else "tasks")) / task
    if not task_dir.exists():
        typer.echo(f"task not found: {task_dir}", err=True)
        raise typer.Exit(1)
    task_spec = json.loads((task_dir / "task.json").read_text())

    # Resolve candidate harness class
    if candidate == "baseline":
        from agents.baseline import BaselineHarness

        harness_class: type[CodingAgentHarness] = BaselineHarness
    else:
        try:
            mod = importlib.import_module(f"agents.{candidate}")
        except ImportError as exc:
            typer.echo(f"failed to import agents.{candidate}: {exc}", err=True)
            raise typer.Exit(1) from None
        harness_class = _find_harness_class(mod)
        if harness_class is None:
            typer.echo(
                f"agents.{candidate} does not export a CodingAgentHarness subclass",
                err=True,
            )
            raise typer.Exit(1)

    harness = harness_class()

    # Set up trace dir + run inside a fresh sandbox
    trace_dir = (
        REPO_ROOT
        / "runs"
        / run_name
        / "candidates"
        / candidate
        / "traces"
        / f"{task}-trial-1"
    )

    with sandbox_for(task_dir / "workspace") as sandbox:
        final_state = run_inner_loop(
            harness,
            task_dict=task_spec,
            workspace=sandbox,
            trace_dir=trace_dir,
        )

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
    under runs/{run_name}/candidates/{candidate}/eval-result.json."""
    import datetime
    import importlib
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

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

    # Resolve candidate harness class once; each trial instantiates a
    # fresh harness so per-trial mutable state (e.g. the API client) is
    # not shared across concurrent threads.
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

    def _one_trial(task_dir: Path, spec: dict, trial_idx: int) -> tuple[str, int, bool]:
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
        harness = harness_class()
        with sandbox_for(task_dir / "workspace") as sandbox:
            final = run_inner_loop(
                harness,
                task_dict=spec,
                workspace=sandbox,
                trace_dir=trace_dir,
                thread_id=f"bench-{candidate}-{task_id}-trial-{trial_idx}",
            )
        passed = (final.get("score") or 0.0) >= 1.0
        return task_id, trial_idx, passed

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one_trial, td, spec, t) for td, spec, t in work]
        for n_done, fut in enumerate(as_completed(futures), start=1):
            task_id, trial_idx, passed = fut.result()
            results[task_id][trial_idx - 1] = passed
            mark = "✓" if passed else "✗"
            typer.echo(f"  [{n_done}/{len(work)}] {mark} {task_id} trial-{trial_idx}")

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


def main() -> None:
    """Console-script entrypoint."""
    app()


if __name__ == "__main__":
    main()
