"""Holdout finalization and reproducible reporting tests."""

from __future__ import annotations

import json
from pathlib import Path

from app.meta_harness.artifacts import atomic_write_json
from app.meta_harness.candidates import materialize_candidate
from app.meta_harness.contracts import EvaluationPolicy, Provenance, RunManifest, RunMode
from app.meta_harness.reports import build_run_report, finalize_run


def _source(repo_root: Path) -> Path:
    source = repo_root / "proposals" / "candidate.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from types import SimpleNamespace\n"
        "from app.meta_harness.harness import CodingAgentHarness\n\n"
        "class CandidateHarness(CodingAgentHarness):\n"
        "    def __init__(self):\n"
        "        pass\n"
        "    async def _call_llm(self, messages, tools, *, tool_choice=None):\n"
        "        usage = SimpleNamespace(input_tokens=1, output_tokens=1, "
        "cache_read_input_tokens=0, cache_creation_input_tokens=0)\n"
        "        if tools[0]['name'] == 'submit_plan':\n"
        "            block = SimpleNamespace(type='tool_use', name='submit_plan', "
        "id='plan', input={'summary': 'finish', 'steps': []})\n"
        "        else:\n"
        "            block = SimpleNamespace(type='tool_use', name='task_complete', "
        "id='done', input={})\n"
        "        return SimpleNamespace(content=[block], usage=usage)\n"
    )
    return source


def _holdout(repo_root: Path) -> Path:
    root = repo_root / "eval" / "holdout"
    task = root / "task-holdout"
    (task / "workspace").mkdir(parents=True)
    (task / "task.json").write_text(
        json.dumps(
            {
                "id": "task-holdout",
                "tier": "smoke",
                "instruction": "finish",
                "test_command": "true",
                "expected_files_changed": [],
                "runtime_adapter": "generic-command-v1",
            }
        )
    )
    return root


async def test_finalization_is_separate_and_includes_baseline(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    source = _source(repo_root)
    policy = EvaluationPolicy(
        policy_id="search-v1",
        mode=RunMode.RESEARCH,
        inner_model="fixed-model",
        runtime_adapter="generic-command-v1",
        trials=1,
        workers=1,
        synthetic=True,
    )
    provenance = Provenance(
        git_commit="abc",
        git_dirty=False,
        authorization_profile="trusted-local-research",
    )
    baseline = materialize_candidate(
        run_dir=run_dir,
        repo_root=repo_root,
        metadata={
            "name": "baseline",
            "source_path": str(source.relative_to(repo_root)),
            "class_name": "CandidateHarness",
        },
        parent_ids=[],
        policy=policy,
        provenance=provenance,
    )
    candidate = materialize_candidate(
        run_dir=run_dir,
        repo_root=repo_root,
        metadata={
            "name": "candidate-a",
            "source_path": str(source.relative_to(repo_root)),
            "class_name": "CandidateHarness",
        },
        parent_ids=[baseline.candidate_id],
        policy=policy,
        provenance=provenance,
    )
    branch_source = repo_root / "proposals" / "branch.py"
    branch_source.write_text(source.read_text().replace("CandidateHarness", "BranchHarness"))
    branch_dir = run_dir / "branches" / "branch-a"
    branch_dir.mkdir(parents=True)
    branch_candidate = materialize_candidate(
        run_dir=branch_dir,
        repo_root=repo_root,
        metadata={
            "name": "branch-candidate",
            "source_path": str(branch_source.relative_to(repo_root)),
            "class_name": "BranchHarness",
        },
        parent_ids=[baseline.candidate_id],
        policy=policy,
        provenance=provenance,
    )
    atomic_write_json(
        branch_dir / "frontier_val.json",
        {
            "_pareto_ids": [branch_candidate.candidate_id],
            "_best": {
                "candidate_id": branch_candidate.candidate_id,
                "name": branch_candidate.name,
            },
        },
    )
    manifest = RunManifest(
        run_id=run_dir.name,
        mode=RunMode.RESEARCH,
        status="completed",
        policy=policy,
        search_task_ids=["task-search"],
        persistence_backend="memory",
        synthetic=True,
        best_candidate="candidate-a",
        best_candidate_id=candidate.candidate_id,
        budget=1,
    )
    atomic_write_json(run_dir / "manifest.json", manifest)
    atomic_write_json(
        run_dir / "frontier_val.json",
        {
            "_pareto_ids": [candidate.candidate_id],
            "_best": {
                "candidate_id": candidate.candidate_id,
                "name": candidate.name,
            },
        },
    )

    report_before_finalization = build_run_report(run_dir)
    assert branch_candidate.candidate_id in report_before_finalization["frontier_ids"]
    assert report_before_finalization["candidate_locations"][branch_candidate.candidate_id] == "branches/branch-a"

    report = await finalize_run(
        run_dir=run_dir,
        repo_root=repo_root,
        holdout_tasks_dir=_holdout(repo_root),
        trials=1,
        workers=1,
        allow_synthetic_search=True,
    )

    assert report["feedback_to_search"] is False
    assert report["baseline_candidate_id"] == baseline.candidate_id
    assert set(report["candidate_ids"]) == {
        baseline.candidate_id,
        candidate.candidate_id,
        branch_candidate.candidate_id,
    }
    assert report["holdout_policy"]["task_visibility"] == "holdout"
    assert report["holdout_policy"]["allow_global_memory"] is False
    assert (run_dir / "finalization.json").exists()
    assert (
        run_dir / "candidates" / branch_candidate.candidate_id / "candidate.json"
    ).exists()
    assert (
        run_dir
        / "candidates"
        / candidate.candidate_id
        / "holdout"
        / "eval-result.json"
    ).exists()
    assert not (
        run_dir / "candidates" / candidate.candidate_id / "eval-result.json"
    ).exists()
