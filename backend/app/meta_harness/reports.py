"""Reproducible run reports and isolated holdout finalization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.meta_harness.artifacts import atomic_write_json, sha256_file
from app.meta_harness.candidates import (
    candidate_search_roots,
    locate_candidate,
    mirror_candidate_artifact,
    resolve_candidate_id,
)
from app.meta_harness.contracts import EvaluationPolicy, RunMode, utc_now
from app.meta_harness.evaluator import Evaluator
from app.meta_harness.ledger import read_events
from app.meta_harness.runtime import discover_tasks


def _candidate_ids_for_finalization(
    run_dir: Path,
    requested: list[str] | None,
) -> list[str]:
    if requested:
        return list(dict.fromkeys(resolve_candidate_id(run_dir, value) for value in requested))
    manifest = json.loads((run_dir / "manifest.json").read_text())
    frontier_path = run_dir / "frontier_val.json"
    frontier = json.loads(frontier_path.read_text()) if frontier_path.exists() else {}
    values: list[str] = []
    baseline_id = resolve_candidate_id(run_dir, "baseline")
    values.append(baseline_id)
    values.extend(str(value) for value in frontier.get("_pareto_ids", []))
    branches_root = run_dir / "branches"
    if branches_root.exists():
        for branch_frontier_path in sorted(branches_root.glob("*/frontier_val.json")):
            branch_frontier = json.loads(branch_frontier_path.read_text())
            values.extend(
                str(value) for value in branch_frontier.get("_pareto_ids", [])
            )
            branch_best = (branch_frontier.get("_best") or {}).get("candidate_id")
            if branch_best:
                values.append(str(branch_best))
    best_id = manifest.get("best_candidate_id")
    if best_id:
        values.append(str(best_id))
    elif (frontier.get("_best") or {}).get("candidate_id"):
        values.append(str(frontier["_best"]["candidate_id"]))
    return list(dict.fromkeys(values))


def _paired_comparison(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    baseline_tasks = baseline.get("per_task", {})
    candidate_tasks = candidate.get("per_task", {})
    task_ids = sorted(set(baseline_tasks) | set(candidate_tasks))
    improved: list[str] = []
    regressed: list[str] = []
    unchanged: list[str] = []
    deltas: dict[str, float] = {}
    for task_id in task_ids:
        baseline_rate = float((baseline_tasks.get(task_id) or {}).get("pass_rate", 0.0))
        candidate_rate = float((candidate_tasks.get(task_id) or {}).get("pass_rate", 0.0))
        delta = round(candidate_rate - baseline_rate, 6)
        deltas[task_id] = delta
        if delta > 0:
            improved.append(task_id)
        elif delta < 0:
            regressed.append(task_id)
        else:
            unchanged.append(task_id)
    return {
        "paired_task_deltas": deltas,
        "improved_task_ids": improved,
        "regressed_task_ids": regressed,
        "unchanged_task_ids": unchanged,
        "regression_count": len(regressed),
    }


async def finalize_run(
    *,
    run_dir: Path,
    repo_root: Path,
    holdout_tasks_dir: Path,
    candidate_ids: list[str] | None = None,
    trials: int | None = None,
    workers: int | None = None,
    checkpointer: Any = None,
    allow_synthetic_search: bool = False,
) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("synthetic") and not allow_synthetic_search:
        raise ValueError("synthetic search runs cannot produce research finalization reports")
    search_policy = EvaluationPolicy.model_validate(manifest["policy"])
    holdout_tasks = discover_tasks(holdout_tasks_dir, visibility="holdout")
    if not holdout_tasks:
        raise ValueError(f"no holdout tasks found in {holdout_tasks_dir}")
    holdout_policy = EvaluationPolicy(
        policy_id=f"holdout_{search_policy.policy_id}",
        mode=RunMode.RESEARCH,
        task_visibility="holdout",
        sandbox_profile=search_policy.sandbox_profile,
        runtime_adapter="task-declared",
        execution_backend=search_policy.execution_backend,
        inner_model=search_policy.inner_model,
        model_provider=search_policy.model_provider,
        trials=trials or search_policy.trials,
        workers=workers or search_policy.workers,
        max_act_turns=search_policy.max_act_turns,
        max_verify_retries=search_policy.max_verify_retries,
        allow_global_memory=False,
        allow_recursive_children=False,
        random_seed=search_policy.random_seed,
        synthetic=False,
    )
    evaluator = Evaluator(
        run_dir=run_dir,
        repo_root=repo_root,
        policy=holdout_policy,
        checkpointer=checkpointer,
        phase="holdout",
        run_id=str(manifest.get("run_id", run_dir.name)),
    )
    selected_ids = _candidate_ids_for_finalization(run_dir, candidate_ids)
    evaluations: dict[str, dict[str, Any]] = {}
    for candidate_id in selected_ids:
        artifact_root, _resolved_id = locate_candidate(run_dir, candidate_id)
        artifact = mirror_candidate_artifact(
            artifact_root,
            run_dir,
            candidate_id,
        )
        evaluation = await evaluator.evaluate_candidate(artifact, holdout_tasks)
        evaluations[candidate_id] = evaluation.model_dump(mode="json")
    baseline_id = resolve_candidate_id(run_dir, "baseline")
    baseline = evaluations.get(baseline_id)
    if baseline is None:
        raise ValueError("baseline must be included in finalization")
    comparisons = {
        candidate_id: _paired_comparison(baseline, evaluation)
        for candidate_id, evaluation in evaluations.items()
        if candidate_id != baseline_id
    }
    report = {
        "schema_version": 1,
        "run_id": manifest.get("run_id", run_dir.name),
        "phase": "holdout_finalization",
        "feedback_to_search": False,
        "search_manifest": {
            "path": "manifest.json",
            "sha256": sha256_file(manifest_path),
        },
        "search_policy_id": search_policy.policy_id,
        "holdout_policy": holdout_policy.model_dump(mode="json"),
        "holdout_tasks": [
            {"task_id": task.id, "sha256": task.sha256}
            for task in holdout_tasks
        ],
        "candidate_ids": selected_ids,
        "baseline_candidate_id": baseline_id,
        "evaluations": evaluations,
        "comparisons": comparisons,
        "synthetic": False,
        "human_intervention": False,
        "finalized_at": utc_now(),
    }
    atomic_write_json(run_dir / "finalization.json", report)
    atomic_write_json(
        run_dir / "holdout-result.json",
        {
            "candidate": manifest.get("best_candidate"),
            "candidate_id": manifest.get("best_candidate_id"),
            "baseline_candidate_id": baseline_id,
            "evaluations": evaluations,
            "comparisons": comparisons,
            "synthetic": False,
            "feedback_to_search": False,
        },
    )
    return report


def _compact_result(value: dict[str, Any]) -> dict[str, Any]:
    task_results = value.get("task_results", [])
    failures = [result for result in task_results if not result.get("passed", False)]
    excluded = {"task_results", "artifact_refs"}
    return {
        **{key: item for key, item in value.items() if key not in excluded},
        "failure_count": len(failures),
        "failure_categories": sorted(
            {
                str(result.get("failure_category"))
                for result in failures
                if result.get("failure_category")
            }
        ),
        "attempt_ids": [result.get("attempt_id") for result in task_results],
    }


def build_run_report(run_dir: Path) -> dict[str, Any]:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    frontier = json.loads((run_dir / "frontier_val.json").read_text())
    summary_paths = [run_dir / "evolution_summary.jsonl"]
    branches_root = run_dir / "branches"
    if branches_root.exists():
        summary_paths.extend(sorted(branches_root.glob("*/evolution_summary.jsonl")))
    rows = [
        json.loads(line)
        for summary_path in summary_paths
        if summary_path.exists()
        for line in summary_path.read_text().splitlines()
        if line.strip()
    ]
    frontier_ids = list(frontier.get("_pareto_ids", []))
    if branches_root.exists():
        for branch_frontier_path in sorted(branches_root.glob("*/frontier_val.json")):
            branch_frontier = json.loads(branch_frontier_path.read_text())
            frontier_ids.extend(branch_frontier.get("_pareto_ids", []))
    frontier_ids = list(dict.fromkeys(frontier_ids))
    candidate_ids = list(
        dict.fromkeys(row.get("candidate_id") for row in rows if row.get("candidate_id"))
    )
    evaluation_ids = list(dict.fromkeys([*candidate_ids, *frontier_ids]))
    candidate_results: dict[str, dict[str, Any]] = {}
    candidate_locations: dict[str, str] = {}
    for candidate_id in evaluation_ids:
        artifact_root, _resolved_id = locate_candidate(run_dir, candidate_id)
        result_path = artifact_root / "candidates" / candidate_id / "eval-result.json"
        candidate_locations[candidate_id] = str(
            artifact_root.relative_to(run_dir) or Path(".")
        )
        if result_path.exists():
            candidate_results[candidate_id] = _compact_result(
                json.loads(result_path.read_text())
            )
    tool_call_counts: dict[str, dict[str, int]] = {}
    for evidence_root in candidate_search_roots(run_dir):
        for event in read_events(evidence_root):
            if event.event_type != "ToolCallCompleted":
                continue
            candidate_id = str(event.payload.get("candidate_id") or "")
            tool_name = str(event.payload.get("tool_name") or "unknown")
            if not candidate_id:
                continue
            per_candidate = tool_call_counts.setdefault(candidate_id, {})
            per_candidate[tool_name] = per_candidate.get(tool_name, 0) + 1
    global_best_candidate_id = max(
        candidate_results,
        key=lambda candidate_id: float(
            candidate_results[candidate_id].get("accuracy_value", 0.0) or 0.0
        ),
        default=manifest.get("best_candidate_id"),
    )

    def usage_value(result: dict[str, Any], metric: str) -> float | None:
        value = ((result.get("usage") or {}).get(metric) or {}).get("value")
        return float(value) if isinstance(value, int | float) else None

    proposer_sessions = []
    for session_path in sorted(run_dir.glob("proposer-sessions/iter-*/session.json")):
        proposer_sessions.append(json.loads(session_path.read_text()))
    if branches_root.exists():
        for session_path in sorted(
            branches_root.glob("*/proposer-sessions/iter-*/session.json")
        ):
            proposer_sessions.append(json.loads(session_path.read_text()))
    candidate_generation_seconds = sum(
        float(session.get("duration_seconds") or 0.0)
        for session in proposer_sessions
    )
    proposer_input_tokens = sum(
        int((session.get("token_usage") or {}).get("input_tokens") or 0)
        for session in proposer_sessions
    )
    proposer_output_tokens = sum(
        int((session.get("token_usage") or {}).get("output_tokens") or 0)
        for session in proposer_sessions
    )
    proposer_estimated_cost = sum(
        float(session.get("estimated_cost_usd") or 0.0)
        for session in proposer_sessions
    )
    total_tokens_values = [
        (usage_value(result, "input_tokens"), usage_value(result, "output_tokens"))
        for result in candidate_results.values()
    ]
    total_tokens = (
        sum(
            (input_tokens or 0.0) + (output_tokens or 0.0)
            for input_tokens, output_tokens in total_tokens_values
        )
        if total_tokens_values
        and all(
            input_tokens is not None and output_tokens is not None
            for input_tokens, output_tokens in total_tokens_values
        )
        else None
    )
    if total_tokens is not None:
        total_tokens += proposer_input_tokens + proposer_output_tokens
    estimated_cost_values = [
        usage_value(result, "estimated_cost_usd")
        for result in candidate_results.values()
    ]
    total_estimated_cost = (
        proposer_estimated_cost
        + sum(value for value in estimated_cost_values if value is not None)
        if estimated_cost_values
        and all(value is not None for value in estimated_cost_values)
        else None
    )
    billed_cost_values = [
        usage_value(result, "billed_cost_usd")
        for result in candidate_results.values()
    ]
    total_billed_cost = (
        sum(value for value in billed_cost_values if value is not None)
        if billed_cost_values and all(value is not None for value in billed_cost_values)
        else None
    )
    evaluation_wall_values = [
        usage_value(result, "wall_seconds") for result in candidate_results.values()
    ]
    total_wall_seconds = (
        candidate_generation_seconds
        + sum(value for value in evaluation_wall_values if value is not None)
        if evaluation_wall_values
        and all(value is not None for value in evaluation_wall_values)
        else None
    )
    try:
        baseline_id = resolve_candidate_id(run_dir, "baseline")
    except (KeyError, ValueError):
        baseline_id = None
    baseline_accuracy = (
        candidate_results.get(baseline_id, {}).get("accuracy_value")
        if baseline_id
        else None
    )
    best_accuracy = candidate_results.get(global_best_candidate_id, {}).get(
        "accuracy_value"
    )
    improvement = (
        float(best_accuracy) - float(baseline_accuracy)
        if best_accuracy is not None and baseline_accuracy is not None
        else None
    )
    candidate_denominator = max(1, len(candidate_ids) - (1 if baseline_id else 0))
    effective_cost = (
        total_billed_cost if total_billed_cost is not None else total_estimated_cost
    )
    search_efficiency = {
        "measurement_status": (
            "synthetic"
            if manifest.get("synthetic", False)
            else ("measured" if improvement is not None else "unknown")
        ),
        "token_measurement_status": (
            "synthetic"
            if manifest.get("synthetic", False) and total_tokens is not None
            else ("measured" if total_tokens is not None else "unknown")
        ),
        "cost_measurement_status": (
            "billed"
            if total_billed_cost is not None
            else ("estimated" if total_estimated_cost is not None else "unknown")
        ),
        "wall_measurement_status": (
            "synthetic"
            if manifest.get("synthetic", False) and total_wall_seconds is not None
            else ("measured" if total_wall_seconds is not None else "unknown")
        ),
        "accuracy_improvement": improvement,
        "improvement_per_candidate": (
            improvement / candidate_denominator if improvement is not None else None
        ),
        "improvement_per_1k_tokens": (
            improvement / (total_tokens / 1000.0)
            if improvement is not None and total_tokens
            else None
        ),
        "improvement_per_dollar": (
            improvement / effective_cost
            if improvement is not None and effective_cost
            else None
        ),
        "improvement_per_wall_hour": (
            improvement / (total_wall_seconds / 3600.0)
            if improvement is not None and total_wall_seconds
            else None
        ),
        "candidate_generation_seconds": candidate_generation_seconds,
        "proposer_input_tokens": proposer_input_tokens,
        "proposer_output_tokens": proposer_output_tokens,
        "total_tokens": total_tokens,
        "total_estimated_cost_usd": total_estimated_cost,
        "total_billed_cost_usd": total_billed_cost,
        "total_wall_seconds": total_wall_seconds,
    }
    return {
        "schema_version": 1,
        "run_id": manifest.get("run_id", run_dir.name),
        "git_commit": manifest.get("git_commit"),
        "git_dirty": manifest.get("git_dirty"),
        "runtime_sha256": manifest.get("runtime_sha256"),
        "dependency_lock_sha256": manifest.get("dependency_lock_sha256"),
        "mode": manifest.get("mode"),
        "policy": manifest.get("policy"),
        "parent_policy": manifest.get("parent_policy"),
        "random_seed": manifest.get("random_seed"),
        "artifact_retention": manifest.get("artifact_retention"),
        "search_budget": manifest.get("budget"),
        "synthetic": manifest.get("synthetic", False),
        "candidate_ids": candidate_ids,
        "archive_size": len(candidate_ids),
        "frontier_ids": frontier_ids,
        "frontier_size": len(frontier_ids),
        "best_candidate_id": manifest.get("best_candidate_id"),
        "global_best_candidate_id": global_best_candidate_id,
        "candidate_locations": candidate_locations,
        "results": candidate_results,
        "tool_call_counts": tool_call_counts,
        "search_efficiency": search_efficiency,
        "proposer_evidence_access": manifest.get("proposer_evidence_access", []),
        "recursive_children_enabled": bool(
            (manifest.get("policy") or {}).get("allow_recursive_children", False)
        ),
        "human_intervention": manifest.get("human_intervention", False),
        "generated_at": utc_now(),
    }
