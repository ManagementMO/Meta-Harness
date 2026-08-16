"""Meta-Harness command-line interface."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import sys
import threading
from pathlib import Path
from typing import Any

import typer
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
load_dotenv(REPO_ROOT / ".env")


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


app = typer.Typer(
    name="meta-harness",
    help="Artifact-backed research harness evolution and evaluation.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    from app import __version__

    typer.echo(f"meta-harness {__version__}")


def _find_harness_class(module: Any) -> type | None:
    from app.meta_harness.harness import CodingAgentHarness

    for _, value in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(value, CodingAgentHarness)
            and value is not CodingAgentHarness
            and value.__module__ == module.__name__
        ):
            return value
    return None


def _candidate_metadata(candidate: str) -> dict[str, Any]:
    if candidate == "baseline":
        return {
            "name": "baseline",
            "source_path": "agents/baseline.py",
            "class_name": "BaselineHarness",
            "import_path": "agents.baseline:BaselineHarness",
        }
    module = importlib.import_module(f"agents.{candidate}")
    candidate_class = _find_harness_class(module)
    if candidate_class is None:
        raise ValueError(f"agents.{candidate} has no CodingAgentHarness subclass")
    return {
        "name": candidate,
        "source_path": str(Path(module.__file__).resolve().relative_to(REPO_ROOT)),
        "class_name": candidate_class.__name__,
        "import_path": f"agents.{candidate}:{candidate_class.__name__}",
    }


def _policy(
    *,
    mode: str,
    visibility: str,
    trials: int,
    workers: int,
    inner_model: str | None,
    synthetic: bool,
    allow_global_memory: bool,
    random_seed: int | None = None,
):
    from app.meta_harness.artifacts import canonical_json_bytes, sha256_bytes
    from app.meta_harness.contracts import EvaluationPolicy, RunMode
    from app.meta_harness.harness import CodingAgentHarness
    from app.meta_harness.providers import provider_for_model

    model = inner_model or CodingAgentHarness.MODEL
    provider = provider_for_model(model)
    policy_identity = {
        "mode": mode,
        "visibility": visibility,
        "trials": trials,
        "workers": workers,
        "inner_model": model,
        "model_provider": provider,
        "synthetic": synthetic,
        "allow_global_memory": allow_global_memory,
    }
    return EvaluationPolicy(
        policy_id="cli_" + sha256_bytes(canonical_json_bytes(policy_identity))[:16],
        mode=RunMode(mode),
        task_visibility=visibility,
        runtime_adapter="task-declared",
        inner_model=model,
        model_provider=provider,
        trials=trials,
        workers=workers,
        allow_global_memory=allow_global_memory,
        random_seed=random_seed,
        synthetic=synthetic,
    )


def _write_cli_manifest(
    *,
    run_dir: Path,
    policy: Any,
    task_ids: list[str],
    status: str,
    best_candidate: str | None = None,
    best_candidate_id: str | None = None,
    error: str | None = None,
) -> None:
    from app.meta_harness.artifacts import atomic_write_json, sha256_file
    from app.meta_harness.contracts import RunManifest, RunMode
    from app.meta_harness.provenance import capture_git_state, capture_runtime_sha256

    git_commit, git_dirty = capture_git_state(REPO_ROOT)
    manifest = RunManifest(
        run_id=run_dir.name,
        mode=RunMode.RESEARCH,
        status=status,
        git_commit=git_commit,
        git_dirty=git_dirty,
        runtime_sha256=capture_runtime_sha256(REPO_ROOT),
        dependency_lock_sha256=(
            sha256_file(REPO_ROOT / "uv.lock")
            if (REPO_ROOT / "uv.lock").is_file()
            else None
        ),
        policy=policy,
        random_seed=policy.random_seed,
        search_task_ids=task_ids if policy.task_visibility == "search" else [],
        holdout_visible=policy.task_visibility == "holdout",
        persistence_backend="memory",
        synthetic=policy.synthetic,
        best_candidate=best_candidate,
        best_candidate_id=best_candidate_id,
        error=error,
    )
    atomic_write_json(run_dir / "manifest.json", manifest)


def _write_cli_evaluation_index(
    *,
    run_dir: Path,
    artifact: Any,
    evaluation: Any,
    iteration: int = 0,
) -> None:
    from app.meta_harness.artifacts import atomic_write_json
    from app.meta_harness import runs as runs_module

    accuracy = evaluation.accuracy.value
    total_tokens = None
    if (
        evaluation.usage.input_tokens.value is not None
        and evaluation.usage.output_tokens.value is not None
    ):
        total_tokens = (
            evaluation.usage.input_tokens.value
            + evaluation.usage.output_tokens.value
        )
    attempts = max(1, len(evaluation.task_results))
    avg_tokens = total_tokens / attempts if total_tokens is not None else None
    frontier = {
        "iteration": iteration,
        "candidates": [
            {
                "candidate_id": artifact.candidate_id,
                "name": artifact.name,
                "accuracy": accuracy,
                "avg_tokens": avg_tokens,
                "dominated_by_names": [],
                "synthetic": evaluation.synthetic,
            }
        ],
        "_pareto_names": [artifact.name],
        "_pareto_ids": [artifact.candidate_id],
        "_best": {
            "candidate_id": artifact.candidate_id,
            "name": artifact.name,
            "accuracy": accuracy,
            "avg_tokens": avg_tokens,
        },
        "per_task": {
            task_id: {
                "best_candidate": artifact.name,
                "best_candidate_id": artifact.candidate_id,
                "pass_rate": aggregate.pass_rate,
            }
            for task_id, aggregate in evaluation.per_task.items()
        },
    }
    runs_module.write_frontier(run_dir, frontier)
    runs_module.append_evolution_summary(
        run_dir,
        {
            "iteration": iteration,
            "candidate": artifact.name,
            "candidate_id": artifact.candidate_id,
            "artifact_path": (
                f"candidates/{artifact.candidate_id}/candidate.json"
            ),
            "parent_candidate_name": None,
            "parent_ids": artifact.parent_ids,
            "status": "best",
            "scores": {
                "accuracy": evaluation.accuracy.model_dump(mode="json"),
                "accuracy_value": accuracy,
                "per_task": {
                    key: value.model_dump(mode="json")
                    for key, value in evaluation.per_task.items()
                },
                "usage": evaluation.usage.model_dump(mode="json"),
                "synthetic": evaluation.synthetic,
            },
            "delta": None,
            "synthetic": evaluation.synthetic,
            "thread_id": run_dir.name,
        },
    )
    atomic_write_json(
        run_dir / "candidates" / artifact.candidate_id / "status.json",
        {
            "candidate": artifact.name,
            "candidate_id": artifact.candidate_id,
            "accepted": True,
            "parent": None,
            "parent_ids": artifact.parent_ids,
            "delta": None,
            "reason": "standalone-evaluation",
            "synthetic": evaluation.synthetic,
        },
    )


def _materialize_cli_candidate(
    *,
    run_dir: Path,
    candidate: str,
    policy: Any,
):
    from app.meta_harness.candidates import (
        load_candidate_artifact,
        materialize_candidate,
        resolve_candidate_id,
    )
    from app.meta_harness.provenance import capture_provenance

    try:
        candidate_id = resolve_candidate_id(run_dir, candidate)
    except (KeyError, ValueError):
        candidate_id = None
    if candidate_id:
        return load_candidate_artifact(run_dir, candidate_id)
    return materialize_candidate(
        run_dir=run_dir,
        repo_root=REPO_ROOT,
        metadata=_candidate_metadata(candidate),
        parent_ids=[],
        policy=policy,
        provenance=capture_provenance(
            REPO_ROOT,
            authorization_profile="trusted-local-cli",
        ),
    )


@app.command()
def inner(
    task: str = typer.Option(..., "--task"),
    candidate: str = typer.Option("baseline", "--candidate"),
    run_name: str = typer.Option("inner-test", "--run-name"),
    holdout: bool = typer.Option(False, "--holdout"),
    inner_model: str | None = typer.Option(None, "--inner-model"),
    seed: int | None = typer.Option(None, "--seed", min=0, max=2**31 - 2),
) -> None:
    from app.meta_harness.evaluator import Evaluator
    from app.meta_harness.runs import make_run_dir
    from app.meta_harness.runtime import load_task_spec

    visibility = "holdout" if holdout else "search"
    task_dir = REPO_ROOT / "eval" / visibility.replace("search", "tasks") / task
    if visibility == "holdout":
        task_dir = REPO_ROOT / "eval" / "holdout" / task
    if not task_dir.exists():
        typer.echo(f"task not found: {task_dir}", err=True)
        raise typer.Exit(1)
    run_dir = make_run_dir(REPO_ROOT, run_name, fresh=False)
    policy = _policy(
        mode="research",
        visibility=visibility,
        trials=1,
        workers=1,
        inner_model=inner_model,
        synthetic=False,
        allow_global_memory=False,
        random_seed=seed,
    )
    _write_cli_manifest(
        run_dir=run_dir,
        policy=policy,
        task_ids=[task],
        status="running",
    )
    artifact = _materialize_cli_candidate(
        run_dir=run_dir,
        candidate=candidate,
        policy=policy,
    )
    evaluator = Evaluator(
        run_dir=run_dir,
        repo_root=REPO_ROOT,
        policy=policy,
        phase=visibility,
    )
    try:
        evaluation = _run_async(
            evaluator.evaluate_candidate(
                artifact,
                [load_task_spec(task_dir, visibility=visibility)],
            )
        )
    except Exception as exc:
        _write_cli_manifest(
            run_dir=run_dir,
            policy=policy,
            task_ids=[task],
            status="failed",
            error=str(exc),
        )
        typer.echo(f"inner evaluation failed: {exc}", err=True)
        raise typer.Exit(2) from None
    result = evaluation.task_results[0]
    _write_cli_evaluation_index(
        run_dir=run_dir,
        artifact=artifact,
        evaluation=evaluation,
    )
    _write_cli_manifest(
        run_dir=run_dir,
        policy=policy,
        task_ids=[task],
        status="completed",
        best_candidate=artifact.name,
        best_candidate_id=artifact.candidate_id,
    )
    typer.echo(
        json.dumps(
            {
                "task": task,
                "candidate": artifact.name,
                "candidate_id": artifact.candidate_id,
                "score": result.score,
                "passed": result.passed,
                "usage": result.usage.model_dump(mode="json"),
                "failure_category": (
                    result.failure_category.value if result.failure_category else None
                ),
                "phase": visibility,
            },
            indent=2,
        )
    )


@app.command()
def benchmark(
    candidate: str = typer.Option("baseline", "--candidate"),
    trials: int = typer.Option(5, "--trials", min=1),
    workers: int = typer.Option(5, "--workers", min=1),
    run_name: str | None = typer.Option(None, "--run-name"),
    holdout: bool = typer.Option(False, "--holdout"),
    inner_model: str | None = typer.Option(None, "--inner-model"),
    seed: int | None = typer.Option(None, "--seed", min=0, max=2**31 - 2),
) -> None:
    import datetime

    from app.meta_harness.evaluator import Evaluator
    from app.meta_harness.runs import make_run_dir
    from app.meta_harness.runtime import discover_tasks

    visibility = "holdout" if holdout else "search"
    tasks_root = REPO_ROOT / "eval" / ("holdout" if holdout else "tasks")
    tasks = discover_tasks(tasks_root, visibility=visibility)
    if not tasks:
        typer.echo(f"no tasks found in {tasks_root}", err=True)
        raise typer.Exit(1)
    run_name = run_name or "bench-" + datetime.datetime.now(
        datetime.timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")
    run_dir = make_run_dir(REPO_ROOT, run_name, fresh=False)
    policy = _policy(
        mode="research",
        visibility=visibility,
        trials=trials,
        workers=workers,
        inner_model=inner_model,
        synthetic=False,
        allow_global_memory=False,
        random_seed=seed,
    )
    _write_cli_manifest(
        run_dir=run_dir,
        policy=policy,
        task_ids=[task.id for task in tasks],
        status="running",
    )
    artifact = _materialize_cli_candidate(
        run_dir=run_dir,
        candidate=candidate,
        policy=policy,
    )
    evaluator = Evaluator(
        run_dir=run_dir,
        repo_root=REPO_ROOT,
        policy=policy,
        phase=visibility,
    )
    try:
        evaluation = _run_async(evaluator.evaluate_candidate(artifact, tasks))
    except Exception as exc:
        _write_cli_manifest(
            run_dir=run_dir,
            policy=policy,
            task_ids=[task.id for task in tasks],
            status="failed",
            error=str(exc),
        )
        typer.echo(f"benchmark failed: {exc}", err=True)
        raise typer.Exit(2) from None
    _write_cli_evaluation_index(
        run_dir=run_dir,
        artifact=artifact,
        evaluation=evaluation,
    )
    _write_cli_manifest(
        run_dir=run_dir,
        policy=policy,
        task_ids=[task.id for task in tasks],
        status="completed",
        best_candidate=artifact.name,
        best_candidate_id=artifact.candidate_id,
    )
    typer.echo(json.dumps(evaluation.model_dump(mode="json"), indent=2))


def _validate_skill(path: Path) -> None:
    from app.meta_harness.skill_contract import validate_skill

    validate_skill(path)


@app.command()
def loop(
    proposer: str = typer.Option("claude", "--proposer"),
    budget: int = typer.Option(5, "--budget", min=1),
    trials: int = typer.Option(5, "--trials", min=1),
    workers: int = typer.Option(3, "--workers", min=1),
    fresh: bool = typer.Option(False, "--fresh"),
    run_name: str | None = typer.Option(None, "--run-name"),
    domain: str = typer.Option("coding-agent", "--domain"),
    skill: str | None = typer.Option(None, "--skill"),
    skill_dir: str | None = typer.Option(None, "--skill-dir"),
    mock_bench: bool = typer.Option(False, "--mock-bench"),
    holdout: bool = typer.Option(False, "--holdout"),
    persistent: bool = typer.Option(True, "--persistent/--no-persistent"),
    mode: str = typer.Option("research", "--mode"),
    parent_policy: str = typer.Option("best_accuracy", "--parent-policy"),
    inner_model: str | None = typer.Option(None, "--inner-model"),
    proposer_model: str | None = typer.Option(None, "--proposer-model"),
    seed: int | None = typer.Option(None, "--seed", min=0, max=2**31 - 2),
    max_act_turns: int = typer.Option(25, "--max-act-turns", min=1),
    max_verify_retries: int = typer.Option(3, "--max-verify-retries", min=0),
    global_memory: bool = typer.Option(
        False,
        "--global-memory/--no-global-memory",
    ),
) -> None:
    import datetime

    from app.meta_harness.contracts import RunMode
    from app.meta_harness.memory import memory_store as memory_store_context
    from app.meta_harness.outer import run_outer_loop
    from app.meta_harness.persistence import persistence_layer
    from app.meta_harness.reports import finalize_run
    from app.meta_harness.runs import make_run_dir

    if proposer not in {"claude", "gemini", "mock"}:
        raise typer.BadParameter("proposer must be 'claude', 'gemini', or 'mock'")
    resolved_inner_model = inner_model or (
        "gemini-3.1-flash-lite" if proposer == "gemini" else None
    )
    resolved_proposer_model = proposer_model or (
        "gemini-3.6-flash" if proposer == "gemini" else "opus"
    )
    try:
        resolved_mode = RunMode(mode)
    except ValueError as exc:
        raise typer.BadParameter("mode must be 'research' or 'autonomous'") from exc
    if resolved_mode == RunMode.RESEARCH and global_memory:
        raise typer.BadParameter("research mode forbids global memory")
    run_name = run_name or "loop-" + datetime.datetime.now(
        datetime.timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")
    run_dir = make_run_dir(REPO_ROOT, run_name, fresh=fresh)
    skill_path: Path | None = None
    if proposer in {"claude", "gemini"}:
        if skill and skill_dir:
            raise typer.BadParameter("use only one of --skill or --skill-dir")
        if skill_dir:
            skill_path = (REPO_ROOT / skill_dir / "SKILL.md").resolve()
        elif skill:
            raw = Path(skill)
            skill_path = raw if raw.is_absolute() else (REPO_ROOT / raw).resolve()
        else:
            skill_path = REPO_ROOT / "skills" / f"meta-harness-{domain}" / "SKILL.md"
        if not skill_path.exists():
            typer.echo(f"skill not found: {skill_path}", err=True)
            raise typer.Exit(2)
        try:
            _validate_skill(skill_path)
        except ValueError as exc:
            typer.echo(f"invalid skill: {exc}", err=True)
            raise typer.Exit(2) from None

    async def execute() -> Any:
        async def invoke(checkpointer=None, memory_store=None):
            return await run_outer_loop(
                run_dir=run_dir,
                repo_root=REPO_ROOT,
                eval_tasks_dir=REPO_ROOT / "eval" / "tasks",
                mock_proposer=proposer == "mock",
                mock_bench=mock_bench,
                trials=trials,
                bench_workers=workers,
                budget=budget,
                skill_path=skill_path,
                checkpointer=checkpointer,
                memory_store=memory_store,
                mode=resolved_mode,
                parent_policy=parent_policy,
                inner_model=resolved_inner_model,
                proposer_model=resolved_proposer_model,
                proposer_backend=proposer,
                random_seed=seed,
                max_act_turns=max_act_turns,
                max_verify_retries=max_verify_retries,
                allow_global_memory=global_memory,
            )

        if not persistent:
            return await invoke()
        async with persistence_layer() as saver:
            if not global_memory:
                return await invoke(checkpointer=saver)
            async with memory_store_context() as store:
                return await invoke(checkpointer=saver, memory_store=store)

    final_state = _run_async(execute())
    holdout_result: dict[str, Any] | None = None
    if holdout:
        if mock_bench:
            holdout_result = {
                "skipped": True,
                "reason": "synthetic search cannot produce a research holdout report",
            }
        else:
            holdout_result = _run_async(
                finalize_run(
                    run_dir=run_dir,
                    repo_root=REPO_ROOT,
                    holdout_tasks_dir=REPO_ROOT / "eval" / "holdout",
                    trials=trials,
                    workers=workers,
                )
            )
    typer.echo(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "iterations_completed": final_state["iteration"],
                "budget_remaining": final_state["budget_remaining"],
                "best_candidate": final_state.get("best_candidate"),
                "best_candidate_id": final_state.get("best_candidate_id"),
                "n_candidates": len(final_state.get("candidates") or []),
                "frontier_ids": final_state.get("frontier"),
                "persistent": persistent,
                "mode": resolved_mode.value,
                "proposer_backend": proposer,
                "proposer_model": resolved_proposer_model,
                "inner_model": resolved_inner_model,
                "random_seed": seed,
                "max_act_turns": max_act_turns,
                "max_verify_retries": max_verify_retries,
                "synthetic": mock_bench,
                "holdout": holdout_result,
            },
            indent=2,
        )
    )


@app.command()
def finalize(
    run_name: str = typer.Argument(...),
    candidate: list[str] | None = typer.Option(None, "--candidate"),
    trials: int | None = typer.Option(None, "--trials", min=1),
    workers: int | None = typer.Option(None, "--workers", min=1),
) -> None:
    from app.meta_harness.reports import finalize_run
    from app.meta_harness.runs import make_run_path

    run_dir = make_run_path(REPO_ROOT, run_name)
    if not run_dir.exists():
        typer.echo(f"run not found: {run_dir}", err=True)
        raise typer.Exit(1)
    try:
        result = _run_async(
            finalize_run(
                run_dir=run_dir,
                repo_root=REPO_ROOT,
                holdout_tasks_dir=REPO_ROOT / "eval" / "holdout",
                candidate_ids=candidate,
                trials=trials,
                workers=workers,
            )
        )
    except (ValueError, RuntimeError) as exc:
        typer.echo(f"finalization refused: {exc}", err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(result, indent=2))


@app.command()
def report(run_name: str = typer.Argument(...)) -> None:
    from app.meta_harness.reports import build_run_report
    from app.meta_harness.runs import make_run_path

    run_dir = make_run_path(REPO_ROOT, run_name)
    if not run_dir.exists():
        typer.echo(f"run not found: {run_dir}", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(build_run_report(run_dir), indent=2))


@app.command()
def bundle(
    run_name: str = typer.Argument(...),
    output: Path = typer.Option(..., "--output"),
    include_raw: bool = typer.Option(False, "--include-raw"),
    include_tasks: bool = typer.Option(True, "--tasks/--no-tasks"),
    include_holdout_tasks: bool = typer.Option(False, "--include-holdout-tasks"),
) -> None:
    from app.meta_harness.experiments import export_experiment_bundle
    from app.meta_harness.runs import make_run_path

    run_dir = make_run_path(REPO_ROOT, run_name)
    if not run_dir.exists():
        typer.echo(f"run not found: {run_dir}", err=True)
        raise typer.Exit(1)
    try:
        result = export_experiment_bundle(
            run_dir=run_dir,
            destination=output,
            include_raw=include_raw,
            repo_root=REPO_ROOT,
            include_tasks=include_tasks,
            include_holdout_tasks=include_holdout_tasks,
        )
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(f"bundle export refused: {exc}", err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(result, indent=2))


@app.command("verify-bundle")
def verify_bundle(path: Path = typer.Argument(...)) -> None:
    from app.meta_harness.experiments import verify_experiment_bundle

    typer.echo(json.dumps(verify_experiment_bundle(path), indent=2))


@app.command("compare-runs")
def compare_run_results(run_names: list[str] = typer.Argument(...)) -> None:
    from app.meta_harness.experiments import compare_runs
    from app.meta_harness.runs import make_run_path

    run_dirs = [make_run_path(REPO_ROOT, run_name) for run_name in run_names]
    missing = [str(path) for path in run_dirs if not path.exists()]
    if missing:
        typer.echo(f"runs not found: {missing}", err=True)
        raise typer.Exit(1)
    try:
        result = compare_runs(run_dirs)
    except ValueError as exc:
        typer.echo(f"comparison refused: {exc}", err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(result, indent=2))


@app.command()
def events(run_name: str = typer.Argument(...)) -> None:
    from app.meta_harness.ledger import read_events
    from app.meta_harness.runs import make_run_path

    run_dir = make_run_path(REPO_ROOT, run_name)
    if not run_dir.exists():
        typer.echo(f"run not found: {run_dir}", err=True)
        raise typer.Exit(1)
    typer.echo(
        json.dumps(
            [event.model_dump(mode="json") for event in read_events(run_dir)],
            indent=2,
        )
    )


@app.command()
def fork(
    run_name: str = typer.Argument(...),
    checkpoint: str = typer.Option(..., "--checkpoint"),
    mod: list[str] = typer.Option([], "--mod"),
    branch_name: str | None = typer.Option(None, "--name"),
    detach: bool = typer.Option(False, "--detach"),
) -> None:
    from app.meta_harness.branches import worktree_add
    from app.meta_harness.outer import OuterLoopRunner
    from app.meta_harness.persistence import persistence_layer
    from app.meta_harness.runs import make_run_path

    run_dir = make_run_path(REPO_ROOT, run_name)
    if not run_dir.exists():
        typer.echo(f"run not found: {run_dir}", err=True)
        raise typer.Exit(1)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        typer.echo(f"manifest.json missing in {run_dir}; cannot fork", err=True)
        raise typer.Exit(1)
    modifications: dict[str, Any] = {}
    for raw in mod:
        if "=" not in raw:
            raise typer.BadParameter(f"--mod must be KEY=VALUE; got {raw!r}")
        key, _, value = raw.partition("=")
        modifications[key.strip()] = value
    manifest = json.loads(manifest_path.read_text())
    policy = manifest.get("policy") or {}
    skill_path = Path(manifest["skill_path"]) if manifest.get("skill_path") else None

    async def execute() -> dict[str, Any]:
        async with persistence_layer() as saver:
            runner = OuterLoopRunner(
                run_dir=run_dir,
                repo_root=REPO_ROOT,
                eval_tasks_dir=REPO_ROOT / "eval" / "tasks",
                mock_proposer=bool(manifest.get("mock_proposer", False)),
                mock_bench=bool(manifest.get("mock_bench", False)),
                trials=int(manifest.get("trials", 5)),
                bench_workers=int(manifest.get("workers", 3)),
                skill_path=skill_path,
                checkpointer=saver,
                mode=manifest.get("mode", "research"),
                parent_policy=manifest.get("parent_policy", "best_accuracy"),
                inner_model=policy.get("inner_model"),
                proposer_model=manifest.get("proposer_model", "opus"),
                allow_global_memory=policy.get("allow_global_memory", False),
            )
            metadata, task = await worktree_add(
                runner.build(),
                run_id=run_name,
                parent_thread_id=run_name,
                parent_checkpoint_id=checkpoint,
                mods=modifications,
                name=branch_name,
                run_dir=run_dir,
            )
            if not detach:
                await task
            return metadata.to_dict()

    typer.echo(json.dumps(_run_async(execute()), indent=2, default=str))


@app.command()
def init(
    domain: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force"),
) -> None:
    target = REPO_ROOT / "skills" / f"meta-harness-{domain}"
    skill_file = target / "SKILL.md"
    if skill_file.exists() and not force:
        typer.echo(f"{skill_file} already exists. Pass --force to overwrite.", err=True)
        raise typer.Exit(1)
    target.mkdir(parents=True, exist_ok=True)
    template = REPO_ROOT / "skills" / "meta-harness-coding-agent" / "SKILL.md"
    if template.exists() and template != skill_file:
        content = template.read_text().replace(
            "meta-harness-coding-agent",
            f"meta-harness-{domain}",
            1,
        )
    else:
        content = f"""---
name: meta-harness-{domain}
description: Evolve the {domain} harness from immutable evidence.
---

# What gets evolved

A versioned harness bundle.

## Hard rules (Anti-Overfitting)

Do not inspect holdout tasks.

## Hard rules (Anti-Parameter-Tuning)

Change mechanisms, not constants.

## Workflow

Analyze, hypothesize, prototype, implement, and register one run-scoped proposal.

## Interface contract

Subclass CodingAgentHarness.

## pending_eval.json

Register source_path, class_name, parent, hypothesis, axis, and expected_score_delta.
"""
    skill_file.write_text(content)
    _validate_skill(skill_file)
    typer.echo(json.dumps({"domain": domain, "skill_path": str(skill_file)}, indent=2))


@app.command()
def resume(run_name: str = typer.Argument(...)) -> None:
    from app.meta_harness.memory import memory_store as memory_store_context
    from app.meta_harness.outer import resume_outer_loop
    from app.meta_harness.persistence import persistence_layer
    from app.meta_harness.runs import make_run_path

    run_dir = make_run_path(REPO_ROOT, run_name)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        typer.echo(f"manifest.json missing in {run_dir}; cannot resume", err=True)
        raise typer.Exit(1)
    manifest = json.loads(manifest_path.read_text())
    policy = manifest.get("policy") or {}
    skill_path = Path(manifest["skill_path"]) if manifest.get("skill_path") else None

    async def execute() -> Any:
        async with persistence_layer() as saver:
            if not policy.get("allow_global_memory"):
                return await resume_outer_loop(
                    run_dir=run_dir,
                    repo_root=REPO_ROOT,
                    eval_tasks_dir=REPO_ROOT / "eval" / "tasks",
                    checkpointer=saver,
                    skill_path=skill_path,
                )
            async with memory_store_context() as store:
                return await resume_outer_loop(
                    run_dir=run_dir,
                    repo_root=REPO_ROOT,
                    eval_tasks_dir=REPO_ROOT / "eval" / "tasks",
                    checkpointer=saver,
                    skill_path=skill_path,
                    memory_store=store,
                )

    final_state = _run_async(execute())
    typer.echo(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "resumed": True,
                "iterations_completed": final_state["iteration"],
                "budget_remaining": final_state["budget_remaining"],
                "best_candidate": final_state.get("best_candidate"),
                "best_candidate_id": final_state.get("best_candidate_id"),
            },
            indent=2,
        )
    )


memory_app = typer.Typer(name="memory", no_args_is_help=True)
app.add_typer(memory_app, name="memory")


@memory_app.command("list")
def memory_list(
    namespace: str = typer.Option("coding-agent", "--namespace"),
    limit: int = typer.Option(50, "--limit", min=1),
) -> None:
    from app.meta_harness.memory import list_namespace, memory_store

    async def execute() -> list:
        async with memory_store() as store:
            return await list_namespace(store, domain=namespace, limit=limit)

    typer.echo(json.dumps(_run_async(execute()), indent=2, default=str))


refinement_app = typer.Typer(name="refinement", no_args_is_help=True)
app.add_typer(refinement_app, name="refinement")


@refinement_app.command("apply")
def refinement_apply(
    run_name: str = typer.Argument(...),
    refinement_id: str = typer.Argument(...),
) -> None:
    from app.meta_harness.refinements import apply_refinement
    from app.meta_harness.runs import make_run_path

    run_dir = make_run_path(REPO_ROOT, run_name)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    record = apply_refinement(
        run_dir=run_dir,
        repo_root=REPO_ROOT,
        run_id=run_name,
        refinement_id=refinement_id,
        mode=manifest.get("mode", "research"),
    )
    typer.echo(json.dumps(record.model_dump(mode="json"), indent=2))


@refinement_app.command("rollback")
def refinement_rollback(
    run_name: str = typer.Argument(...),
    refinement_id: str = typer.Argument(...),
) -> None:
    from app.meta_harness.refinements import rollback_refinement
    from app.meta_harness.runs import make_run_path

    run_dir = make_run_path(REPO_ROOT, run_name)
    record = rollback_refinement(
        run_dir=run_dir,
        repo_root=REPO_ROOT,
        run_id=run_name,
        refinement_id=refinement_id,
    )
    typer.echo(json.dumps(record.model_dump(mode="json"), indent=2))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
