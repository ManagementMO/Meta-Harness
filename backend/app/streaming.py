"""In-process SSE event registry.

The event type allowlist is intentionally closed and mirrors
``docs/INTERFACES.md`` section 7.2. API routers and graph nodes emit into
per-run channels named ``run:{run_id}``; the dashboard consumes those
channels through ``GET /runs/{run_id}/stream``.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator


REGISTERED_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "state-update",
        "checkpoint-written",
        "candidate-created",
        "validate-result",
        "eval-result",
        "frontier-updated",
        "iteration-complete",
        "fork-created",
        "branch-cancelled",
        "memory-pattern-stored",
        "error",
    }
)


class StreamingRegistryError(RuntimeError):
    """Base error for runtime-enforced SSE contract violations."""

    status_code = 500


class UnknownEventTypeError(StreamingRegistryError):
    """Raised when code attempts to emit an event outside the allowlist."""


class InvalidEventPayloadError(StreamingRegistryError):
    """Raised when an allowed event does not satisfy the shared payload shape."""


@dataclass(frozen=True)
class SSEEvent:
    """One event stored in the in-process backlog and written to SSE."""

    event_type: str
    event_id: str
    data: dict[str, Any]
    ts: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def channel_for_run(run_id: str) -> str:
    """Return the multiplexed SSE channel name for a run."""

    return f"run:{run_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_sse(event: SSEEvent) -> str:
    """Serialize one event according to the HTML SSE wire format."""

    payload = json.dumps(event.data, default=str, separators=(",", ":"))
    return f"event: {event.event_type}\nid: {event.event_id}\ndata: {payload}\n\n"


class EventRegistry:
    """Closed-set registry with per-channel subscribers and replay history."""

    def __init__(
        self,
        allowed_event_types: set[str] | frozenset[str] | None = None,
        *,
        history_limit: int = 1000,
    ) -> None:
        self.allowed_event_types = frozenset(
            allowed_event_types or REGISTERED_EVENT_TYPES
        )
        self.history_limit = history_limit
        self._history: dict[str, list[SSEEvent]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[SSEEvent]]] = {}

    def emit(
        self,
        channel: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_id: str | None = None,
    ) -> SSEEvent:
        """Emit one event.

        Unknown event types raise a 500-class error by design; this is the
        runtime enforcement for the frontend/backend SSE contract.
        """

        if event_type not in self.allowed_event_types:
            raise UnknownEventTypeError(
                f"unregistered SSE event type: {event_type!r}"
            )
        if not isinstance(payload, dict):
            raise InvalidEventPayloadError("SSE payload must be a JSON object")
        if "thread_id" not in payload:
            raise InvalidEventPayloadError(
                f"SSE event {event_type!r} missing required thread_id"
            )

        event = SSEEvent(
            event_type=event_type,
            event_id=event_id or uuid.uuid4().hex,
            data=payload,
            ts=_now(),
        )
        history = self._history.setdefault(channel, [])
        history.append(event)
        if len(history) > self.history_limit:
            del history[: len(history) - self.history_limit]

        for queue in list(self._subscribers.get(channel, set())):
            queue.put_nowait(event)
        return event

    def history(self, channel: str) -> list[SSEEvent]:
        """Return a copy of a channel's replay backlog."""

        return list(self._history.get(channel, []))

    def clear(self) -> None:
        """Clear subscribers and history. Intended for tests."""

        self._history.clear()
        self._subscribers.clear()

    async def subscribe(
        self,
        channel: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[str]:
        """Yield formatted SSE chunks for one channel.

        Existing backlog is replayed first. If ``last_event_id`` is present
        and found, replay starts after that event.
        """

        replay = self.history(channel)
        if last_event_id:
            for idx, event in enumerate(replay):
                if event.event_id == last_event_id:
                    replay = replay[idx + 1 :]
                    break
        for event in replay:
            yield format_sse(event)

        queue: asyncio.Queue[SSEEvent] = asyncio.Queue()
        self._subscribers.setdefault(channel, set()).add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=heartbeat_interval,
                    )
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield format_sse(event)
        finally:
            subscribers = self._subscribers.get(channel)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(channel, None)


event_registry = EventRegistry()


def emit_run_event(
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    event_id: str | None = None,
) -> SSEEvent:
    """Emit one event to the multiplexed channel for ``run_id``."""

    return event_registry.emit(
        channel_for_run(run_id),
        event_type,
        payload,
        event_id=event_id,
    )
