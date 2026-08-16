"""Deterministic experiment bundles and repeated-run summaries."""

from __future__ import annotations

import json
import math
import statistics
import zipfile
from pathlib import Path
from typing import Any

from app.meta_harness.artifacts import atomic_write_json, sha256_bytes, sha256_file
from app.meta_harness.provenance import capture_runtime_sha256, runtime_source_paths
from app.meta_harness.reports import build_run_report


def _portable_file(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return not any(
        part in {"__pycache__", ".pytest_cache"} for part in relative.parts
    ) and path.suffix not in {".pyc", ".pyo"}


def _bundle_files(run_dir: Path, *, include_raw: bool) -> list[Path]:
    exact = {
        "manifest.json",
        "frontier_val.json",
        "evolution_summary.jsonl",
        "events.jsonl",
        "finalization.json",
        "holdout-result.json",
    }
    files: list[Path] = []
    for path in sorted(
        item
        for item in run_dir.rglob("*")
        if item.is_file() and _portable_file(item, run_dir)
    ):
        relative = path.relative_to(run_dir)
        if relative.as_posix() in exact:
            files.append(path)
            continue
        if relative.name in {"candidate.json", "eval-result.json", "status.json"}:
            files.append(path)
            continue
        if "source" in relative.parts or "refinements" in relative.parts:
            files.append(path)
            continue
        if include_raw and (
            "traces" in relative.parts
            or "artifacts" in relative.parts
            or "proposer-sessions" in relative.parts
        ):
            files.append(path)
    return files


def export_experiment_bundle(
    *,
    run_dir: Path,
    destination: Path,
    include_raw: bool = False,
    repo_root: Path | None = None,
    include_tasks: bool = True,
    include_holdout_tasks: bool = False,
) -> dict[str, Any]:
    sources = [
        (path, path.relative_to(run_dir).as_posix())
        for path in _bundle_files(run_dir, include_raw=include_raw)
    ]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    runtime_included = False
    if repo_root is not None:
        expected_runtime = manifest.get("runtime_sha256")
        current_runtime = capture_runtime_sha256(repo_root)
        if expected_runtime and expected_runtime != current_runtime:
            raise ValueError(
                "runtime source drifted after the run; export from the recorded commit "
                "or rerun the experiment"
            )
        expected_lock = manifest.get("dependency_lock_sha256")
        lock_path = repo_root / "uv.lock"
        current_lock = sha256_file(lock_path) if lock_path.is_file() else None
        if expected_lock and expected_lock != current_lock:
            raise ValueError(
                "dependency lock drifted after the run; export from the recorded "
                "environment or rerun the experiment"
            )
        runtime_paths = [
            *runtime_source_paths(),
            "pyproject.toml",
            "backend/pyproject.toml",
            "sdk/pyproject.toml",
            "uv.lock",
        ]
        for relative in runtime_paths:
            path = repo_root / relative
            if path.is_file():
                sources.append((path, f"runtime/{relative}"))
                runtime_included = True
    if repo_root is not None and include_tasks:
        for task_id in manifest.get("search_task_ids", []):
            task_root = repo_root / "eval" / "tasks" / task_id
            if not task_root.is_dir():
                raise FileNotFoundError(task_root)
            for path in sorted(
                item
                for item in task_root.rglob("*")
                if item.is_file() and _portable_file(item, task_root)
            ):
                sources.append(
                    (
                        path,
                        f"tasks/search/{task_id}/{path.relative_to(task_root).as_posix()}",
                    )
                )
    if repo_root is not None and include_holdout_tasks:
        finalization_path = run_dir / "finalization.json"
        if not finalization_path.exists():
            raise ValueError("holdout tasks require a completed finalization artifact")
        finalization = json.loads(finalization_path.read_text())
        for task in finalization.get("holdout_tasks", []):
            task_id = task["task_id"]
            task_root = repo_root / "eval" / "holdout" / task_id
            if not task_root.is_dir():
                raise FileNotFoundError(task_root)
            for path in sorted(
                item
                for item in task_root.rglob("*")
                if item.is_file() and _portable_file(item, task_root)
            ):
                sources.append(
                    (
                        path,
                        f"tasks/holdout/{task_id}/{path.relative_to(task_root).as_posix()}",
                    )
                )
    sources = sorted(dict((relative, path) for path, relative in sources).items())
    entries = [
        {
            "path": relative,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for relative, path in sources
    ]
    bundle_manifest = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "include_raw": include_raw,
        "include_runtime": runtime_included,
        "include_tasks": include_tasks,
        "include_holdout_tasks": include_holdout_tasks,
        "files": entries,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, path in sources:
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
        manifest_bytes = json.dumps(
            bundle_manifest,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        info = zipfile.ZipInfo("bundle-manifest.json", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, manifest_bytes)
    result = {
        **bundle_manifest,
        "bundle_path": str(destination.resolve()),
        "bundle_sha256": sha256_file(destination),
        "size_bytes": destination.stat().st_size,
    }
    atomic_write_json(run_dir / "bundle.json", result)
    return result


def verify_experiment_bundle(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if "bundle-manifest.json" not in names:
            raise ValueError("bundle manifest is missing")
        manifest = json.loads(archive.read("bundle-manifest.json"))
        expected = {entry["path"]: entry for entry in manifest["files"]}
        if set(expected) | {"bundle-manifest.json"} != set(names):
            raise ValueError("bundle file set does not match manifest")
        for name, entry in expected.items():
            content = archive.read(name)
            if len(content) != entry["size_bytes"]:
                raise ValueError(f"bundle size mismatch: {name}")
            if sha256_bytes(content) != entry["sha256"]:
                raise ValueError(f"bundle hash mismatch: {name}")
    return manifest


def compare_runs(run_dirs: list[Path]) -> dict[str, Any]:
    if not run_dirs:
        raise ValueError("at least one run is required")
    reports = [build_run_report(run_dir) for run_dir in run_dirs]
    if any(report.get("synthetic") for report in reports):
        raise ValueError("synthetic runs cannot enter a research confidence report")
    policy_ids = {
        str((report.get("policy") or {}).get("policy_id"))
        for report in reports
        if (report.get("policy") or {}).get("policy_id")
    }
    git_commits = {
        str(report.get("git_commit"))
        for report in reports
        if report.get("git_commit")
    }
    runtime_hashes = {
        str(report.get("runtime_sha256"))
        for report in reports
        if report.get("runtime_sha256")
    }
    dependency_hashes = {
        str(report.get("dependency_lock_sha256"))
        for report in reports
        if report.get("dependency_lock_sha256")
    }
    if len(policy_ids) > 1:
        raise ValueError("runs use different evaluation policies")
    if len(git_commits) > 1:
        raise ValueError("runs use different git commits")
    if len(runtime_hashes) > 1:
        raise ValueError("runs use different evaluator runtime sources")
    if len(dependency_hashes) > 1:
        raise ValueError("runs use different dependency locks")
    accuracies: list[float] = []
    for report in reports:
        best_id = report.get("global_best_candidate_id") or report.get("best_candidate_id")
        result = (report.get("results") or {}).get(best_id, {})
        accuracy = result.get("accuracy_value")
        if accuracy is None:
            metric = result.get("accuracy") or {}
            accuracy = metric.get("value") if isinstance(metric, dict) else metric
        if accuracy is None:
            raise ValueError(f"run {report.get('run_id')} has no measured best accuracy")
        accuracies.append(float(accuracy))
    mean = statistics.fmean(accuracies)
    standard_deviation = statistics.stdev(accuracies) if len(accuracies) > 1 else 0.0
    margin = 1.96 * standard_deviation / math.sqrt(len(accuracies))
    return {
        "schema_version": 1,
        "run_ids": [report["run_id"] for report in reports],
        "n_runs": len(reports),
        "best_accuracies": accuracies,
        "mean_accuracy": mean,
        "sample_standard_deviation": standard_deviation,
        "confidence_interval_95": [max(0.0, mean - margin), min(1.0, mean + margin)],
        "git_commits": sorted(git_commits),
        "runtime_sha256": sorted(runtime_hashes),
        "dependency_lock_sha256": sorted(dependency_hashes),
        "policy_ids": sorted(policy_ids),
    }
