"""Evidence ledger, lifecycle, and refinement tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.meta_harness.ledger import (
    append_event,
    ledger_path,
    lifecycle_state,
    read_events,
    transition_lifecycle,
)
from app.meta_harness.refinements import (
    apply_refinement,
    propose_refinement,
    rollback_refinement,
)


def test_ledger_is_append_only_and_queryable(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    first = append_event(
        run_dir,
        event_type="CandidateMaterialized",
        run_id="run",
        entity_type="candidate",
        entity_id="cand_a",
        payload={"sha256": "abc"},
    )
    second = append_event(
        run_dir,
        event_type="CandidateBenchmarked",
        run_id="run",
        entity_type="candidate",
        entity_id="cand_a",
        payload={"accuracy": 1.0},
    )

    events = read_events(run_dir)
    assert [event.event_id for event in events] == [first.event_id, second.event_id]
    assert [event.event_type for event in events] == [
        "CandidateMaterialized",
        "CandidateBenchmarked",
    ]


def test_idempotent_event_is_appended_once(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    first = append_event(
        run_dir,
        event_type="TaskAttemptFinished",
        run_id="run",
        entity_type="attempt",
        entity_id="attempt-a",
        attempt_id="attempt-a",
        idempotency_key="attempt-a:finished",
        payload={"passed": True},
    )
    second = append_event(
        run_dir,
        event_type="TaskAttemptFinished",
        run_id="run",
        entity_type="attempt",
        entity_id="attempt-a",
        attempt_id="attempt-a",
        idempotency_key="attempt-a:finished",
        payload={"passed": True},
    )

    assert first == second
    assert len(read_events(run_dir)) == 1


def test_torn_ledger_tail_is_ignored_and_repaired(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    append_event(
        run_dir,
        event_type="RunCreated",
        run_id="run",
        entity_type="run",
        entity_id="run",
    )
    with ledger_path(run_dir).open("ab") as handle:
        handle.write(b'{"schema_version":1,"torn"')

    events = read_events(run_dir, repair_torn_tail=True)

    assert len(events) == 1
    assert ledger_path(run_dir).read_bytes().endswith(b"\n")
    assert b'"torn"' not in ledger_path(run_dir).read_bytes()


def test_lifecycle_transitions_fail_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    for state in ("created", "admitted", "running", "succeeded", "archived"):
        transition_lifecycle(
            run_dir,
            run_id="run",
            entity_type="run",
            entity_id="run",
            to_state=state,
        )
    assert lifecycle_state(run_dir, entity_type="run", entity_id="run") == "archived"
    with pytest.raises(ValueError, match="invalid"):
        transition_lifecycle(
            run_dir,
            run_id="run",
            entity_type="run",
            entity_id="run",
            to_state="running",
        )


def test_run_scoped_refinement_applies_and_rolls_back(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run"
    target = run_dir / "components" / "prompts" / "verify.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    record = propose_refinement(
        run_dir=run_dir,
        run_id="run",
        kind="prompt",
        scope="run",
        target="prompts/verify.txt",
        proposed_content=b"after",
        existing_content=b"before",
        parent_version="prompt.verify.v1",
        proposed_version="prompt.verify.v2",
        rationale="verification traces omit actionable context",
        evidence=[{"run_id": "run", "artifact": "trace/verify.json"}],
        expected_outcome="fewer blind retries",
    )

    applied = apply_refinement(
        run_dir=run_dir,
        repo_root=repo_root,
        run_id="run",
        refinement_id=record.refinement_id,
        mode="research",
    )
    assert applied.status == "applied"
    assert target.read_bytes() == b"after"

    rolled_back = rollback_refinement(
        run_dir=run_dir,
        repo_root=repo_root,
        run_id="run",
        refinement_id=record.refinement_id,
    )
    assert rolled_back.status == "rolled_back"
    assert target.read_bytes() == b"before"


def test_research_mode_rejects_global_refinement_application(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / "runs" / "run"
    record = propose_refinement(
        run_dir=run_dir,
        run_id="run",
        kind="memory",
        scope="global",
        target="memory/pattern.txt",
        proposed_content=b"pattern",
        existing_content=None,
        parent_version=None,
        proposed_version="memory.pattern.v1",
        rationale="repeated evidence",
        evidence=[{"run_id": "run", "artifact": "trace/result.json"}],
        expected_outcome="reuse the pattern",
    )

    with pytest.raises(ValueError, match="research mode"):
        apply_refinement(
            run_dir=run_dir,
            repo_root=repo_root,
            run_id="run",
            refinement_id=record.refinement_id,
            mode="research",
        )
