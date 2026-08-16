"""Tests for state schemas (LLM-free)."""

from __future__ import annotations

from app.meta_harness.contracts import CandidateRecord, CandidateStatus
from app.meta_harness.state import CodingAgentState, MetaHarnessState


def test_candidate_record_serializes_at_checkpoint_boundary():
    candidate = CandidateRecord(
        candidate_id="cand_0123456789abcdef",
        name="baseline",
        artifact_path="candidates/cand_0123456789abcdef/candidate.json",
        status=CandidateStatus.PENDING,
        iteration=0,
    )
    serialized = candidate.model_dump(mode="json")
    assert serialized["candidate_id"] == "cand_0123456789abcdef"
    assert serialized["status"] == "pending"
    assert serialized["scores"] is None


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
