"""Candidate, provenance, and measurement contract tests."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.meta_harness.candidates import (
    load_candidate_artifact,
    load_candidate_class,
    locate_candidate,
    materialize_candidate,
    mirror_candidate_artifact,
)
from app.meta_harness.contracts import (
    ComponentKind,
    EvaluationPolicy,
    MeasurementStatus,
    MetricValue,
    PendingEvaluation,
    Provenance,
)


def _policy() -> EvaluationPolicy:
    return EvaluationPolicy(
        policy_id="search-v1",
        inner_model="claude-haiku-4-5-20251001",
    )


def _provenance() -> Provenance:
    return Provenance(
        git_commit="abc123",
        git_dirty=False,
        authorization_profile="trusted-local-research",
    )


def _candidate_source(repo_root: Path) -> Path:
    source = repo_root / "proposals" / "candidate.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from app.meta_harness.harness import CodingAgentHarness\n\n"
        "class CandidateHarness(CodingAgentHarness):\n"
        "    SYSTEM_PROMPT = 'immutable candidate'\n"
    )
    return source


def test_unknown_measurement_cannot_encode_zero() -> None:
    metric = MetricValue.unknown(unit="tokens")
    assert metric.value is None
    assert metric.status == MeasurementStatus.UNKNOWN
    with pytest.raises(ValidationError):
        MetricValue(value=0, status=MeasurementStatus.UNKNOWN, unit="tokens")


def test_synthetic_measurement_is_explicit() -> None:
    metric = MetricValue.synthetic(42, unit="tokens", source="mock-bench-v1")
    assert metric.value == 42
    assert metric.status == MeasurementStatus.SYNTHETIC


def test_pending_evaluation_contract_rejects_unresolvable_candidates() -> None:
    with pytest.raises(ValidationError, match="source_path or import_path"):
        PendingEvaluation.model_validate(
            {
                "iteration": 1,
                "candidates": [
                    {
                        "name": "missing-source",
                        "class_name": "MissingSourceHarness",
                    }
                ],
            }
        )


def test_candidate_components_are_typed_and_hashed(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    source = _candidate_source(repo_root)
    digest = "a" * 64
    artifact = materialize_candidate(
        run_dir=run_dir,
        repo_root=repo_root,
        metadata={
            "name": "candidate-a",
            "source_path": str(source.relative_to(repo_root)),
            "class_name": "CandidateHarness",
        },
        parent_ids=[],
        policy=_policy(),
        provenance=_provenance(),
        components={
            "prompts": ["prompt.default.v1"],
            "skills": [f"skill.coding-agent.v2:{digest}"],
        },
    )

    assert [component.kind for component in artifact.components] == [
        ComponentKind.PROMPT,
        ComponentKind.SKILL,
    ]
    assert artifact.components[1].sha256 == digest


def test_runtime_fingerprint_changes_candidate_identity(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    source = _candidate_source(repo_root)
    metadata = {
        "name": "candidate-a",
        "source_path": str(source.relative_to(repo_root)),
        "class_name": "CandidateHarness",
    }
    first = materialize_candidate(
        run_dir=run_dir,
        repo_root=repo_root,
        metadata=metadata,
        parent_ids=[],
        policy=_policy(),
        provenance=Provenance(
            git_commit="abc123",
            git_dirty=True,
            runtime_sha256="runtime-a",
            authorization_profile="trusted-local-research",
        ),
    )
    second = materialize_candidate(
        run_dir=run_dir,
        repo_root=repo_root,
        metadata=metadata,
        parent_ids=[],
        policy=_policy(),
        provenance=Provenance(
            git_commit="abc123",
            git_dirty=True,
            runtime_sha256="runtime-b",
            authorization_profile="trusted-local-research",
        ),
    )
    assert first.candidate_id != second.candidate_id


def test_concurrent_materialization_publishes_one_candidate(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    source = _candidate_source(repo_root)
    metadata = {
        "name": "candidate-a",
        "source_path": str(source.relative_to(repo_root)),
        "class_name": "CandidateHarness",
    }

    def materialize() -> CandidateArtifact:
        return materialize_candidate(
            run_dir=run_dir,
            repo_root=repo_root,
            metadata=metadata,
            parent_ids=[],
            policy=_policy(),
            provenance=_provenance(),
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        artifacts = list(pool.map(lambda _index: materialize(), range(8)))

    candidate_ids = {artifact.candidate_id for artifact in artifacts}
    assert len(candidate_ids) == 1
    candidate_id = candidate_ids.pop()
    index = json.loads((run_dir / "candidates" / "index.json").read_text())
    assert index["candidate_ids"] == [candidate_id]
    load_candidate_artifact(run_dir, candidate_id)


def test_candidate_source_is_immutable_after_materialization(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    source = _candidate_source(repo_root)
    artifact = materialize_candidate(
        run_dir=run_dir,
        repo_root=repo_root,
        metadata={
            "name": "candidate-a",
            "source_path": str(source.relative_to(repo_root)),
            "class_name": "CandidateHarness",
        },
        parent_ids=[],
        policy=_policy(),
        provenance=_provenance(),
    )
    immutable_source = run_dir / artifact.source.artifact_path
    original = immutable_source.read_text()
    source.write_text("raise RuntimeError('root source changed')\n")
    loaded = load_candidate_artifact(run_dir, artifact.candidate_id)
    assert loaded.source.sha256 == artifact.source.sha256
    assert immutable_source.read_text() == original


def test_two_runs_materialize_separate_candidate_bytes(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    source = _candidate_source(repo_root)
    run_a = repo_root / "runs" / "run-a"
    run_b = repo_root / "runs" / "run-b"
    run_a.mkdir(parents=True)
    run_b.mkdir(parents=True)
    metadata = {
        "name": "candidate-a",
        "source_path": str(source.relative_to(repo_root)),
        "class_name": "CandidateHarness",
    }
    artifact_a = materialize_candidate(
        run_dir=run_a,
        repo_root=repo_root,
        metadata=metadata,
        parent_ids=[],
        policy=_policy(),
        provenance=_provenance(),
    )
    artifact_b = materialize_candidate(
        run_dir=run_b,
        repo_root=repo_root,
        metadata=metadata,
        parent_ids=[],
        policy=_policy(),
        provenance=_provenance(),
    )
    assert artifact_a.candidate_id == artifact_b.candidate_id
    assert (run_a / artifact_a.source.artifact_path).is_file()
    assert (run_b / artifact_b.source.artifact_path).is_file()
    assert (run_a / artifact_a.source.artifact_path).resolve() != (
        run_b / artifact_b.source.artifact_path
    ).resolve()


def test_branch_candidate_can_be_located_and_mirrored_to_run_archive(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run-a"
    branch_dir = run_dir / "branches" / "branch-a"
    branch_dir.mkdir(parents=True)
    source = _candidate_source(repo_root)
    artifact = materialize_candidate(
        run_dir=branch_dir,
        repo_root=repo_root,
        metadata={
            "name": "branch-candidate",
            "source_path": str(source.relative_to(repo_root)),
            "class_name": "CandidateHarness",
        },
        parent_ids=[],
        policy=_policy(),
        provenance=_provenance(),
    )

    located_root, located_id = locate_candidate(run_dir, artifact.candidate_id)
    assert located_root == branch_dir
    assert located_id == artifact.candidate_id

    mirrored = mirror_candidate_artifact(branch_dir, run_dir, artifact.candidate_id)
    assert mirrored == artifact
    assert (run_dir / "candidates" / artifact.candidate_id / "candidate.json").exists()
    resolved_root, resolved_id = locate_candidate(run_dir, "branch-candidate")
    assert resolved_root == run_dir
    assert resolved_id == artifact.candidate_id


def test_candidate_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    source = _candidate_source(repo_root)
    artifact = materialize_candidate(
        run_dir=run_dir,
        repo_root=repo_root,
        metadata={
            "name": "candidate-a",
            "source_path": str(source.relative_to(repo_root)),
            "class_name": "CandidateHarness",
        },
        parent_ids=[],
        policy=_policy(),
        provenance=_provenance(),
    )
    (run_dir / artifact.source.artifact_path).write_text("tampered\n")
    with pytest.raises(ValueError, match="mismatch"):
        load_candidate_artifact(run_dir, artifact.candidate_id)


def test_research_candidate_policy_rejects_holdout_leakage(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    source = repo_root / "proposals" / "leaky.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from app.meta_harness.harness import CodingAgentHarness\n\n"
        "class LeakyHarness(CodingAgentHarness):\n"
        "    HOLDOUT = 'eval/holdout/task-secret'\n"
    )
    artifact = materialize_candidate(
        run_dir=run_dir,
        repo_root=repo_root,
        metadata={
            "name": "leaky",
            "source_path": str(source.relative_to(repo_root)),
            "class_name": "LeakyHarness",
        },
        parent_ids=[],
        policy=_policy(),
        provenance=_provenance(),
    )

    with pytest.raises(ValueError, match="protected task data"):
        load_candidate_class(
            run_dir,
            artifact,
            repo_root=repo_root,
            research_mode=True,
        )


def test_materialized_candidate_class_loads_by_id(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    source = _candidate_source(repo_root)
    artifact = materialize_candidate(
        run_dir=run_dir,
        repo_root=repo_root,
        metadata={
            "name": "candidate-a",
            "source_path": str(source.relative_to(repo_root)),
            "class_name": "CandidateHarness",
        },
        parent_ids=[],
        policy=_policy(),
        provenance=_provenance(),
    )
    candidate_class = load_candidate_class(
        run_dir,
        artifact,
        repo_root=repo_root,
        research_mode=True,
    )
    assert candidate_class.__name__ == "CandidateHarness"
    assert not (run_dir / artifact.source.artifact_path).parent.joinpath("__pycache__").exists()
