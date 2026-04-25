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
from app.meta_harness.runs import make_run_dir  # noqa: E402


def test_mock_outer_loop_produces_all_files(tmp_path: Path):
    run_dir = make_run_dir(tmp_path, "test-outer", fresh=True)
    eval_tasks_dir = REPO_ROOT / "eval" / "tasks"

    final = run_outer_loop(
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
    assert len(final["candidates"]) == 2

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
    assert len(rows) == 2
    assert rows[0]["parent_candidate_name"] is None  # first iter, no parent
    assert "parent_candidate_name" in rows[1]
    for row in rows:
        assert "iteration" in row
        assert "candidate" in row
        assert "scores" in row
        assert "delta" in row

    # Per-candidate artifacts.
    for c in final["candidates"]:
        cand_dir = run_dir / "candidates" / c["name"]
        assert (cand_dir / "eval-result.json").exists()
        assert (cand_dir / "status.json").exists()

    # Cleanup the mock harness files written to repo-root agents/.
    for c in final["candidates"]:
        stub = REPO_ROOT / "agents" / f"{c['name']}.py"
        if stub.exists():
            stub.unlink()
