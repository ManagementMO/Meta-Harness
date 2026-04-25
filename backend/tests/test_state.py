"""Tests for state schemas (LLM-free)."""

from __future__ import annotations

from pathlib import Path

from app.meta_harness.state import Candidate, CodingAgentState, MetaHarnessState


def test_candidate_dataclass_minimal_construction(tmp_path: Path):
    c = Candidate(
        name="baseline",
        import_path="agents.baseline:BaselineHarness",
        parent=None,
        hypothesis="starting point",
        axis="exploration",
        expected_score_delta=None,
        iteration=0,
        traces_dir=tmp_path / "candidates" / "baseline" / "traces",
    )
    assert c.status == "pending"
    assert c.scores is None
    assert c.delta is None
    assert c.cost_usd is None
    assert isinstance(c.traces_dir, Path)


def test_meta_harness_state_typed_dict_keys():
    state: MetaHarnessState = {
        "run_id": "r-1",
        "iteration": 0,
        "budget_remaining": 5,
        "candidates": [],
        "frontier": [],
        "best_candidate": None,
        "proposer_prior": "",
    }
    assert set(state.keys()) == {
        "run_id",
        "iteration",
        "budget_remaining",
        "candidates",
        "frontier",
        "best_candidate",
        "proposer_prior",
    }


def test_coding_agent_state_typed_dict_keys():
    state: CodingAgentState = {
        "task": {},
        "workspace_path": "/tmp/x",
        "orient_summary": None,
        "plan": None,
        "messages": [],
        "turn_count": 0,
        "verify_attempts": 0,
        "verify_result": None,
        "final_files": None,
        "score": None,
    }
    assert state["turn_count"] == 0
    assert state["score"] is None
