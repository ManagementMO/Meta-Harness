"""Append-only evidence and lifecycle ledger with torn-tail recovery."""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from app.meta_harness.artifacts import (
    _fsync_directory,
    atomic_write_bytes,
    canonical_json_bytes,
)
from app.meta_harness.contracts import ArtifactRef, LedgerEvent

MAX_EVENT_BYTES = 256 * 1024
MAX_EVENTS = 1_000_000
_LOCK = threading.Lock()
_TERMINAL_STATES = {
    "succeeded",
    "failed",
    "canceled",
    "expired",
    "reconciled",
    "archived",
    "abandoned",
}
_ALLOWED_TRANSITIONS = {
    None: {"created"},
    "created": {"admitted", "canceled", "failed"},
    "admitted": {"running", "canceled", "failed"},
    "running": {"waiting", "succeeded", "failed", "canceled", "expired", "abandoned"},
    "waiting": {"running", "canceled", "expired", "abandoned"},
    "abandoned": {"reconciled", "running", "failed", "canceled"},
    "succeeded": {"archived"},
    "failed": {"reconciled", "archived"},
    "canceled": {"archived"},
    "expired": {"reconciled", "archived"},
    "reconciled": {"archived"},
    "archived": set(),
}


def ledger_path(run_dir: Path) -> Path:
    return run_dir / "events.jsonl"


def _find_event(path: Path, event_id: str) -> LedgerEvent | None:
    if not path.exists():
        return None
    with path.open("rb") as handle:
        for line in handle:
            if event_id.encode() not in line:
                continue
            event = LedgerEvent.model_validate_json(line)
            if event.event_id == event_id:
                return event
    return None


def append_event(
    run_dir: Path,
    *,
    event_type: str,
    run_id: str,
    entity_type: str,
    entity_id: str,
    thread_id: str | None = None,
    attempt_id: str | None = None,
    idempotency_key: str | None = None,
    payload: dict[str, Any] | None = None,
    artifact_refs: list[ArtifactRef] | None = None,
) -> LedgerEvent:
    event_id = (
        "evt_" + uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"meta-harness:{run_id}:{idempotency_key}",
        ).hex
        if idempotency_key
        else f"evt_{uuid.uuid4().hex}"
    )
    event = LedgerEvent(
        event_id=event_id,
        event_type=event_type,
        run_id=run_id,
        entity_type=entity_type,
        entity_id=entity_id,
        thread_id=thread_id,
        attempt_id=attempt_id,
        idempotency_key=idempotency_key,
        payload=payload or {},
        artifact_refs=artifact_refs or [],
    )
    encoded = canonical_json_bytes(event.model_dump(mode="json")) + b"\n"
    if len(encoded) > MAX_EVENT_BYTES:
        raise ValueError(f"ledger event exceeds {MAX_EVENT_BYTES} bytes")
    path = ledger_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o644)
        try:
            try:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except ImportError:
                pass
            if idempotency_key:
                existing = _find_event(path, event.event_id)
                if existing is not None:
                    return existing
            written = os.write(descriptor, encoded)
            if written != len(encoded):
                raise OSError("short ledger write")
            os.fsync(descriptor)
        finally:
            try:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except ImportError:
                pass
            os.close(descriptor)
        _fsync_directory(path.parent)
    return event


def read_events(
    run_dir: Path,
    *,
    repair_torn_tail: bool = False,
) -> list[LedgerEvent]:
    path = ledger_path(run_dir)
    if not path.exists():
        return []
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    events: list[LedgerEvent] = []
    valid_bytes = bytearray()
    for index, line in enumerate(lines):
        if not line.strip():
            valid_bytes.extend(line)
            continue
        try:
            event = LedgerEvent.model_validate_json(line)
        except Exception:
            if index != len(lines) - 1:
                raise ValueError(f"corrupt ledger record at line {index + 1}")
            if repair_torn_tail:
                atomic_write_bytes(path, bytes(valid_bytes))
            break
        events.append(event)
        valid_bytes.extend(line if line.endswith(b"\n") else line + b"\n")
        if len(events) > MAX_EVENTS:
            raise ValueError(f"ledger exceeds {MAX_EVENTS} records")
    return events


def events_for(
    run_dir: Path,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    event_type: str | None = None,
) -> list[LedgerEvent]:
    return [
        event
        for event in read_events(run_dir)
        if (entity_type is None or event.entity_type == entity_type)
        and (entity_id is None or event.entity_id == entity_id)
        and (event_type is None or event.event_type == event_type)
    ]


def lifecycle_state(
    run_dir: Path,
    *,
    entity_type: str,
    entity_id: str,
) -> str | None:
    state: str | None = None
    for event in events_for(
        run_dir,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type="LifecycleTransition",
    ):
        state = str(event.payload["to"])
    return state


def transition_lifecycle(
    run_dir: Path,
    *,
    run_id: str,
    entity_type: str,
    entity_id: str,
    to_state: str,
    thread_id: str | None = None,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> LedgerEvent:
    current = lifecycle_state(
        run_dir,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    allowed = _ALLOWED_TRANSITIONS.get(current, set())
    if to_state not in allowed:
        raise ValueError(
            f"invalid {entity_type} lifecycle transition {current!r} -> {to_state!r}"
        )
    return append_event(
        run_dir,
        event_type="LifecycleTransition",
        run_id=run_id,
        entity_type=entity_type,
        entity_id=entity_id,
        thread_id=thread_id,
        payload={
            "from": current,
            "to": to_state,
            "reason": reason,
            "details": details or {},
        },
    )


def reconcile_lifecycle(
    run_dir: Path,
    *,
    run_id: str,
    entity_type: str,
    entity_id: str,
    observed_terminal_state: str | None = None,
    thread_id: str | None = None,
) -> str:
    current = lifecycle_state(
        run_dir,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    if current in _TERMINAL_STATES:
        return str(current)
    target = observed_terminal_state or "abandoned"
    transition_lifecycle(
        run_dir,
        run_id=run_id,
        entity_type=entity_type,
        entity_id=entity_id,
        to_state=target,
        thread_id=thread_id,
        reason="reconciled from durable evidence",
    )
    return target
