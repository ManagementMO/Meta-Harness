"""Shared public SDK types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TraceEvent:
    """One lightweight event emitted by SDK instrumentation."""

    run_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=utc_now)
    sequence: int = 0


@dataclass(frozen=True)
class RunInfo:
    """Public summary for an instrumented run."""

    run_id: str
    started_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
