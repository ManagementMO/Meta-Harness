"""Single candidate evaluator for search, finalization, and mock fixtures."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.meta_harness.artifacts import (
    atomic_write_json,
    sha256_file,
    store_artifact,
    store_json_artifact,
)
from app.meta_harness.candidates import load_candidate_class
from app.meta_harness.contracts import (
    ArtifactRef,
    CandidateArtifact,
    CandidateEvaluation,
    EvaluationPolicy,
    FailureCategory,
    MeasurementStatus,
    MetricValue,
    RunMode,
    TaskAggregate,
    TaskResult,
    TaskSpec,
    UsageMetrics,
)
from app.meta_harness.execution import ChildBudget, get_execution_backend
from app.meta_harness.ledger import append_event
from app.meta_harness.sandbox import sandbox_for

EVALUATOR_VERSION = "candidate-evaluator-v1"


class EvaluationInfrastructureError(RuntimeError):
    pass


class EvaluationPolicyError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _metric_from_optional(
    value: int | float | None,
    *,
    unit: str,
    source: str,
) -> MetricValue:
    if value is None:
        return MetricValue.unknown(unit=unit, source=source)
    return MetricValue.measured(value, unit=unit, source=source)


def _aggregate_metric(
    values: list[MetricValue],
    *,
    unit: str,
    source: str,
) -> MetricValue:
    if not values:
        return MetricValue.measured(0, unit=unit, source=source)
    if any(value.status == MeasurementStatus.UNKNOWN for value in values):
        return MetricValue.unknown(unit=unit, source=source)
    measured = [
        value.value
        for value in values
        if value.status in {MeasurementStatus.MEASURED, MeasurementStatus.SYNTHETIC}
        and value.value is not None
    ]
    if len(measured) != len(values):
        return MetricValue.not_applicable(source=source)
    if all(value.status == MeasurementStatus.SYNTHETIC for value in values):
        return MetricValue.synthetic(sum(measured), unit=unit, source=source)
    return MetricValue.measured(sum(measured), unit=unit, source=source)


def _candidate_manifest_sha256(run_dir: Path, candidate_id: str) -> str:
    return sha256_file(run_dir / "candidates" / candidate_id / "candidate.json")


def _workspace_files(workspace: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace)
        if any(
            part in {"__pycache__", ".pytest_cache", ".git"}
            for part in relative.parts
        ):
            continue
        result[relative.as_posix()] = sha256_file(path)
    return result


def _scope_summary(
    before: dict[str, str],
    after: dict[str, str],
    expected: list[str],
) -> dict[str, Any]:
    changed = sorted(
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )
    expected_set = set(expected)
    out_of_plan = [path for path in changed if path not in expected_set]
    return {
        "status": "measured",
        "changed_files": changed,
        "expected_files_changed": sorted(expected_set),
        "out_of_plan_changes": out_of_plan,
        "passed": not out_of_plan,
    }


def _trace_artifacts(run_dir: Path, trace_dir: Path) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    if not trace_dir.exists():
        return refs
    media_types = {
        ".json": "application/json",
        ".jsonl": "application/x-ndjson",
        ".md": "text/markdown",
        ".txt": "text/plain",
    }
    for path in sorted(item for item in trace_dir.rglob("*") if item.is_file()):
        refs.append(
            store_artifact(
                run_dir,
                path.read_bytes(),
                media_type=media_types.get(path.suffix, "application/octet-stream"),
            )
        )
    return refs


def _usage_from_state(
    state: dict[str, Any],
    *,
    wall_seconds: float,
) -> UsageMetrics:
    telemetry = state.get("telemetry") or {}
    usage_available = bool(telemetry.get("usage_available", False))
    source = "inner-harness-v1"
    input_tokens = telemetry.get("input_tokens") if usage_available else None
    output_tokens = telemetry.get("output_tokens") if usage_available else None
    cached_tokens = telemetry.get("cached_tokens") if usage_available else None
    verify_attempts = int(state.get("verify_attempts", 0) or 0)
    return UsageMetrics(
        input_tokens=_metric_from_optional(
            input_tokens,
            unit="tokens",
            source=source,
        ),
        output_tokens=_metric_from_optional(
            output_tokens,
            unit="tokens",
            source=source,
        ),
        cached_tokens=_metric_from_optional(
            cached_tokens,
            unit="tokens",
            source=source,
        ),
        estimated_cost_usd=MetricValue.unknown(
            unit="usd",
            source="provider-pricing-unavailable",
        ),
        billed_cost_usd=MetricValue.unknown(
            unit="usd",
            source="provider-billing-unavailable",
        ),
        wall_seconds=MetricValue.measured(
            round(wall_seconds, 6),
            unit="seconds",
            source="monotonic-clock",
        ),
        model_calls=MetricValue.measured(
            int(telemetry.get("model_call_count", 0)),
            unit="calls",
            source=source,
        ),
        tool_calls=MetricValue.measured(
            len(state.get("tool_events") or []),
            unit="calls",
            source="inner-tool-events-v1",
        ),
        act_turns=MetricValue.measured(
            int(state.get("turn_count", 0) or 0),
            unit="turns",
            source="inner-state",
        ),
        verification_retries=MetricValue.measured(
            max(0, verify_attempts - 1),
            unit="retries",
            source="inner-state",
        ),
    )


def _failure_category(
    *,
    passed: bool,
    verify_result: dict[str, Any],
) -> FailureCategory | None:
    if passed:
        return None
    if verify_result.get("timed_out"):
        return FailureCategory.TIMEOUT
    return FailureCategory.VERIFICATION


class Evaluator:
    def __init__(
        self,
        *,
        run_dir: Path,
        repo_root: Path,
        policy: EvaluationPolicy,
        checkpointer: Any = None,
        phase: str = "search",
        run_id: str | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.repo_root = repo_root
        self.policy = policy
        self.checkpointer = checkpointer
        if phase not in {"search", "holdout", "validation"}:
            raise ValueError(f"unknown evaluation phase: {phase}")
        self.phase = phase
        self.run_id = run_id or run_dir.name
        self.backend = get_execution_backend(policy.execution_backend)

    async def evaluate_task(
        self,
        candidate: CandidateArtifact,
        candidate_class: type,
        task: TaskSpec,
        *,
        trial_index: int,
    ) -> TaskResult:
        if task.visibility != self.policy.task_visibility:
            raise ValueError(
                f"task visibility {task.visibility!r} does not match "
                f"policy {self.policy.task_visibility!r}"
            )
        attempt_id = f"attempt_{uuid.uuid4().hex}"
        started_at = _now()
        append_event(
            self.run_dir,
            event_type="TaskAttemptStarted",
            run_id=self.run_id,
            entity_type="attempt",
            entity_id=attempt_id,
            attempt_id=attempt_id,
            payload={
                "candidate_id": candidate.candidate_id,
                "task_id": task.id,
                "phase": self.phase,
                "policy_id": self.policy.policy_id,
            },
        )
        started_clock = time.monotonic()
        trace_root = "traces" if self.phase == "search" else f"{self.phase}-traces"
        trace_dir = (
            self.run_dir
            / "candidates"
            / candidate.candidate_id
            / trace_root
            / f"{task.id}-trial-{trial_index}"
        )
        trace_dir.mkdir(parents=True, exist_ok=True)
        state: dict[str, Any] = {}
        verify_result: dict[str, Any] = {}
        scope_summary: dict[str, Any] = {
            "status": "unknown",
            "changed_files": None,
            "expected_files_changed": task.expected_files_changed,
            "out_of_plan_changes": None,
            "passed": None,
        }
        passed = False
        score = 0.0
        failure_category: FailureCategory | None = FailureCategory.UNKNOWN
        error: dict[str, str] | None = None
        harness = None
        try:
            harness = candidate_class()
            harness.MODEL = self.policy.inner_model
            with sandbox_for(Path(task.source_path) / "workspace") as workspace:
                before = _workspace_files(workspace)
                state = await self.backend.execute(
                    harness,
                    task_dict=task.model_dump(mode="json"),
                    workspace=workspace,
                    trace_dir=trace_dir,
                    thread_id=(
                        f"{self.phase}-{candidate.candidate_id}-{task.id}-trial-{trial_index}"
                    ),
                    checkpointer=self.checkpointer,
                    child_budget=ChildBudget(),
                )
                observed_models = {
                    str(call["model"])
                    for call in (state.get("telemetry") or {}).get("model_calls", [])
                    if call.get("model")
                }
                if (
                    self.policy.mode == RunMode.RESEARCH
                    and observed_models
                    and observed_models != {self.policy.inner_model}
                ):
                    raise EvaluationPolicyError(
                        "provider-reported model does not match the fixed research model"
                    )
                after = _workspace_files(workspace)
                scope_summary = _scope_summary(
                    before,
                    after,
                    task.expected_files_changed,
                )
            verify_result = dict(state.get("verify_result") or {})
            score = float(state.get("score") or 0.0)
            passed = score >= 1.0
            failure_category = _failure_category(
                passed=passed,
                verify_result=verify_result,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            failure_category = FailureCategory.TIMEOUT
            error = {"type": type(exc).__name__, "message": str(exc)}
        except Exception as exc:
            message = str(exc)
            if exc.__class__.__module__.startswith("anthropic") or "ANTHROPIC_API_KEY" in message:
                failure_category = FailureCategory.MODEL
            elif exc.__class__.__module__.startswith("app.meta_harness"):
                failure_category = FailureCategory.EVALUATOR
            else:
                failure_category = FailureCategory.CANDIDATE
            error = {"type": type(exc).__name__, "message": message}
        wall_seconds = time.monotonic() - started_clock
        if harness is not None and "telemetry" not in state:
            state["telemetry"] = harness._telemetry().snapshot()
        usage = _usage_from_state(state, wall_seconds=wall_seconds)
        refs = _trace_artifacts(self.run_dir, trace_dir)
        test_summary = {
            "status": "measured" if error is None else "unknown",
            "tests_pass": passed,
            "test_command": verify_result.get("test_command", task.test_command),
            "exit_code": verify_result.get("exit_code"),
            "timed_out": bool(verify_result.get("timed_out", False)),
            "output": verify_result.get("test_output", ""),
            "error": error,
        }
        result = TaskResult(
            candidate_id=candidate.candidate_id,
            candidate_manifest_sha256=_candidate_manifest_sha256(
                self.run_dir,
                candidate.candidate_id,
            ),
            task_id=task.id,
            task_sha256=task.sha256,
            attempt_id=attempt_id,
            passed=passed,
            score=score,
            failure_category=failure_category,
            test_summary=test_summary,
            lint_summary={
                "status": "unknown",
                "passed": None,
                "errors": None,
            },
            scope_summary=scope_summary,
            usage=usage,
            retry_count=max(0, int(state.get("verify_attempts", 0) or 0) - 1),
            artifact_refs=refs,
            evaluator_version=EVALUATOR_VERSION,
            sandbox_profile=self.policy.sandbox_profile,
            runtime_adapter=task.runtime_adapter,
            execution_backend=self.policy.execution_backend,
            synthetic=False,
            started_at=started_at,
            finished_at=_now(),
        )
        atomic_write_json(trace_dir / "task-result.json", result)
        result_ref = store_json_artifact(self.run_dir, result)
        result.artifact_refs.append(result_ref)
        atomic_write_json(trace_dir / "task-result.json", result)
        evidence_refs = [*refs, result_ref]
        telemetry = state.get("telemetry") or {}
        for index, model_call in enumerate(telemetry.get("model_calls", []), 1):
            append_event(
                self.run_dir,
                event_type="ModelCallCompleted",
                run_id=self.run_id,
                entity_type="model_call",
                entity_id=f"{attempt_id}:model:{index}",
                attempt_id=attempt_id,
                payload={
                    "candidate_id": candidate.candidate_id,
                    "task_id": task.id,
                    **model_call,
                },
            )
        for tool_event in state.get("tool_events") or []:
            append_event(
                self.run_dir,
                event_type="ToolCallCompleted",
                run_id=self.run_id,
                entity_type="tool_call",
                entity_id=str(tool_event.get("call_id") or uuid.uuid4().hex),
                attempt_id=attempt_id,
                payload={
                    "candidate_id": candidate.candidate_id,
                    "task_id": task.id,
                    "tool": tool_event.get("tool"),
                    "turn": tool_event.get("turn"),
                    "duration_ms": tool_event.get("duration_ms"),
                    "is_error": tool_event.get("is_error"),
                },
            )
        append_event(
            self.run_dir,
            event_type="VerificationCompleted",
            run_id=self.run_id,
            entity_type="attempt",
            entity_id=attempt_id,
            attempt_id=attempt_id,
            payload={
                "candidate_id": candidate.candidate_id,
                "task_id": task.id,
                "passed": passed,
                "score": score,
                "failure_category": (
                    failure_category.value if failure_category is not None else None
                ),
            },
            artifact_refs=evidence_refs,
        )
        append_event(
            self.run_dir,
            event_type="TaskAttemptFinished",
            run_id=self.run_id,
            entity_type="attempt",
            entity_id=attempt_id,
            attempt_id=attempt_id,
            payload={
                "candidate_id": candidate.candidate_id,
                "task_id": task.id,
                "passed": passed,
                "score": score,
            },
            artifact_refs=evidence_refs,
        )
        return result

    async def evaluate_candidate(
        self,
        candidate: CandidateArtifact,
        tasks: list[TaskSpec],
    ) -> CandidateEvaluation:
        if self.policy.synthetic:
            raise ValueError("use evaluate_synthetic_candidate for synthetic policies")
        started_at = _now()
        started_clock = time.monotonic()
        candidate_class = load_candidate_class(
            self.run_dir,
            candidate,
            repo_root=self.repo_root,
            research_mode=self.policy.mode == RunMode.RESEARCH,
        )
        semaphore = asyncio.Semaphore(self.policy.workers)

        async def run_one(task: TaskSpec, trial_index: int) -> TaskResult:
            async with semaphore:
                return await self.evaluate_task(
                    candidate,
                    candidate_class,
                    task,
                    trial_index=trial_index,
                )

        task_results = await asyncio.gather(
            *[
                run_one(task, trial_index)
                for task in tasks
                for trial_index in range(1, self.policy.trials + 1)
            ]
        )
        infrastructure_failures = [
            result
            for result in task_results
            if result.failure_category
            in {
                FailureCategory.CANDIDATE,
                FailureCategory.EVALUATOR,
                FailureCategory.MODEL,
                FailureCategory.POLICY,
                FailureCategory.SANDBOX,
            }
        ]
        if infrastructure_failures:
            append_event(
                self.run_dir,
                event_type="CandidateEvaluationAborted",
                run_id=self.run_id,
                entity_type="candidate",
                entity_id=candidate.candidate_id,
                payload={
                    "policy_id": self.policy.policy_id,
                    "phase": self.phase,
                    "attempt_ids": [
                        result.attempt_id for result in infrastructure_failures
                    ],
                    "failure_categories": sorted(
                        {
                            result.failure_category.value
                            for result in infrastructure_failures
                            if result.failure_category is not None
                        }
                    ),
                },
            )
            raise EvaluationInfrastructureError(
                "candidate evaluation aborted because candidate loading, model, "
                "evaluator, policy, or sandbox execution failed"
            )
        per_task: dict[str, TaskAggregate] = {}
        for task in tasks:
            matches = [result for result in task_results if result.task_id == task.id]
            per_task[task.id] = TaskAggregate(
                pass_rate=(
                    sum(result.passed for result in matches) / len(matches)
                    if matches
                    else 0.0
                ),
                trials=[result.passed for result in matches],
                scores=[result.score for result in matches],
                attempt_ids=[result.attempt_id for result in matches],
            )
        accuracy_value = (
            sum(result.passed for result in task_results) / len(task_results)
            if task_results
            else 0.0
        )
        usage = UsageMetrics(
            input_tokens=_aggregate_metric(
                [result.usage.input_tokens for result in task_results],
                unit="tokens",
                source="task-result-sum",
            ),
            output_tokens=_aggregate_metric(
                [result.usage.output_tokens for result in task_results],
                unit="tokens",
                source="task-result-sum",
            ),
            cached_tokens=_aggregate_metric(
                [result.usage.cached_tokens for result in task_results],
                unit="tokens",
                source="task-result-sum",
            ),
            estimated_cost_usd=MetricValue.unknown(
                unit="usd",
                source="provider-pricing-unavailable",
            ),
            billed_cost_usd=MetricValue.unknown(
                unit="usd",
                source="provider-billing-unavailable",
            ),
            wall_seconds=MetricValue.measured(
                round(time.monotonic() - started_clock, 6),
                unit="seconds",
                source="candidate-wall-clock",
            ),
            model_calls=_aggregate_metric(
                [result.usage.model_calls for result in task_results],
                unit="calls",
                source="task-result-sum",
            ),
            tool_calls=_aggregate_metric(
                [result.usage.tool_calls for result in task_results],
                unit="calls",
                source="task-result-sum",
            ),
            act_turns=_aggregate_metric(
                [result.usage.act_turns for result in task_results],
                unit="turns",
                source="task-result-sum",
            ),
            verification_retries=_aggregate_metric(
                [result.usage.verification_retries for result in task_results],
                unit="retries",
                source="task-result-sum",
            ),
        )
        evaluation = CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            candidate_name=candidate.name,
            candidate_manifest_sha256=_candidate_manifest_sha256(
                self.run_dir,
                candidate.candidate_id,
            ),
            policy_id=self.policy.policy_id,
            task_hashes={task.id: task.sha256 for task in tasks},
            n_tasks=len(tasks),
            n_trials_per_task=self.policy.trials,
            accuracy=MetricValue.measured(
                round(accuracy_value, 6),
                unit="ratio",
                source="task-pass-rate",
            ),
            per_task=per_task,
            usage=usage,
            task_results=task_results,
            synthetic=False,
            started_at=started_at,
            finished_at=_now(),
        )
        self._write_evaluation(candidate, evaluation)
        return evaluation

    def evaluate_synthetic_candidate(
        self,
        candidate: CandidateArtifact,
        tasks: list[TaskSpec],
        *,
        target_accuracy: float,
    ) -> CandidateEvaluation:
        if not self.policy.synthetic:
            raise ValueError("synthetic evaluation requires a synthetic policy")
        started_at = _now()
        task_results: list[TaskResult] = []
        per_task: dict[str, TaskAggregate] = {}
        passes_per_task = int(round(self.policy.trials * target_accuracy))
        for task in tasks:
            trials = [index < passes_per_task for index in range(self.policy.trials)]
            attempts: list[str] = []
            for index, passed in enumerate(trials, 1):
                attempt_id = f"synthetic_{candidate.candidate_id}_{task.id}_{index}"
                attempts.append(attempt_id)
                task_results.append(
                    TaskResult(
                        candidate_id=candidate.candidate_id,
                        candidate_manifest_sha256=_candidate_manifest_sha256(
                            self.run_dir,
                            candidate.candidate_id,
                        ),
                        task_id=task.id,
                        task_sha256=task.sha256,
                        attempt_id=attempt_id,
                        passed=passed,
                        score=1.0 if passed else 0.0,
                        failure_category=None if passed else FailureCategory.VERIFICATION,
                        test_summary={
                            "status": "synthetic",
                            "tests_pass": passed,
                            "test_command": task.test_command,
                            "exit_code": 0 if passed else 1,
                            "timed_out": False,
                            "output": "synthetic mock fixture",
                            "error": None,
                        },
                        lint_summary={
                            "status": "unknown",
                            "passed": None,
                            "errors": None,
                        },
                        scope_summary={
                            "status": "unknown",
                            "changed_files": None,
                            "expected_files_changed": task.expected_files_changed,
                            "out_of_plan_changes": None,
                            "passed": None,
                        },
                        usage=UsageMetrics(
                            input_tokens=MetricValue.synthetic(
                                24000,
                                unit="tokens",
                                source="mock-bench-v1",
                            ),
                            output_tokens=MetricValue.synthetic(
                                800,
                                unit="tokens",
                                source="mock-bench-v1",
                            ),
                            cached_tokens=MetricValue.synthetic(
                                0,
                                unit="tokens",
                                source="mock-bench-v1",
                            ),
                            estimated_cost_usd=MetricValue.unknown(
                                unit="usd",
                                source="mock-bench-v1",
                            ),
                            billed_cost_usd=MetricValue.not_applicable(
                                source="mock-bench-v1"
                            ),
                            wall_seconds=MetricValue.synthetic(
                                0.05,
                                unit="seconds",
                                source="mock-bench-v1",
                            ),
                            model_calls=MetricValue.synthetic(
                                1,
                                unit="calls",
                                source="mock-bench-v1",
                            ),
                            tool_calls=MetricValue.synthetic(
                                1,
                                unit="calls",
                                source="mock-bench-v1",
                            ),
                            act_turns=MetricValue.synthetic(
                                1,
                                unit="turns",
                                source="mock-bench-v1",
                            ),
                            verification_retries=MetricValue.synthetic(
                                0,
                                unit="retries",
                                source="mock-bench-v1",
                            ),
                        ),
                        retry_count=0,
                        evaluator_version=EVALUATOR_VERSION,
                        sandbox_profile=self.policy.sandbox_profile,
                        runtime_adapter=task.runtime_adapter,
                        execution_backend=self.policy.execution_backend,
                        synthetic=True,
                        started_at=started_at,
                        finished_at=started_at,
                    )
                )
            per_task[task.id] = TaskAggregate(
                pass_rate=sum(trials) / len(trials) if trials else 0.0,
                trials=trials,
                scores=[1.0 if passed else 0.0 for passed in trials],
                attempt_ids=attempts,
            )
        usage = UsageMetrics(
            input_tokens=_aggregate_metric(
                [result.usage.input_tokens for result in task_results],
                unit="tokens",
                source="mock-bench-v1",
            ),
            output_tokens=_aggregate_metric(
                [result.usage.output_tokens for result in task_results],
                unit="tokens",
                source="mock-bench-v1",
            ),
            cached_tokens=_aggregate_metric(
                [result.usage.cached_tokens for result in task_results],
                unit="tokens",
                source="mock-bench-v1",
            ),
            estimated_cost_usd=MetricValue.unknown(
                unit="usd",
                source="mock-bench-v1",
            ),
            billed_cost_usd=MetricValue.not_applicable(source="mock-bench-v1"),
            wall_seconds=MetricValue.synthetic(
                round(0.05 * len(task_results), 6),
                unit="seconds",
                source="mock-bench-v1",
            ),
            model_calls=_aggregate_metric(
                [result.usage.model_calls for result in task_results],
                unit="calls",
                source="mock-bench-v1",
            ),
            tool_calls=_aggregate_metric(
                [result.usage.tool_calls for result in task_results],
                unit="calls",
                source="mock-bench-v1",
            ),
            act_turns=_aggregate_metric(
                [result.usage.act_turns for result in task_results],
                unit="turns",
                source="mock-bench-v1",
            ),
            verification_retries=_aggregate_metric(
                [result.usage.verification_retries for result in task_results],
                unit="retries",
                source="mock-bench-v1",
            ),
        )
        actual_accuracy = (
            sum(result.passed for result in task_results) / len(task_results)
            if task_results
            else 0.0
        )
        evaluation = CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            candidate_name=candidate.name,
            candidate_manifest_sha256=_candidate_manifest_sha256(
                self.run_dir,
                candidate.candidate_id,
            ),
            policy_id=self.policy.policy_id,
            task_hashes={task.id: task.sha256 for task in tasks},
            n_tasks=len(tasks),
            n_trials_per_task=self.policy.trials,
            accuracy=MetricValue.synthetic(
                round(actual_accuracy, 6),
                unit="ratio",
                source="mock-bench-v1",
            ),
            per_task=per_task,
            usage=usage,
            task_results=task_results,
            synthetic=True,
            started_at=started_at,
            finished_at=_now(),
        )
        self._write_evaluation(candidate, evaluation)
        return evaluation

    def _write_evaluation(
        self,
        candidate: CandidateArtifact,
        evaluation: CandidateEvaluation,
    ) -> None:
        document = evaluation.model_dump(mode="json")
        accuracy = evaluation.accuracy.value
        input_tokens = evaluation.usage.input_tokens.value
        output_tokens = evaluation.usage.output_tokens.value
        total_tokens = (
            int(input_tokens) + int(output_tokens)
            if input_tokens is not None and output_tokens is not None
            else None
        )
        attempts = max(1, len(evaluation.task_results))
        document.update(
            {
                "candidate": candidate.name,
                "accuracy_value": accuracy,
                "tokens": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "measurement_status": evaluation.usage.input_tokens.status.value,
                },
                "avg_tokens": total_tokens / attempts if total_tokens is not None else None,
                "cost_usd": evaluation.usage.estimated_cost_usd.value,
                "wall_time_s": evaluation.usage.wall_seconds.value,
                "_mock_bench": evaluation.synthetic,
                "synthetic": evaluation.synthetic,
            }
        )
        candidate_root = self.run_dir / "candidates" / candidate.candidate_id
        path = (
            candidate_root / "eval-result.json"
            if self.phase == "search"
            else candidate_root / self.phase / "eval-result.json"
        )
        atomic_write_json(path, document)
        result_ref = store_json_artifact(self.run_dir, document)
        evaluation.artifact_refs.append(result_ref)
        document["artifact_refs"] = [
            ref.model_dump(mode="json") for ref in evaluation.artifact_refs
        ]
        atomic_write_json(path, document)
        append_event(
            self.run_dir,
            event_type="CandidateBenchmarked",
            run_id=self.run_id,
            entity_type="candidate",
            entity_id=candidate.candidate_id,
            payload={
                "candidate_name": candidate.name,
                "policy_id": evaluation.policy_id,
                "phase": self.phase,
                "accuracy": evaluation.accuracy.model_dump(mode="json"),
                "synthetic": evaluation.synthetic,
                "result_path": str(path.relative_to(self.run_dir)),
            },
            artifact_refs=[result_ref],
        )


def load_evaluation(path: Path) -> CandidateEvaluation:
    value = json.loads(path.read_text())
    allowed = set(CandidateEvaluation.model_fields)
    return CandidateEvaluation.model_validate(
        {key: item for key, item in value.items() if key in allowed}
    )
