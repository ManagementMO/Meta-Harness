"""Experiment bundle and repeated-run reporting tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.meta_harness.experiments import (
    compare_runs,
    export_experiment_bundle,
    verify_experiment_bundle,
)
from app.meta_harness.provenance import capture_runtime_sha256


def _run(root: Path, name: str, accuracy: float, *, synthetic: bool = False) -> Path:
    run_dir = root / name
    candidate_id = "cand_" + hashlib.sha256(name.encode()).hexdigest()[:16]
    candidate_dir = run_dir / "candidates" / candidate_id
    (candidate_dir / "source").mkdir(parents=True)
    (candidate_dir / "source" / "harness.py").write_text("class Harness: pass\n")
    (candidate_dir / "candidate.json").write_text(
        json.dumps({"candidate_id": candidate_id, "name": "candidate"})
    )
    (candidate_dir / "eval-result.json").write_text(
        json.dumps(
            {
                "candidate_id": candidate_id,
                "accuracy_value": accuracy,
                "accuracy": {
                    "value": accuracy,
                    "status": "synthetic" if synthetic else "measured",
                },
                "per_task": {},
                "task_results": [],
                "synthetic": synthetic,
            }
        )
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": name,
                "git_commit": "abc",
                "git_dirty": False,
                "mode": "research",
                "policy": {"policy_id": "policy-v1"},
                "parent_policy": "best_accuracy",
                "budget": 1,
                "synthetic": synthetic,
                "best_candidate_id": candidate_id,
            }
        )
    )
    (run_dir / "frontier_val.json").write_text(
        json.dumps({"_pareto_ids": [candidate_id]})
    )
    (run_dir / "evolution_summary.jsonl").write_text(
        json.dumps({"candidate_id": candidate_id}) + "\n"
    )
    (run_dir / "events.jsonl").write_text("")
    return run_dir


def test_experiment_bundle_is_deterministic_and_verified(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "run-a", 0.8)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["search_task_ids"] = ["task-a"]
    manifest_path.write_text(json.dumps(manifest))
    runtime_file = tmp_path / "backend" / "app" / "meta_harness" / "contracts.py"
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_text("SCHEMA_VERSION = 1\n")
    manifest = json.loads(manifest_path.read_text())
    manifest["runtime_sha256"] = capture_runtime_sha256(tmp_path)
    manifest_path.write_text(json.dumps(manifest))
    task_dir = tmp_path / "eval" / "tasks" / "task-a"
    (task_dir / "workspace").mkdir(parents=True)
    (task_dir / "task.json").write_text(json.dumps({"id": "task-a"}))
    (task_dir / "workspace" / "example.py").write_text("value = 1\n")
    first = export_experiment_bundle(
        run_dir=run_dir,
        destination=tmp_path / "first.zip",
        repo_root=tmp_path,
    )
    second = export_experiment_bundle(
        run_dir=run_dir,
        destination=tmp_path / "second.zip",
        repo_root=tmp_path,
    )

    assert first["bundle_sha256"] == second["bundle_sha256"]
    manifest = verify_experiment_bundle(tmp_path / "first.zip")
    assert manifest["run_id"] == "run-a"
    assert manifest["include_runtime"] is True
    assert any(
        entry["path"] == "runtime/backend/app/meta_harness/contracts.py"
        for entry in manifest["files"]
    )
    assert any(entry["path"].endswith("candidate.json") for entry in manifest["files"])
    assert any(
        entry["path"] == "tasks/search/task-a/task.json"
        for entry in manifest["files"]
    )
    assert not any("__pycache__" in entry["path"] for entry in manifest["files"])

    runtime_file.write_text("SCHEMA_VERSION = 2\n")
    with pytest.raises(ValueError, match="runtime source drifted"):
        export_experiment_bundle(
            run_dir=run_dir,
            destination=tmp_path / "drifted.zip",
            repo_root=tmp_path,
        )


def test_compare_runs_reports_confidence_interval(tmp_path: Path) -> None:
    first = _run(tmp_path, "run-a", 0.6)
    second = _run(tmp_path, "run-b", 0.8)

    result = compare_runs([first, second])

    assert result["n_runs"] == 2
    assert result["mean_accuracy"] == pytest.approx(0.7)
    assert result["confidence_interval_95"][0] <= 0.7
    assert result["confidence_interval_95"][1] >= 0.7


def test_compare_runs_rejects_runtime_drift(tmp_path: Path) -> None:
    first = _run(tmp_path, "run-a", 0.6)
    second = _run(tmp_path, "run-b", 0.8)
    for run_dir, runtime_hash in ((first, "runtime-a"), (second, "runtime-b")):
        manifest_path = run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["runtime_sha256"] = runtime_hash
        manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="runtime"):
        compare_runs([first, second])


def test_compare_runs_rejects_synthetic_inputs(tmp_path: Path) -> None:
    synthetic = _run(tmp_path, "run-a", 0.8, synthetic=True)
    with pytest.raises(ValueError, match="synthetic"):
        compare_runs([synthetic])
