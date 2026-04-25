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

# The meta-harness CLI imports ``agents.<n>`` dynamically at runtime.
# ``agents/`` lives at the repo root, so we add it to sys.path before
# importing anything that depends on it.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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
