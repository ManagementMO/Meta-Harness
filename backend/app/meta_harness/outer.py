"""Artifact-backed outer search graph for candidate populations."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.meta_harness import frontier as fr
from app.meta_harness import memory as mem
from app.meta_harness import proposer as prp
from app.meta_harness import runs as runs_mod
from app.meta_harness.artifacts import (
    atomic_write_json,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from app.meta_harness.candidates import (
    candidate_manifest_path,
    load_candidate_artifact,
    load_candidate_class,
    materialize_candidate,
)
from app.meta_harness.contracts import (
    CandidateRecord,
    CandidateStatus,
    EvaluationPolicy,
    PendingEvaluation,
    RunManifest,
    RunMode,
    utc_now,
)
from app.meta_harness.evaluator import Evaluator
from app.meta_harness.harness import CodingAgentHarness
from app.meta_harness.ledger import append_event, lifecycle_state, transition_lifecycle
from app.meta_harness.provenance import (
    capture_git_state,
    capture_provenance,
    capture_runtime_sha256,
)
from app.meta_harness.runtime import TaskSpec, discover_tasks
from app.meta_harness.state import MetaHarnessState
from app.streaming import emit_run_event


def _thread_id(state: MetaHarnessState, config: RunnableConfig | None) -> str:
    configurable = (config or {}).get("configurable", {})
    return str(configurable.get("thread_id") or state["run_id"])


def _summary(state: MetaHarnessState, *, iteration: int | None = None) -> dict[str, Any]:
    return {
        "candidates_count": len(state.get("candidates") or []),
        "budget_remaining": state.get("budget_remaining"),
        "best_candidate": state.get("best_candidate"),
        "best_candidate_id": state.get("best_candidate_id"),
        "iteration": iteration if iteration is not None else state.get("iteration"),
    }


def _emit(
    state: MetaHarnessState,
    config: RunnableConfig | None,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    try:
        payload.setdefault("thread_id", _thread_id(state, config))
        emit_run_event(state["run_id"], event_type, payload)
    except Exception:
        pass


def _accuracy(scores: dict[str, Any] | None) -> float:
    if not scores:
        return 0.0
    value = scores.get("accuracy_value")
    if value is None:
        value = scores.get("accuracy")
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _avg_tokens(scores: dict[str, Any] | None) -> float | None:
    if not scores:
        return None
    value = scores.get("avg_tokens")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _record_by_id(
    candidates: list[dict[str, Any]],
    candidate_id: str,
) -> dict[str, Any]:
    for candidate in candidates:
        if candidate.get("candidate_id") == candidate_id:
            return candidate
    raise KeyError(f"unknown candidate id: {candidate_id}")


def _artifact_root(record: dict[str, Any]) -> Path:
    raw = record.get("artifact_root")
    if not raw:
        raise ValueError(f"candidate {record.get('candidate_id')} has no artifact root")
    return Path(str(raw))


def _evaluation_document(run_dir: Path, candidate_id: str) -> dict[str, Any]:
    path = run_dir / "candidates" / candidate_id / "eval-result.json"
    return json.loads(path.read_text())


def _compact_scores(document: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "accuracy",
        "accuracy_value",
        "avg_tokens",
        "candidate",
        "candidate_id",
        "cost_usd",
        "n_tasks",
        "n_trials_per_task",
        "per_task",
        "policy_id",
        "synthetic",
        "tokens",
        "usage",
        "wall_time_s",
    }
    return {key: document[key] for key in keys if key in document}


def _status_value(record: dict[str, Any]) -> str:
    status = record.get("status")
    return status.value if isinstance(status, CandidateStatus) else str(status)


def _update_manifest(path: Path, **updates: Any) -> None:
    manifest = json.loads(path.read_text()) if path.exists() else {}
    updates.setdefault("updated_at", utc_now())
    manifest.update(updates)
    atomic_write_json(path, manifest)


class OuterLoopRunner:
    def __init__(
        self,
        *,
        run_dir: Path,
        repo_root: Path,
        eval_tasks_dir: Path,
        mock_proposer: bool,
        mock_bench: bool,
        trials: int,
        bench_workers: int,
        skill_path: Path | None = None,
        checkpointer: Any = None,
        memory_store: Any = None,
        mode: RunMode | str = RunMode.RESEARCH,
        parent_policy: str = "best_accuracy",
        inner_model: str | None = None,
        proposer_model: str = "opus",
        allow_global_memory: bool | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.repo_root = repo_root
        self.eval_tasks_dir = eval_tasks_dir
        self.mock_proposer = mock_proposer
        self.mock_bench = mock_bench
        self.trials = trials
        self.bench_workers = bench_workers
        self.skill_path = skill_path
        self.checkpointer = checkpointer
        self.memory_store = memory_store
        self.mode = RunMode(mode)
        self.parent_policy = parent_policy
        self.inner_model = inner_model or CodingAgentHarness.MODEL
        self.proposer_model = proposer_model
        self.allow_global_memory = (
            self.mode == RunMode.AUTONOMOUS
            if allow_global_memory is None
            else allow_global_memory
        )
        if self.mode == RunMode.RESEARCH and self.allow_global_memory:
            raise ValueError("research mode forbids global memory")
        if parent_policy not in {"best_accuracy", "pareto_sample"}:
            raise ValueError(f"unknown parent policy: {parent_policy}")

    def _execution_dir(
        self,
        state: MetaHarnessState,
        config: RunnableConfig | None,
    ) -> Path:
        thread_id = _thread_id(state, config)
        if thread_id == state["run_id"]:
            target = self.run_dir
        else:
            branch_id = thread_id.rsplit(".fork.", 1)[-1]
            branch_id = runs_mod.validate_artifact_name(branch_id, kind="branch")
            target = self.run_dir / "branches" / branch_id
        target.mkdir(parents=True, exist_ok=True)
        (target / "candidates").mkdir(exist_ok=True)
        (target / "proposer-sessions").mkdir(exist_ok=True)
        (target / "proposals").mkdir(exist_ok=True)
        return target

    def _tasks(self) -> list[TaskSpec]:
        return discover_tasks(self.eval_tasks_dir, visibility="search")

    def _validate_proposal_metadata(
        self,
        execution_dir: Path,
        iteration: int,
        metadata: dict[str, Any],
        parent_name: str,
    ) -> None:
        if self.mode != RunMode.RESEARCH:
            return
        source_path = metadata.get("source_path")
        class_name = metadata.get("class_name")
        if not source_path or not class_name:
            raise ValueError(
                "research proposals require run-scoped source_path and class_name"
            )
        raw_path = Path(str(source_path))
        resolved = raw_path if raw_path.is_absolute() else self.repo_root / raw_path
        proposal_root = (execution_dir / "proposals" / f"iter-{iteration}").resolve()
        try:
            resolved.resolve().relative_to(proposal_root)
        except ValueError as exc:
            raise ValueError(
                f"research proposal source must be inside {proposal_root}"
            ) from exc
        if metadata.get("parent") not in {None, parent_name}:
            raise ValueError("proposal parent does not match selected parent")

    def _skill_components(self) -> list[str]:
        if self.skill_path is None:
            return []
        return [f"{self.skill_path}:{sha256_file(self.skill_path)}"]

    def _protected_task_strings(self) -> list[str]:
        search_tasks = self._tasks()
        values = [task.id for task in search_tasks]
        values.extend(
            expected_file
            for task in search_tasks
            for expected_file in task.expected_files_changed
        )
        holdout_root = self.repo_root / "eval" / "holdout"
        if holdout_root.exists():
            holdout_tasks = discover_tasks(holdout_root, visibility="holdout")
            values.extend(task.id for task in holdout_tasks)
            values.extend(
                expected_file
                for task in holdout_tasks
                for expected_file in task.expected_files_changed
            )
        return list(dict.fromkeys(values))

    def _policy(self) -> EvaluationPolicy:
        tasks = self._tasks()
        policy_value = {
            "mode": self.mode.value,
            "task_ids": [task.id for task in tasks],
            "task_hashes": [task.sha256 for task in tasks],
            "sandbox_profile": "local-process-v1",
            "runtime_adapter": "task-declared",
            "execution_backend": "fixed-langgraph-v1",
            "inner_model": self.inner_model,
            "model_provider": "anthropic",
            "trials": self.trials,
            "workers": self.bench_workers,
            "allow_global_memory": self.allow_global_memory,
            "allow_recursive_children": False,
            "synthetic": self.mock_bench,
        }
        policy_id = "policy_" + sha256_bytes(canonical_json_bytes(policy_value))[:16]
        return EvaluationPolicy(
            policy_id=policy_id,
            mode=self.mode,
            task_visibility="search",
            sandbox_profile="local-process-v1",
            runtime_adapter="task-declared",
            execution_backend="fixed-langgraph-v1",
            inner_model=self.inner_model,
            trials=self.trials,
            workers=self.bench_workers,
            allow_global_memory=self.allow_global_memory,
            allow_recursive_children=False,
            synthetic=self.mock_bench,
        )

    def _write_manifest(self, execution_dir: Path, *, status: str) -> None:
        policy = self._policy()
        git_commit, git_dirty = capture_git_state(self.repo_root)
        manifest = RunManifest(
            run_id=execution_dir.name,
            mode=self.mode,
            status=status,
            git_commit=git_commit,
            git_dirty=git_dirty,
            runtime_sha256=capture_runtime_sha256(self.repo_root),
            dependency_lock_sha256=(
                sha256_file(self.repo_root / "uv.lock")
                if (self.repo_root / "uv.lock").is_file()
                else None
            ),
            policy=policy,
            parent_policy=self.parent_policy,
            search_task_ids=[task.id for task in self._tasks()],
            holdout_visible=False,
            persistence_backend=(
                "postgres" if self.checkpointer is not None else "memory"
            ),
            synthetic=self.mock_bench,
            mock_proposer=self.mock_proposer,
            mock_bench=self.mock_bench,
            trials=self.trials,
            workers=self.bench_workers,
            proposer_model=self.proposer_model,
            proposer_evidence_access=(
                ["synthetic_fixture"]
                if self.mock_proposer
                else [
                    "evolution_summary",
                    "frontier",
                    "candidate_source",
                    "raw_traces",
                ]
            ),
            human_intervention=False,
            skill_path=str(self.skill_path) if self.skill_path else None,
        )
        path = execution_dir / "manifest.json"
        if path.exists():
            existing = json.loads(path.read_text())
            existing.update(manifest.model_dump(mode="json"))
            atomic_write_json(path, existing)
        else:
            atomic_write_json(path, manifest)

    async def initialize(
        self,
        state: MetaHarnessState,
        config: RunnableConfig = None,
    ) -> dict[str, Any]:
        if state.get("candidates"):
            return {}
        execution_dir = self._execution_dir(state, config)
        self._write_manifest(execution_dir, status="running")
        policy = self._policy()
        provenance = capture_provenance(
            self.repo_root,
            authorization_profile=(
                "trusted-local-research-audited"
                if self.mode == RunMode.RESEARCH
                else "trusted-local-autonomous"
            ),
        )
        artifact = materialize_candidate(
            run_dir=execution_dir,
            repo_root=self.repo_root,
            metadata={
                "name": "baseline",
                "source_path": "agents/baseline.py",
                "class_name": "BaselineHarness",
                "import_path": "agents.baseline:BaselineHarness",
            },
            parent_ids=[],
            policy=policy,
            provenance=provenance,
            components={
                "prompts": ["baseline-defaults"],
                "skills": self._skill_components(),
                "memories": [],
                "subagents": [],
            },
        )
        append_event(
            execution_dir,
            event_type="CandidateMaterialized",
            run_id=state["run_id"],
            entity_type="candidate",
            entity_id=artifact.candidate_id,
            thread_id=_thread_id(state, config),
            payload={
                "candidate_name": artifact.name,
                "source": artifact.source.model_dump(mode="json"),
                "parent_ids": artifact.parent_ids,
            },
        )
        evaluator = Evaluator(
            run_dir=execution_dir,
            repo_root=self.repo_root,
            policy=policy,
            checkpointer=self.checkpointer,
            run_id=state["run_id"],
        )
        if self.mock_bench:
            evaluation = evaluator.evaluate_synthetic_candidate(
                artifact,
                self._tasks(),
                target_accuracy=0.60,
            )
        else:
            evaluation = await evaluator.evaluate_candidate(artifact, self._tasks())
        scores = _compact_scores(
            _evaluation_document(execution_dir, artifact.candidate_id)
        )
        record = CandidateRecord(
            candidate_id=artifact.candidate_id,
            name=artifact.name,
            artifact_path=candidate_manifest_path(
                execution_dir,
                artifact.candidate_id,
            ),
            parent_ids=[],
            parent=None,
            hypothesis="checked-in baseline harness",
            axis="exploration",
            iteration=0,
            status=CandidateStatus.BEST,
            scores=scores,
            import_path="agents.baseline:BaselineHarness",
            cost_usd=None,
            artifact_root=str(execution_dir),
        ).model_dump(mode="json")
        candidates = [record]
        frontier = self._build_frontier(0, candidates)
        runs_mod.write_frontier(execution_dir, frontier)
        self._write_status(execution_dir, record, accepted=True, reason="baseline")
        runs_mod.append_evolution_summary(
            execution_dir,
            self._evolution_row(record, thread_id=_thread_id(state, config)),
        )
        _emit(
            state,
            config,
            "candidate-created",
            self._candidate_event(record, synthetic=evaluation.synthetic),
        )
        _emit(
            state,
            config,
            "eval-result",
            self._eval_event(record),
        )
        _emit(
            state,
            config,
            "state-update",
            {
                "node": "initialize",
                "iteration": 0,
                "summary": {
                    **_summary(state, iteration=0),
                    "candidates_count": 1,
                    "best_candidate": artifact.name,
                    "best_candidate_id": artifact.candidate_id,
                },
            },
        )
        return {
            "candidates": candidates,
            "frontier": frontier.get("_pareto_ids", []),
            "best_candidate": artifact.name,
            "best_candidate_id": artifact.candidate_id,
            "active_candidate_ids": [],
            "parent_policy": self.parent_policy,
            "mode": self.mode.value,
            "evaluation_policy": policy.model_dump(mode="json"),
        }

    async def propose(
        self,
        state: MetaHarnessState,
        config: RunnableConfig = None,
    ) -> dict[str, Any]:
        iteration = state["iteration"] + 1
        execution_dir = self._execution_dir(state, config)
        candidates = [dict(candidate) for candidate in state.get("candidates") or []]
        parent_id = self._select_parent_id(state, candidates)
        parent = _record_by_id(candidates, parent_id)
        parent_artifact = load_candidate_artifact(_artifact_root(parent), parent_id)
        parent_source = _artifact_root(parent) / parent_artifact.source.artifact_path
        try:
            parent_source_path = parent_source.resolve().relative_to(
                self.repo_root.resolve()
            ).as_posix()
        except ValueError:
            parent_source_path = str(parent_source.resolve())
        memory_components: list[str] = []
        if self.mock_proposer:
            payload = await asyncio.to_thread(
                prp.mock_propose,
                run_dir=execution_dir,
                iteration=iteration,
                parent_name=parent["name"],
                repo_root=self.repo_root,
            )
        else:
            if self.skill_path is None:
                raise ValueError("skill_path required for non-mock proposer")
            proposer_prior = state.get("proposer_prior", "")
            if self.allow_global_memory and self.memory_store is not None:
                patterns = await mem.search_patterns(self.memory_store, limit=5)
                memory_components = [
                    f"{pattern.get('key', 'unknown')}:"
                    f"{sha256_bytes(canonical_json_bytes(pattern))}"
                    for pattern in patterns
                ]
                memory_section = mem.format_patterns_for_prompt(patterns)
                if memory_section:
                    proposer_prior = (
                        f"{proposer_prior}\n\n{memory_section}"
                        if proposer_prior
                        else memory_section
                    )
            payload = await asyncio.to_thread(
                prp.claude_propose,
                run_dir=execution_dir,
                iteration=iteration,
                parent_name=parent["name"],
                repo_root=self.repo_root,
                skill_path=self.skill_path,
                proposer_prior=proposer_prior,
                parent_source_path=parent_source_path,
                research_mode=self.mode == RunMode.RESEARCH,
                model=self.proposer_model,
            )
        normalized_payload = payload
        if payload.get("candidates") is None and payload.get("name"):
            candidate_payload = dict(payload)
            candidate_payload.pop("iteration", None)
            normalized_payload = {
                "iteration": iteration,
                "candidates": [candidate_payload],
            }
        pending = PendingEvaluation.model_validate(normalized_payload)
        if pending.iteration != iteration:
            raise ValueError(
                f"proposal iteration mismatch: {pending.iteration} != {iteration}"
            )
        proposed = [
            candidate.model_dump(mode="json", exclude_none=True)
            for candidate in pending.candidates
        ]
        policy = self._policy()
        session_id = self._proposer_session_id(execution_dir, iteration)
        active_ids: list[str] = []
        for metadata in proposed:
            self._validate_proposal_metadata(
                execution_dir,
                iteration,
                metadata,
                parent["name"],
            )
            provenance = capture_provenance(
                self.repo_root,
                authorization_profile=(
                    "trusted-local-research-audited"
                    if self.mode == RunMode.RESEARCH
                    else "trusted-local-autonomous"
                ),
                proposer_session_id=session_id,
                extra={
                    "proposer_model": self.proposer_model,
                    "parent_policy": self.parent_policy,
                    "iteration": iteration,
                },
            )
            artifact = materialize_candidate(
                run_dir=execution_dir,
                repo_root=self.repo_root,
                metadata=metadata,
                parent_ids=[parent_id],
                policy=policy,
                provenance=provenance,
                components={
                    "prompts": ["candidate-source"],
                    "skills": self._skill_components(),
                    "memories": memory_components,
                    "subagents": [],
                },
            )
            append_event(
                execution_dir,
                event_type="CandidateMaterialized",
                run_id=state["run_id"],
                entity_type="candidate",
                entity_id=artifact.candidate_id,
                thread_id=_thread_id(state, config),
                payload={
                    "candidate_name": artifact.name,
                    "source": artifact.source.model_dump(mode="json"),
                    "parent_ids": artifact.parent_ids,
                    "iteration": iteration,
                },
            )
            record = CandidateRecord(
                candidate_id=artifact.candidate_id,
                name=artifact.name,
                artifact_path=candidate_manifest_path(
                    execution_dir,
                    artifact.candidate_id,
                ),
                parent_ids=[parent_id],
                parent=parent["name"],
                hypothesis=str(metadata.get("hypothesis", "")),
                axis=metadata.get("axis", "exploitation"),
                expected_score_delta=metadata.get("expected_score_delta"),
                iteration=iteration,
                status=CandidateStatus.PENDING,
                scores=None,
                import_path=metadata.get("import_path"),
                artifact_root=str(execution_dir),
            ).model_dump(mode="json")
            candidates.append(record)
            active_ids.append(artifact.candidate_id)
            _emit(
                state,
                config,
                "candidate-created",
                self._candidate_event(record, synthetic=self.mock_bench),
            )
        _emit(
            state,
            config,
            "state-update",
            {
                "node": "propose",
                "iteration": iteration,
                "summary": {
                    **_summary(state, iteration=iteration),
                    "candidates_count": len(candidates),
                    "active_candidate_ids": active_ids,
                },
            },
        )
        return {
            "iteration": iteration,
            "candidates": candidates,
            "active_candidate_ids": active_ids,
        }

    async def validate(
        self,
        state: MetaHarnessState,
        config: RunnableConfig = None,
    ) -> dict[str, Any]:
        candidates = [dict(candidate) for candidate in state["candidates"]]
        active_ids = list(state.get("active_candidate_ids") or [])
        for candidate_id in active_ids:
            record = _record_by_id(candidates, candidate_id)
            valid = True
            error: str | None = None
            try:
                artifact = load_candidate_artifact(
                    _artifact_root(record),
                    candidate_id,
                )
                load_candidate_class(
                    _artifact_root(record),
                    artifact,
                    repo_root=self.repo_root,
                    research_mode=self.mode == RunMode.RESEARCH,
                    forbidden_strings=(
                        self._protected_task_strings()
                        if self.mode == RunMode.RESEARCH
                        else None
                    ),
                )
                record["status"] = CandidateStatus.PENDING.value
                record["validation_error"] = None
            except Exception as exc:
                valid = False
                error = str(exc)
                record["status"] = CandidateStatus.INVALID.value
                record["validation_error"] = error
            payload: dict[str, Any] = {
                "candidate": record["name"],
                "candidate_id": candidate_id,
                "valid": valid,
            }
            if error:
                payload["error"] = error
            _emit(state, config, "validate-result", payload)
        _emit(
            state,
            config,
            "state-update",
            {
                "node": "validate",
                "iteration": state["iteration"],
                "summary": _summary(state),
            },
        )
        return {"candidates": candidates}

    async def benchmark(
        self,
        state: MetaHarnessState,
        config: RunnableConfig = None,
    ) -> dict[str, Any]:
        execution_dir = self._execution_dir(state, config)
        candidates = [dict(candidate) for candidate in state["candidates"]]
        active_ids = list(state.get("active_candidate_ids") or [])
        evaluator = Evaluator(
            run_dir=execution_dir,
            repo_root=self.repo_root,
            policy=self._policy(),
            checkpointer=self.checkpointer,
            run_id=state["run_id"],
        )
        for candidate_id in active_ids:
            record = _record_by_id(candidates, candidate_id)
            if _status_value(record) == CandidateStatus.INVALID.value:
                continue
            artifact = load_candidate_artifact(execution_dir, candidate_id)
            try:
                if self.mock_bench:
                    target = min(0.95, 0.60 + state["iteration"] * 0.10)
                    evaluator.evaluate_synthetic_candidate(
                        artifact,
                        self._tasks(),
                        target_accuracy=target,
                    )
                else:
                    await evaluator.evaluate_candidate(artifact, self._tasks())
                record["scores"] = _compact_scores(
                    _evaluation_document(execution_dir, candidate_id)
                )
                record["status"] = CandidateStatus.EVALUATED.value
                record["cost_usd"] = None
            except Exception as exc:
                record["status"] = CandidateStatus.INVALID.value
                record["validation_error"] = str(exc)
            _emit(state, config, "eval-result", self._eval_event(record))
        _emit(
            state,
            config,
            "state-update",
            {
                "node": "benchmark",
                "iteration": state["iteration"],
                "summary": _summary(state),
            },
        )
        return {"candidates": candidates}

    async def update_frontier(
        self,
        state: MetaHarnessState,
        config: RunnableConfig = None,
    ) -> dict[str, Any]:
        execution_dir = self._execution_dir(state, config)
        candidates = [dict(candidate) for candidate in state["candidates"]]
        active_ids = list(state.get("active_candidate_ids") or [])
        frontier = self._build_frontier(state["iteration"], candidates)
        frontier_ids = list(frontier.get("_pareto_ids") or [])
        selected_id = self._select_best_id(candidates, frontier_ids, state["iteration"])
        selected = _record_by_id(candidates, selected_id)
        for record in candidates:
            candidate_id = str(record.get("candidate_id"))
            if candidate_id == selected_id:
                record["status"] = CandidateStatus.BEST.value
            elif candidate_id in frontier_ids:
                record["status"] = CandidateStatus.FRONTIER.value
            elif record.get("scores"):
                record["status"] = CandidateStatus.REJECTED.value
        for candidate_id in active_ids:
            record = _record_by_id(candidates, candidate_id)
            parent_ids = record.get("parent_ids") or []
            parent_accuracy = 0.0
            if parent_ids:
                parent_accuracy = _accuracy(
                    _record_by_id(candidates, parent_ids[0]).get("scores")
                )
            record["delta"] = round(_accuracy(record.get("scores")) - parent_accuracy, 6)
            accepted = candidate_id in frontier_ids
            self._write_status(
                execution_dir,
                record,
                accepted=accepted,
                reason="frontier" if accepted else "dominated",
            )
            runs_mod.append_evolution_summary(
                execution_dir,
                self._evolution_row(record, thread_id=_thread_id(state, config)),
            )
        runs_mod.write_frontier(execution_dir, frontier)
        append_event(
            execution_dir,
            event_type="FrontierUpdated",
            run_id=state["run_id"],
            entity_type="run",
            entity_id=state["run_id"],
            thread_id=_thread_id(state, config),
            payload={
                "iteration": state["iteration"],
                "frontier_ids": frontier_ids,
                "best_candidate_id": selected_id,
                "parent_policy": self.parent_policy,
            },
        )
        if (
            self.allow_global_memory
            and self.memory_store is not None
            and selected_id in active_ids
        ):
            await mem.add_pattern(
                self.memory_store,
                pattern=str(selected.get("hypothesis") or "unknown hypothesis"),
                mechanism_axis=str(selected.get("axis") or "unknown"),
                score_delta=float(selected.get("delta") or 0.0),
                run_id=state["run_id"],
                candidate_id=selected_id,
                scope="global",
            )
            _emit(
                state,
                config,
                "memory-pattern-stored",
                {
                    "namespace": ["learned_patterns", "coding-agent"],
                    "key": selected_id,
                    "score_delta": selected.get("delta"),
                    "candidate_id": selected_id,
                },
            )
        frontier_names = [
            _record_by_id(candidates, candidate_id)["name"]
            for candidate_id in frontier_ids
        ]
        _emit(
            state,
            config,
            "frontier-updated",
            {
                "candidate": selected["name"],
                "candidate_id": selected_id,
                "iteration": state["iteration"],
                "frontier": frontier_names,
                "frontier_ids": frontier_ids,
                "best_candidate": selected["name"],
                "best_candidate_id": selected_id,
                "best_score": _accuracy(selected.get("scores")),
                "status": "best",
                "accepted": selected_id in active_ids,
                "delta": selected.get("delta"),
                "scores": selected.get("scores"),
                "synthetic": bool((selected.get("scores") or {}).get("synthetic")),
            },
        )
        _emit(
            state,
            config,
            "iteration-complete",
            {
                "iteration": state["iteration"],
                "candidate": selected["name"],
                "candidate_id": selected_id,
                "status": (
                    "improved" if selected_id in active_ids else "no_improvement"
                ),
            },
        )
        _emit(
            state,
            config,
            "state-update",
            {
                "node": "update_frontier",
                "iteration": state["iteration"],
                "summary": {
                    **_summary(state),
                    "best_candidate": selected["name"],
                    "best_candidate_id": selected_id,
                },
            },
        )
        return {
            "candidates": candidates,
            "frontier": frontier_ids,
            "best_candidate": selected["name"],
            "best_candidate_id": selected_id,
            "active_candidate_ids": [],
            "budget_remaining": state["budget_remaining"] - 1,
        }

    def _candidate_event(
        self,
        record: dict[str, Any],
        *,
        synthetic: bool,
    ) -> dict[str, Any]:
        return {
            "candidate": record["name"],
            "candidate_id": record["candidate_id"],
            "parent_candidate_name": record.get("parent"),
            "parent": record.get("parent"),
            "parent_ids": record.get("parent_ids", []),
            "import_path": record.get("import_path"),
            "iteration": record.get("iteration", 0),
            "status": record.get("status", "materialized"),
            "scores": {"accuracy": 0.0},
            "delta": record.get("delta"),
            "hypothesis": record.get("hypothesis", ""),
            "axis": record.get("axis", "exploitation"),
            "synthetic": synthetic,
        }

    def _eval_event(self, record: dict[str, Any]) -> dict[str, Any]:
        scores = record.get("scores") or {}
        return {
            "candidate": record["name"],
            "candidate_id": record["candidate_id"],
            "parent_candidate_name": record.get("parent"),
            "parent": record.get("parent"),
            "parent_ids": record.get("parent_ids", []),
            "iteration": record.get("iteration", 0),
            "status": record.get("status"),
            "accuracy": _accuracy(scores),
            "scores": scores,
            "per_task": scores.get("per_task", {}),
            "tokens": scores.get("tokens", {}),
            "cost_usd": scores.get("cost_usd"),
            "hypothesis": record.get("hypothesis", ""),
            "axis": record.get("axis"),
            "synthetic": bool(scores.get("synthetic")),
        }

    def _evolution_row(
        self,
        record: dict[str, Any],
        *,
        thread_id: str,
    ) -> dict[str, Any]:
        scores = record.get("scores") or {}
        accuracy = _accuracy(scores)
        return {
            "iteration": record.get("iteration", 0),
            "candidate": record["name"],
            "candidate_id": record["candidate_id"],
            "artifact_path": record["artifact_path"],
            "parent_candidate_name": record.get("parent"),
            "parent": record.get("parent"),
            "parent_ids": record.get("parent_ids", []),
            "axis": record.get("axis"),
            "status": record.get("status"),
            "hypothesis": record.get("hypothesis", ""),
            "scores": scores,
            "delta": record.get("delta"),
            "outcome": (
                f"{accuracy:.1%} ({float(record.get('delta') or 0):+.1%})"
                if scores
                else "invalid"
            ),
            "tokens": scores.get("avg_tokens"),
            "cost_usd": scores.get("cost_usd"),
            "synthetic": bool(scores.get("synthetic")),
            "thread_id": thread_id,
        }

    def _write_status(
        self,
        execution_dir: Path,
        record: dict[str, Any],
        *,
        accepted: bool,
        reason: str,
    ) -> None:
        atomic_write_json(
            execution_dir
            / "candidates"
            / record["candidate_id"]
            / "status.json",
            {
                "candidate": record["name"],
                "candidate_id": record["candidate_id"],
                "accepted": accepted,
                "parent": record.get("parent"),
                "parent_ids": record.get("parent_ids", []),
                "delta": record.get("delta"),
                "reason": reason,
                "synthetic": bool((record.get("scores") or {}).get("synthetic")),
            },
        )

    def _build_frontier(
        self,
        iteration: int,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        evaluated = [
            {
                "candidate_id": candidate["candidate_id"],
                "name": candidate["name"],
                "accuracy": _accuracy(candidate.get("scores")),
                "avg_tokens": _avg_tokens(candidate.get("scores")),
                "token_measurement_status": (
                    (candidate.get("scores") or {})
                    .get("tokens", {})
                    .get("measurement_status", "unknown")
                ),
                "synthetic": bool(
                    (candidate.get("scores") or {}).get("synthetic")
                ),
            }
            for candidate in candidates
            if candidate.get("scores")
        ]
        per_task_bests: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            scores = candidate.get("scores") or {}
            for task_id, info in scores.get("per_task", {}).items():
                pass_rate = float(info.get("pass_rate", 0.0))
                current = per_task_bests.get(task_id)
                if current is None or pass_rate > current["pass_rate"]:
                    per_task_bests[task_id] = {
                        "best_candidate": candidate["name"],
                        "best_candidate_id": candidate["candidate_id"],
                        "pass_rate": pass_rate,
                    }
        return fr.build_frontier_val(iteration, evaluated, per_task_bests)

    def _select_parent_id(
        self,
        state: MetaHarnessState,
        candidates: list[dict[str, Any]],
    ) -> str:
        if self.parent_policy == "pareto_sample" and state.get("frontier"):
            frontier_ids = sorted(str(value) for value in state["frontier"])
            return frontier_ids[state["iteration"] % len(frontier_ids)]
        best_candidate_id = state.get("best_candidate_id")
        if best_candidate_id:
            return str(best_candidate_id)
        if not candidates:
            raise ValueError("outer loop has no baseline candidate")
        return str(candidates[0]["candidate_id"])

    def _select_best_id(
        self,
        candidates: list[dict[str, Any]],
        frontier_ids: list[str],
        iteration: int,
    ) -> str:
        if not frontier_ids:
            raise ValueError("frontier is empty after evaluation")
        if self.parent_policy == "pareto_sample":
            ordered = sorted(frontier_ids)
            return ordered[iteration % len(ordered)]
        frontier_records = [
            _record_by_id(candidates, candidate_id)
            for candidate_id in frontier_ids
        ]
        return str(
            max(
                frontier_records,
                key=lambda candidate: (
                    _accuracy(candidate.get("scores")),
                    -(
                        _avg_tokens(candidate.get("scores"))
                        if _avg_tokens(candidate.get("scores")) is not None
                        else float("inf")
                    ),
                    candidate["candidate_id"],
                ),
            )["candidate_id"]
        )

    def _proposer_session_id(self, execution_dir: Path, iteration: int) -> str | None:
        path = execution_dir / "proposer-sessions" / f"iter-{iteration}" / "session.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text()).get("session_id")
        except (OSError, json.JSONDecodeError):
            return None

    def _route_after_update(self, state: MetaHarnessState) -> str:
        return "propose" if state["budget_remaining"] > 0 else "end"

    def build(self) -> Any:
        graph: StateGraph = StateGraph(MetaHarnessState)
        graph.add_node("initialize", self.initialize)
        graph.add_node("propose", self.propose)
        graph.add_node("validate", self.validate)
        graph.add_node("benchmark", self.benchmark)
        graph.add_node("update_frontier", self.update_frontier)
        graph.add_edge(START, "initialize")
        graph.add_edge("initialize", "propose")
        graph.add_edge("propose", "validate")
        graph.add_edge("validate", "benchmark")
        graph.add_edge("benchmark", "update_frontier")
        graph.add_conditional_edges(
            "update_frontier",
            self._route_after_update,
            {"propose": "propose", "end": END},
        )
        return (
            graph.compile(checkpointer=self.checkpointer)
            if self.checkpointer is not None
            else graph.compile()
        )


async def run_outer_loop(
    *,
    run_dir: Path,
    repo_root: Path,
    eval_tasks_dir: Path,
    mock_proposer: bool,
    mock_bench: bool,
    trials: int,
    bench_workers: int,
    budget: int,
    skill_path: Path | None = None,
    checkpointer: Any = None,
    memory_store: Any = None,
    mode: RunMode | str = RunMode.RESEARCH,
    parent_policy: str = "best_accuracy",
    inner_model: str | None = None,
    proposer_model: str = "opus",
    allow_global_memory: bool | None = None,
) -> MetaHarnessState:
    runner = OuterLoopRunner(
        run_dir=run_dir,
        repo_root=repo_root,
        eval_tasks_dir=eval_tasks_dir,
        mock_proposer=mock_proposer,
        mock_bench=mock_bench,
        trials=trials,
        bench_workers=bench_workers,
        skill_path=skill_path,
        checkpointer=checkpointer,
        memory_store=memory_store,
        mode=mode,
        parent_policy=parent_policy,
        inner_model=inner_model,
        proposer_model=proposer_model,
        allow_global_memory=allow_global_memory,
    )
    initial: MetaHarnessState = {
        "run_id": run_dir.name,
        "iteration": 0,
        "budget_remaining": budget,
        "candidates": [],
        "frontier": [],
        "best_candidate": None,
        "best_candidate_id": None,
        "active_candidate_ids": [],
        "proposer_prior": "",
        "parent_policy": parent_policy,
        "mode": RunMode(mode).value,
        "evaluation_policy": runner._policy().model_dump(mode="json"),
    }
    runner._write_manifest(run_dir, status="running")
    manifest_path = run_dir / "manifest.json"
    _update_manifest(manifest_path, budget=budget)
    if lifecycle_state(run_dir, entity_type="run", entity_id=run_dir.name) is None:
        for state_name in ("created", "admitted", "running"):
            transition_lifecycle(
                run_dir,
                run_id=run_dir.name,
                entity_type="run",
                entity_id=run_dir.name,
                to_state=state_name,
                thread_id=run_dir.name,
            )
    graph = runner.build()
    try:
        final = await graph.ainvoke(
            initial,
            config={
                "configurable": {"thread_id": run_dir.name},
                "recursion_limit": 300,
            },
        )
    except asyncio.CancelledError:
        transition_lifecycle(
            run_dir,
            run_id=run_dir.name,
            entity_type="run",
            entity_id=run_dir.name,
            to_state="waiting",
            thread_id=run_dir.name,
            reason="outer invocation interrupted; resumable checkpoint retained",
        )
        _update_manifest(manifest_path, status="waiting")
        raise
    except Exception as exc:
        transition_lifecycle(
            run_dir,
            run_id=run_dir.name,
            entity_type="run",
            entity_id=run_dir.name,
            to_state="failed",
            thread_id=run_dir.name,
            reason=str(exc),
        )
        _update_manifest(manifest_path, status="failed", error=str(exc))
        raise
    transition_lifecycle(
        run_dir,
        run_id=run_dir.name,
        entity_type="run",
        entity_id=run_dir.name,
        to_state="succeeded",
        thread_id=run_dir.name,
    )
    _update_manifest(
        manifest_path,
        status="completed",
        current_iteration=final.get("iteration"),
        best_candidate=final.get("best_candidate"),
        best_candidate_id=final.get("best_candidate_id"),
    )
    return final  # type: ignore[return-value]


async def resume_outer_loop(
    *,
    run_dir: Path,
    repo_root: Path,
    eval_tasks_dir: Path,
    checkpointer: Any,
    skill_path: Path | None = None,
    memory_store: Any = None,
) -> MetaHarnessState:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"manifest.json missing in {run_dir}; cannot resume without run config"
        )
    manifest = json.loads(manifest_path.read_text())
    policy = manifest.get("policy") or {}
    runner = OuterLoopRunner(
        run_dir=run_dir,
        repo_root=repo_root,
        eval_tasks_dir=eval_tasks_dir,
        mock_proposer=bool(manifest.get("mock_proposer", False)),
        mock_bench=bool(manifest.get("mock_bench", False)),
        trials=int(manifest.get("trials", 5)),
        bench_workers=int(manifest.get("workers", 3)),
        skill_path=skill_path,
        checkpointer=checkpointer,
        memory_store=memory_store,
        mode=manifest.get("mode", RunMode.RESEARCH.value),
        parent_policy=manifest.get("parent_policy", "best_accuracy"),
        inner_model=policy.get("inner_model"),
        proposer_model=manifest.get("proposer_model", "opus"),
        allow_global_memory=policy.get("allow_global_memory"),
    )
    current_lifecycle = lifecycle_state(
        run_dir,
        entity_type="run",
        entity_id=run_dir.name,
    )
    if current_lifecycle is None:
        for state_name in ("created", "admitted", "running"):
            transition_lifecycle(
                run_dir,
                run_id=run_dir.name,
                entity_type="run",
                entity_id=run_dir.name,
                to_state=state_name,
                thread_id=run_dir.name,
                reason="legacy run adopted for resume",
            )
    elif current_lifecycle in {"waiting", "abandoned"}:
        transition_lifecycle(
            run_dir,
            run_id=run_dir.name,
            entity_type="run",
            entity_id=run_dir.name,
            to_state="running",
            thread_id=run_dir.name,
            reason="resumed from checkpoint",
        )
    elif current_lifecycle == "succeeded":
        graph = runner.build()
        snapshot = await graph.aget_state(
            {"configurable": {"thread_id": run_dir.name}}
        )
        return snapshot.values  # type: ignore[return-value]
    elif current_lifecycle != "running":
        raise ValueError(f"run in terminal lifecycle state cannot resume: {current_lifecycle}")
    _update_manifest(manifest_path, status="running")
    graph = runner.build()
    try:
        final = await graph.ainvoke(
            None,
            config={
                "configurable": {"thread_id": run_dir.name},
                "recursion_limit": 300,
            },
        )
    except asyncio.CancelledError:
        if lifecycle_state(run_dir, entity_type="run", entity_id=run_dir.name) == "running":
            transition_lifecycle(
                run_dir,
                run_id=run_dir.name,
                entity_type="run",
                entity_id=run_dir.name,
                to_state="waiting",
                thread_id=run_dir.name,
                reason="resume interrupted; checkpoint retained",
            )
        _update_manifest(manifest_path, status="waiting")
        raise
    except Exception as exc:
        if lifecycle_state(run_dir, entity_type="run", entity_id=run_dir.name) == "running":
            transition_lifecycle(
                run_dir,
                run_id=run_dir.name,
                entity_type="run",
                entity_id=run_dir.name,
                to_state="failed",
                thread_id=run_dir.name,
                reason=str(exc),
            )
        _update_manifest(manifest_path, status="failed", error=str(exc))
        raise
    if lifecycle_state(run_dir, entity_type="run", entity_id=run_dir.name) == "running":
        transition_lifecycle(
            run_dir,
            run_id=run_dir.name,
            entity_type="run",
            entity_id=run_dir.name,
            to_state="succeeded",
            thread_id=run_dir.name,
        )
    _update_manifest(
        manifest_path,
        status="completed",
        current_iteration=final.get("iteration"),
        best_candidate=final.get("best_candidate"),
        best_candidate_id=final.get("best_candidate_id"),
    )
    return final  # type: ignore[return-value]
