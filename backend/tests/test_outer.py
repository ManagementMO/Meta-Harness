"""Outer-loop end-to-end test in mock mode (BUILD_ORDER step 5 DoD).

Verifies that ``meta-harness loop --proposer mock --mock-bench
--budget 2 --fresh`` produces:
- pending_eval.json (current iteration)
- frontier_val.json with dominated_by_names per candidate
- evolution_summary.jsonl with parent_candidate_name per row
- per-candidate eval-result.json + status.json

LLM-free; runs in <2s.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.meta_harness.outer import run_outer_loop  # noqa: E402
from app.meta_harness.reports import build_run_report  # noqa: E402
from app.meta_harness.runs import candidate_dir, make_run_dir, make_run_path  # noqa: E402


def test_run_and_candidate_names_reject_path_traversal(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.txt").write_text("keep")

    for name in ("..", "../outside", "nested/child", "%2E%2E", ""):
        try:
            make_run_dir(tmp_path, name, fresh=True)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid run name: {name}")

    assert (outside / "sentinel.txt").read_text() == "keep"
    assert make_run_path(tmp_path, "safe-run_1").name == "safe-run_1"

    run_dir = make_run_dir(tmp_path, "safe-run", fresh=True)
    for name in ("..", "../escape", "nested/child", "%2E%2E", ""):
        try:
            candidate_dir(run_dir, name)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid candidate name: {name}")

    assert candidate_dir(run_dir, "_mock_iter_1").name == "_mock_iter_1"


async def test_mock_outer_loop_produces_all_files(tmp_path: Path):
    run_dir = make_run_dir(tmp_path, "test-outer", fresh=True)
    eval_tasks_dir = REPO_ROOT / "eval" / "tasks"

    final = await run_outer_loop(
        run_dir=run_dir,
        repo_root=REPO_ROOT,
        eval_tasks_dir=eval_tasks_dir,
        mock_proposer=True,
        mock_bench=True,
        trials=5,
        bench_workers=1,
        budget=2,
    )

    # Loop completed both iterations.
    assert final["iteration"] == 2
    assert final["budget_remaining"] == 0
    assert len(final["candidates"]) == 3
    assert final["candidates"][0]["name"] == "baseline"
    assert final["best_candidate_id"].startswith("cand_")

    # Required filesystem artifacts.
    assert (run_dir / "pending_eval.json").exists()
    assert (run_dir / "frontier_val.json").exists()
    assert (run_dir / "evolution_summary.jsonl").exists()
    assert (run_dir / "manifest.json").exists()

    # Frontier shape: dominated_by_names per candidate (INTERFACES.md §2.2).
    frontier = json.loads((run_dir / "frontier_val.json").read_text())
    assert frontier["iteration"] == 2
    assert "candidates" in frontier
    assert "_pareto_names" in frontier
    assert "_best" in frontier
    for c in frontier["candidates"]:
        assert "dominated_by_names" in c
        assert isinstance(c["dominated_by_names"], list)

    # Evolution summary: parent_candidate_name per row.
    rows = [
        json.loads(line)
        for line in (run_dir / "evolution_summary.jsonl").read_text().strip().split("\n")
        if line.strip()
    ]
    assert len(rows) == 3
    assert rows[0]["candidate"] == "baseline"
    assert rows[0]["parent_candidate_name"] is None
    assert rows[1]["parent_candidate_name"] == "baseline"
    assert "parent_candidate_name" in rows[2]
    for row in rows:
        assert "iteration" in row
        assert "candidate" in row
        assert "scores" in row
        assert "delta" in row

    # Per-candidate artifacts.
    for candidate in final["candidates"]:
        candidate_dir = run_dir / "candidates" / candidate["candidate_id"]
        assert (candidate_dir / "candidate.json").exists()
        assert (candidate_dir / "eval-result.json").exists()
        assert (candidate_dir / "status.json").exists()
        assert (candidate_dir / "source" / "harness.py").exists()

    report = build_run_report(run_dir)
    assert report["archive_size"] == 3
    assert report["frontier_size"] == len(report["frontier_ids"])
    assert set(report["results"]) == {
        candidate["candidate_id"] for candidate in final["candidates"]
    }
    assert report["search_efficiency"]["measurement_status"] == "synthetic"
    assert report["artifact_retention"]["keep_raw_traces"] is True


async def test_research_outer_loop_rejects_non_scoped_proposal(
    monkeypatch,
    tmp_path: Path,
):
    from app.meta_harness import proposer as proposer_module

    run_dir = make_run_dir(tmp_path, "test-proposal-policy", fresh=True)

    def propose_outside_scope(*, run_dir, iteration, parent_name, repo_root):
        source = run_dir / "outside.py"
        source.write_text(
            "from app.meta_harness.harness import CodingAgentHarness\n\n"
            "class OutsideHarness(CodingAgentHarness):\n"
            "    pass\n"
        )
        payload = {
            "iteration": iteration,
            "candidates": [
                {
                    "name": "outside",
                    "source_path": str(source),
                    "class_name": "OutsideHarness",
                    "parent": parent_name,
                    "hypothesis": "outside scope",
                    "axis": "exploration",
                }
            ],
        }
        (run_dir / "pending_eval.json").write_text(json.dumps(payload))
        return payload

    monkeypatch.setattr(proposer_module, "mock_propose", propose_outside_scope)

    try:
        await run_outer_loop(
            run_dir=run_dir,
            repo_root=REPO_ROOT,
            eval_tasks_dir=REPO_ROOT / "eval" / "tasks",
            mock_proposer=True,
            mock_bench=True,
            trials=1,
            bench_workers=1,
            budget=1,
        )
    except ValueError as exc:
        assert "run-scoped" in str(exc) or "inside" in str(exc)
    else:
        raise AssertionError("research run accepted a non-scoped proposal")


async def test_outer_loop_evaluates_every_proposed_candidate(
    monkeypatch,
    tmp_path: Path,
):
    from app.meta_harness import proposer as proposer_module

    run_dir = make_run_dir(tmp_path, "test-population", fresh=True)

    def propose_population(*, run_dir, iteration, parent_name, repo_root):
        proposals = []
        for suffix in ("a", "b"):
            name = f"population_{suffix}"
            class_name = f"Population{suffix.upper()}"
            source = run_dir / "proposals" / f"iter-{iteration}" / f"{name}.py"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                "from app.meta_harness.harness import CodingAgentHarness\n\n"
                f"class {class_name}(CodingAgentHarness):\n"
                "    pass\n"
            )
            proposals.append(
                {
                    "name": name,
                    "source_path": str(source),
                    "class_name": class_name,
                    "parent": parent_name,
                    "hypothesis": f"population hypothesis {suffix}",
                    "axis": "exploration",
                    "expected_score_delta": 0.1,
                }
            )
        payload = {"iteration": iteration, "candidates": proposals}
        (run_dir / "pending_eval.json").write_text(json.dumps(payload))
        return payload

    monkeypatch.setattr(proposer_module, "mock_propose", propose_population)

    final = await run_outer_loop(
        run_dir=run_dir,
        repo_root=REPO_ROOT,
        eval_tasks_dir=REPO_ROOT / "eval" / "tasks",
        mock_proposer=True,
        mock_bench=True,
        trials=2,
        bench_workers=2,
        budget=1,
    )

    assert len(final["candidates"]) == 3
    baseline_id = final["candidates"][0]["candidate_id"]
    proposed = final["candidates"][1:]
    assert {candidate["name"] for candidate in proposed} == {
        "population_a",
        "population_b",
    }
    assert all(candidate["parent_ids"] == [baseline_id] for candidate in proposed)
    assert all(candidate["scores"] is not None for candidate in proposed)
    assert all(
        (run_dir / "candidates" / candidate["candidate_id"] / "eval-result.json").exists()
        for candidate in proposed
    )
