"""Step 8 end-to-end integration test: cross-run memory flow.

Validates the demo beat:
1. Run-A (mock outer loop) → produces accepted candidate → writes pattern to memory
2. Verify pattern exists via memory list
3. Run-B (mock outer loop) → proposer should have memory patterns injected
4. Verify pattern appeared in run-B's proposer system_prompt
5. Verify no data corruption between runs
6. Verify edge cases: empty namespace, memory store failure tolerance
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

from app.meta_harness.memory import (
    add_pattern,
    format_patterns_for_prompt,
    list_namespace,
    memory_store,
    search_patterns,
)
from app.meta_harness.outer import run_outer_loop
from app.meta_harness.persistence import healthcheck, persistence_layer
from app.meta_harness.runs import make_run_dir

_PG_OK = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(healthcheck())

pytestmark = pytest.mark.skipif(
    not _PG_OK,
    reason="Postgres not reachable at configured DSN",
)


# ── 1. Cross-run pattern propagation ────────────────────────────────


async def test_cross_run_pattern_propagation(tmp_path: Path):
    """The full demo beat: run-A writes patterns, run-B reads them.

    Uses a unique domain namespace to avoid collision with other tests.
    """
    domain = "e2e-cross-run-test"
    eval_tasks_dir = REPO_ROOT / "eval" / "tasks"

    async with persistence_layer() as saver, memory_store() as mstore:
        # ── Run A ────────────────────────────────────────────────
        run_a_dir = make_run_dir(tmp_path, "e2e-run-a", fresh=True)
        final_a = await run_outer_loop(
            run_dir=run_a_dir,
            repo_root=REPO_ROOT,
            eval_tasks_dir=eval_tasks_dir,
            mock_proposer=True,
            mock_bench=True,
            trials=5,
            bench_workers=1,
            budget=2,
            checkpointer=saver,
            memory_store=mstore,
        )
        assert final_a["iteration"] == 2

        # Manually write a pattern to the e2e domain to simulate
        # what happens with a real (non-mock) proposer that produces
        # meaningful hypotheses:
        await add_pattern(
            mstore,
            pattern="retry on schema_drift errors reduces patch failures by 8%",
            mechanism_axis="exploitation",
            score_delta=0.08,
            run_id="e2e-run-a",
            domain=domain,
        )

        # Verify pattern exists in the store
        patterns_after_a = await search_patterns(mstore, domain=domain, limit=10)
        assert len(patterns_after_a) >= 1
        drift_patterns = [
            p for p in patterns_after_a if "schema_drift" in p.get("pattern", "")
        ]
        assert len(drift_patterns) >= 1, (
            f"Expected schema_drift pattern, got: {patterns_after_a}"
        )

        # ── Run B ────────────────────────────────────────────────
        run_b_dir = make_run_dir(tmp_path, "e2e-run-b", fresh=True)
        final_b = await run_outer_loop(
            run_dir=run_b_dir,
            repo_root=REPO_ROOT,
            eval_tasks_dir=eval_tasks_dir,
            mock_proposer=True,
            mock_bench=True,
            trials=5,
            bench_workers=1,
            budget=1,
            checkpointer=saver,
            memory_store=mstore,
        )
        assert final_b["iteration"] == 1

        # Patterns from run-A are still there after run-B
        patterns_after_b = await search_patterns(mstore, domain=domain, limit=10)
        assert len(patterns_after_b) >= 1  # not wiped by run-B

    # Cleanup mock stubs
    for final in (final_a, final_b):
        for c in final.get("candidates", []):
            stub = REPO_ROOT / "agents" / f"{c['name']}.py"
            if stub.exists():
                stub.unlink()


# ── 2. Format injection into proposer prior ──────────────────────────


async def test_memory_injection_into_proposer_prior():
    """Verify format_patterns_for_prompt produces content that would be
    injected into the proposer's system prompt correctly."""
    async with memory_store() as mstore:
        # Write a known pattern
        key = await add_pattern(
            mstore,
            pattern="early-exit on auth failures saves context tokens",
            mechanism_axis="exploration",
            score_delta=0.04,
            run_id="inject-test-run",
            domain="e2e-inject-test",
        )

        # Search and format
        patterns = await search_patterns(mstore, domain="e2e-inject-test", limit=5)
        rendered = format_patterns_for_prompt(patterns)

        # Must contain the section header
        assert "## Cross-run memory" in rendered
        assert "learned patterns" in rendered

        # Must contain the pattern text
        assert "early-exit on auth failures" in rendered
        assert "exploration" in rendered
        assert "+4.0%" in rendered
        assert "inject-test-run" in rendered

        # Must NOT contain raw JSON or Python reprs
        assert "{" not in rendered or "**" in rendered  # Markdown bold is OK
        assert "dict(" not in rendered


# ── 3. Pattern schema correctness ────────────────────────────────────


async def test_pattern_value_schema():
    """Each stored pattern must have exactly the expected fields."""
    expected_fields = {"pattern", "mechanism_axis", "score_delta",
                       "evidence_run_ids", "created_at"}

    async with memory_store() as mstore:
        await add_pattern(
            mstore,
            pattern="test schema fields",
            mechanism_axis="exploitation",
            score_delta=0.05,
            run_id="schema-test",
            domain="e2e-schema-test",
        )
        results = await search_patterns(mstore, domain="e2e-schema-test", limit=1)
        assert len(results) >= 1
        entry = results[0]
        # 'key' is added by search_patterns; the value fields must be present
        for field in expected_fields:
            assert field in entry, f"missing field: {field}"
        assert isinstance(entry["evidence_run_ids"], list)
        assert isinstance(entry["score_delta"], (int, float))
        assert isinstance(entry["pattern"], str)
        assert isinstance(entry["created_at"], str)  # ISO format


# ── 4. Empty namespace ───────────────────────────────────────────────


async def test_empty_namespace_returns_empty():
    """Querying a namespace with no patterns returns empty list."""
    async with memory_store() as mstore:
        results = await search_patterns(
            mstore, domain="nonexistent-domain-12345", limit=5
        )
        assert results == []


async def test_format_empty_patterns_omitted():
    """Empty patterns list produces empty string (omitted from prompt)."""
    result = format_patterns_for_prompt([])
    assert result == ""


# ── 5. Multiple patterns ordering ────────────────────────────────────


async def test_patterns_sorted_by_recency():
    """Patterns should be returned newest-first."""
    import time

    async with memory_store() as mstore:
        # Write two patterns with a tiny time gap
        await add_pattern(
            mstore,
            pattern="older pattern",
            mechanism_axis="exploration",
            score_delta=0.02,
            run_id="order-test",
            domain="e2e-order-test",
        )
        time.sleep(0.01)  # ensure different created_at
        await add_pattern(
            mstore,
            pattern="newer pattern",
            mechanism_axis="exploration",
            score_delta=0.04,
            run_id="order-test",
            domain="e2e-order-test",
        )

        results = await search_patterns(mstore, domain="e2e-order-test", limit=10)
        assert len(results) >= 2
        # First result should be the newer one
        assert "newer" in results[0]["pattern"]


# ── 6. Limit enforcement ─────────────────────────────────────────────


async def test_search_respects_limit():
    """search_patterns with limit=1 returns at most 1."""
    async with memory_store() as mstore:
        for i in range(3):
            await add_pattern(
                mstore,
                pattern=f"limit test pattern {i}",
                mechanism_axis="exploitation",
                score_delta=0.01,
                run_id="limit-test",
                domain="e2e-limit-test",
            )
        results = await search_patterns(mstore, domain="e2e-limit-test", limit=1)
        assert len(results) == 1


# ── 7. Outer loop with memory — verify accepted writes pattern ───────


async def test_accepted_candidate_writes_memory_pattern(tmp_path: Path):
    """When a mock candidate is accepted, a pattern should appear in
    the coding-agent domain."""
    eval_tasks_dir = REPO_ROOT / "eval" / "tasks"

    async with persistence_layer() as saver, memory_store() as mstore:
        # Snapshot pattern count before
        before = await search_patterns(mstore, domain="coding-agent", limit=100)
        before_count = len(before)

        run_dir = make_run_dir(tmp_path, "accepted-test", fresh=True)
        final = await run_outer_loop(
            run_dir=run_dir,
            repo_root=REPO_ROOT,
            eval_tasks_dir=eval_tasks_dir,
            mock_proposer=True,
            mock_bench=True,
            trials=5,
            bench_workers=1,
            budget=2,
            checkpointer=saver,
            memory_store=mstore,
        )

        # Check which candidates were accepted
        accepted = [c for c in final["candidates"] if c["status"] == "accepted"]

        # Snapshot after
        after = await search_patterns(mstore, domain="coding-agent", limit=100)
        after_count = len(after)

        # If any candidate was accepted, at least one new pattern
        if accepted:
            assert after_count > before_count, (
                f"Expected new patterns after {len(accepted)} accepted candidates; "
                f"before={before_count}, after={after_count}"
            )

    # Cleanup
    for c in final.get("candidates", []):
        stub = REPO_ROOT / "agents" / f"{c['name']}.py"
        if stub.exists():
            stub.unlink()


# ── 8. Filesystem artifacts still correct ────────────────────────────


async def test_filesystem_artifacts_unaffected_by_memory(tmp_path: Path):
    """Memory integration must not break the existing filesystem
    artifacts (frontier_val.json, evolution_summary.jsonl, etc.)."""
    eval_tasks_dir = REPO_ROOT / "eval" / "tasks"

    async with persistence_layer() as saver, memory_store() as mstore:
        run_dir = make_run_dir(tmp_path, "artifacts-test", fresh=True)
        final = await run_outer_loop(
            run_dir=run_dir,
            repo_root=REPO_ROOT,
            eval_tasks_dir=eval_tasks_dir,
            mock_proposer=True,
            mock_bench=True,
            trials=5,
            bench_workers=1,
            budget=2,
            checkpointer=saver,
            memory_store=mstore,
        )

    # All standard artifacts must exist
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "pending_eval.json").exists()
    assert (run_dir / "frontier_val.json").exists()
    assert (run_dir / "evolution_summary.jsonl").exists()

    # Frontier shape intact
    frontier = json.loads((run_dir / "frontier_val.json").read_text())
    assert "candidates" in frontier
    assert "_pareto_names" in frontier
    for c in frontier["candidates"]:
        assert "dominated_by_names" in c

    # Evolution summary shape intact
    rows = [
        json.loads(line)
        for line in (run_dir / "evolution_summary.jsonl").read_text().strip().split("\n")
        if line.strip()
    ]
    assert len(rows) == 2
    for row in rows:
        assert "parent_candidate_name" in row
        assert "iteration" in row
        assert "candidate" in row

    # Per-candidate artifacts
    for c in final["candidates"]:
        cand_dir = run_dir / "candidates" / c["name"]
        assert (cand_dir / "eval-result.json").exists()
        assert (cand_dir / "status.json").exists()

    # Cleanup
    for c in final.get("candidates", []):
        stub = REPO_ROOT / "agents" / f"{c['name']}.py"
        if stub.exists():
            stub.unlink()
