"""Unified evaluator and truthful measurement tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.meta_harness.candidates import materialize_candidate
from app.meta_harness.contracts import (
    EvaluationPolicy,
    MeasurementStatus,
    Provenance,
    TaskSpec,
)
from app.meta_harness.evaluator import (
    EvaluationInfrastructureError,
    Evaluator,
    _instantiate_harness,
)
from app.meta_harness.harness import CodingAgentHarness


def _source(repo_root: Path) -> Path:
    source = repo_root / "proposals" / "candidate.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from types import SimpleNamespace\n"
        "from app.meta_harness.harness import CodingAgentHarness\n\n"
        "class CandidateHarness(CodingAgentHarness):\n"
        "    def __init__(self):\n"
        "        pass\n\n"
        "    async def _call_llm(self, messages, tools, *, tool_choice=None):\n"
        "        usage = SimpleNamespace(input_tokens=3, output_tokens=2, "
        "cache_read_input_tokens=1, cache_creation_input_tokens=0)\n"
        "        if tools[0]['name'] == 'submit_plan':\n"
        "            block = SimpleNamespace(type='tool_use', name='submit_plan', "
        "id='plan', input={'summary': 'finish', 'steps': []})\n"
        "        else:\n"
        "            block = SimpleNamespace(type='tool_use', name='task_complete', "
        "id='done', input={})\n"
        "        return SimpleNamespace(content=[block], usage=usage)\n"
    )
    return source


def _task(repo_root: Path) -> TaskSpec:
    task_dir = repo_root / "eval" / "tasks" / "task-a"
    (task_dir / "workspace").mkdir(parents=True)
    return TaskSpec(
        id="task-a",
        tier="smoke",
        instruction="finish",
        test_command="true",
        expected_files_changed=[],
        runtime_adapter="generic-command-v1",
        visibility="search",
        source_path=str(task_dir),
        sha256="task-sha",
    )


def _artifact(
    repo_root: Path,
    run_dir: Path,
    policy: EvaluationPolicy,
    source: Path | None = None,
):
    source = source or _source(repo_root)
    return materialize_candidate(
        run_dir=run_dir,
        repo_root=repo_root,
        metadata={
            "name": "candidate-a",
            "source_path": str(source.relative_to(repo_root)),
            "class_name": "CandidateHarness",
        },
        parent_ids=[],
        policy=policy,
        provenance=Provenance(
            git_commit="abc",
            git_dirty=False,
            authorization_profile="trusted-local-research",
        ),
    )


def test_evaluator_enforces_policy_turn_budgets() -> None:
    class HighBudgetHarness(CodingAgentHarness):
        MAX_ACT_TURNS = 100
        MAX_VERIFY_RETRIES = 10

        def __init__(self) -> None:
            pass

    policy = EvaluationPolicy(
        policy_id="policy",
        inner_model="fixed-model",
        runtime_adapter="generic-command-v1",
        max_act_turns=15,
        max_verify_retries=2,
    )
    harness = _instantiate_harness(HighBudgetHarness, policy, seed=101)
    assert harness.MAX_ACT_TURNS == 15
    assert harness.MAX_VERIFY_RETRIES == 2
    assert harness.SEED == 101


async def test_real_evaluator_records_usage_and_unknown_cost(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    policy = EvaluationPolicy(
        policy_id="search-v1",
        inner_model="fixed-model",
        runtime_adapter="generic-command-v1",
        trials=1,
        workers=1,
    )
    artifact = _artifact(repo_root, run_dir, policy)
    evaluator = Evaluator(
        run_dir=run_dir,
        repo_root=repo_root,
        policy=policy,
    )

    result = await evaluator.evaluate_candidate(artifact, [_task(repo_root)])

    assert result.accuracy.value == 1.0
    assert result.accuracy.status == MeasurementStatus.MEASURED
    assert result.usage.input_tokens.value == 6
    assert result.usage.output_tokens.value == 4
    assert result.usage.cached_tokens.value == 2
    assert result.usage.estimated_cost_usd.value is None
    assert result.usage.estimated_cost_usd.status == MeasurementStatus.UNKNOWN
    assert result.task_results[0].scope_summary["status"] == "measured"
    assert result.task_results[0].lint_summary["status"] == "unknown"
    assert result.artifact_refs
    assert result.task_results[0].artifact_refs
    saved = json.loads(
        (
            run_dir
            / "candidates"
            / artifact.candidate_id
            / "eval-result.json"
        ).read_text()
    )
    assert saved["tokens"]["measurement_status"] == "measured"
    assert saved["cost_usd"] is None
    assert saved["synthetic"] is False


async def test_evaluator_aborts_on_infrastructure_failure(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    source = repo_root / "proposals" / "broken.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from app.meta_harness.harness import CodingAgentHarness\n\n"
        "class BrokenHarness(CodingAgentHarness):\n"
        "    def __init__(self):\n"
        "        raise RuntimeError('provider unavailable')\n"
    )
    policy = EvaluationPolicy(
        policy_id="search-v1",
        inner_model="fixed-model",
        runtime_adapter="generic-command-v1",
        trials=1,
        workers=1,
    )
    artifact = materialize_candidate(
        run_dir=run_dir,
        repo_root=repo_root,
        metadata={
            "name": "broken",
            "source_path": str(source.relative_to(repo_root)),
            "class_name": "BrokenHarness",
        },
        parent_ids=[],
        policy=policy,
        provenance=Provenance(
            git_commit="abc",
            git_dirty=False,
            authorization_profile="trusted-local-research",
        ),
    )
    evaluator = Evaluator(
        run_dir=run_dir,
        repo_root=repo_root,
        policy=policy,
    )

    with pytest.raises(EvaluationInfrastructureError):
        await evaluator.evaluate_candidate(artifact, [_task(repo_root)])


async def test_research_evaluator_rejects_model_drift(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    source = _source(repo_root)
    source.write_text(
        source.read_text().replace(
            "return SimpleNamespace(content=[block], usage=usage)",
            "return SimpleNamespace(content=[block], usage=usage, model='wrong-model')",
        )
    )
    policy = EvaluationPolicy(
        policy_id="search-v1",
        inner_model="fixed-model",
        runtime_adapter="generic-command-v1",
        trials=1,
        workers=1,
    )
    artifact = _artifact(repo_root, run_dir, policy, source)
    evaluator = Evaluator(
        run_dir=run_dir,
        repo_root=repo_root,
        policy=policy,
    )

    with pytest.raises(EvaluationInfrastructureError, match="policy"):
        await evaluator.evaluate_candidate(artifact, [_task(repo_root)])


def test_mock_evaluator_labels_every_fixture_synthetic(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    policy = EvaluationPolicy(
        policy_id="mock-v1",
        inner_model="fixed-model",
        runtime_adapter="generic-command-v1",
        trials=2,
        workers=1,
        synthetic=True,
    )
    artifact = _artifact(repo_root, run_dir, policy)
    evaluator = Evaluator(
        run_dir=run_dir,
        repo_root=repo_root,
        policy=policy,
    )

    result = evaluator.evaluate_synthetic_candidate(
        artifact,
        [_task(repo_root)],
        target_accuracy=0.5,
    )

    assert result.synthetic is True
    assert result.accuracy.status == MeasurementStatus.SYNTHETIC
    assert all(task_result.synthetic for task_result in result.task_results)
    assert result.usage.input_tokens.status == MeasurementStatus.SYNTHETIC
    assert result.usage.billed_cost_usd.status == MeasurementStatus.NOT_APPLICABLE
    assert result.artifact_refs
