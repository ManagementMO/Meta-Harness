"""Versioned evidence-backed component refinements with rollback."""

from __future__ import annotations

import uuid
from pathlib import Path, PurePosixPath

from app.meta_harness.artifacts import (
    atomic_write_bytes,
    atomic_write_json,
    sha256_bytes,
    sha256_file,
    store_artifact,
    verify_artifact,
)
from app.meta_harness.contracts import RefinementRecord, RunMode, utc_now
from app.meta_harness.ledger import append_event


def _record_path(run_dir: Path, refinement_id: str) -> Path:
    if not refinement_id.startswith("ref_"):
        raise ValueError(f"invalid refinement id: {refinement_id}")
    return run_dir / "refinements" / refinement_id / "record.json"


def _safe_target(target: str) -> Path:
    path = PurePosixPath(target)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"invalid refinement target: {target!r}")
    return Path(*path.parts)


def _target_path(
    run_dir: Path,
    repo_root: Path,
    record: RefinementRecord,
) -> Path:
    relative = _safe_target(record.target)
    roots = {
        "attempt": run_dir / "attempt-components",
        "run": run_dir / "components",
        "project": repo_root / ".meta-harness" / "components",
        "global": repo_root / ".meta-harness" / "global-components",
    }
    root = roots[record.scope]
    target = (root / relative).resolve()
    target.relative_to(root.resolve())
    return target


def propose_refinement(
    *,
    run_dir: Path,
    run_id: str,
    kind: str,
    scope: str,
    target: str,
    proposed_content: bytes,
    parent_version: str | None,
    proposed_version: str,
    rationale: str,
    evidence: list[dict[str, str]],
    expected_outcome: str,
    existing_content: bytes | None = None,
) -> RefinementRecord:
    if not evidence:
        raise ValueError("refinements require evidence references")
    refinement_id = f"ref_{uuid.uuid4().hex}"
    after_artifact = store_artifact(
        run_dir,
        proposed_content,
        media_type="text/plain",
    )
    before_artifact = (
        store_artifact(run_dir, existing_content, media_type="text/plain")
        if existing_content is not None
        else None
    )
    record = RefinementRecord(
        refinement_id=refinement_id,
        kind=kind,
        scope=scope,
        target=target,
        parent_version=parent_version,
        proposed_version=proposed_version,
        rationale=rationale,
        evidence=evidence,
        expected_outcome=expected_outcome,
        before_hash=sha256_bytes(existing_content) if existing_content is not None else None,
        after_hash=after_artifact.sha256,
        before_artifact=before_artifact,
        after_artifact=after_artifact,
    )
    path = _record_path(run_dir, refinement_id)
    atomic_write_json(path, record)
    append_event(
        run_dir,
        event_type="RefinementProposed",
        run_id=run_id,
        entity_type="refinement",
        entity_id=refinement_id,
        payload={
            "kind": kind,
            "scope": scope,
            "target": target,
            "evidence": evidence,
        },
        artifact_refs=[after_artifact],
    )
    return record


def load_refinement(run_dir: Path, refinement_id: str) -> RefinementRecord:
    path = _record_path(run_dir, refinement_id)
    if not path.exists():
        raise FileNotFoundError(path)
    return RefinementRecord.model_validate_json(path.read_text())


def apply_refinement(
    *,
    run_dir: Path,
    repo_root: Path,
    run_id: str,
    refinement_id: str,
    mode: RunMode | str,
) -> RefinementRecord:
    record = load_refinement(run_dir, refinement_id)
    if record.status != "proposed":
        raise ValueError(f"refinement is not proposed: {record.status}")
    resolved_mode = RunMode(mode)
    if resolved_mode == RunMode.RESEARCH and record.scope in {"project", "global"}:
        raise ValueError("research mode cannot apply project or global refinements")
    target = _target_path(run_dir, repo_root, record)
    current_hash = sha256_file(target) if target.exists() else None
    if current_hash != record.before_hash:
        raise ValueError(
            f"refinement target changed: expected {record.before_hash}, got {current_hash}"
        )
    proposed_path = verify_artifact(run_dir, record.after_artifact)
    atomic_write_bytes(target, proposed_path.read_bytes())
    if sha256_file(target) != record.after_hash:
        raise ValueError("applied refinement hash mismatch")
    record.status = "applied"
    record.applied_path = str(target)
    record.applied_at = utc_now()
    atomic_write_json(_record_path(run_dir, refinement_id), record)
    append_event(
        run_dir,
        event_type="RefinementApplied",
        run_id=run_id,
        entity_type="refinement",
        entity_id=refinement_id,
        payload={
            "scope": record.scope,
            "target": record.target,
            "applied_path": record.applied_path,
            "before_hash": record.before_hash,
            "after_hash": record.after_hash,
        },
        artifact_refs=[record.after_artifact],
    )
    return record


def rollback_refinement(
    *,
    run_dir: Path,
    repo_root: Path,
    run_id: str,
    refinement_id: str,
) -> RefinementRecord:
    record = load_refinement(run_dir, refinement_id)
    if record.status != "applied":
        raise ValueError(f"refinement is not applied: {record.status}")
    target = _target_path(run_dir, repo_root, record)
    if not target.exists() or sha256_file(target) != record.after_hash:
        raise ValueError("applied target no longer matches refinement")
    if record.before_artifact is None:
        target.unlink()
    else:
        before_path = verify_artifact(run_dir, record.before_artifact)
        atomic_write_bytes(target, before_path.read_bytes())
        if sha256_file(target) != record.before_hash:
            raise ValueError("rolled-back refinement hash mismatch")
    record.status = "rolled_back"
    record.rolled_back_at = utc_now()
    atomic_write_json(_record_path(run_dir, refinement_id), record)
    refs = [record.after_artifact]
    if record.before_artifact is not None:
        refs.append(record.before_artifact)
    append_event(
        run_dir,
        event_type="RefinementRolledBack",
        run_id=run_id,
        entity_type="refinement",
        entity_id=refinement_id,
        payload={
            "scope": record.scope,
            "target": record.target,
            "before_hash": record.before_hash,
            "after_hash": record.after_hash,
        },
        artifact_refs=refs,
    )
    return record


def reject_refinement(
    *,
    run_dir: Path,
    run_id: str,
    refinement_id: str,
    reason: str,
) -> RefinementRecord:
    record = load_refinement(run_dir, refinement_id)
    if record.status != "proposed":
        raise ValueError(f"refinement is not proposed: {record.status}")
    record.status = "rejected"
    atomic_write_json(_record_path(run_dir, refinement_id), record)
    append_event(
        run_dir,
        event_type="RefinementRejected",
        run_id=run_id,
        entity_type="refinement",
        entity_id=refinement_id,
        payload={"reason": reason},
    )
    return record
