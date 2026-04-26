"""SSE event registry tests (BUILD_ORDER step 10)."""

from __future__ import annotations

import asyncio

import pytest

from app.streaming import (
    EventRegistry,
    REGISTERED_EVENT_TYPES,
    UnknownEventTypeError,
    channel_for_run,
)


def async_test(fn):
    """Run an async test body without relying on pytest-asyncio."""

    def _run():
        return asyncio.run(fn())

    return _run


def test_registered_event_types_are_closed_contract():
    assert REGISTERED_EVENT_TYPES == {
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


def test_unknown_event_type_raises_500_class_error():
    registry = EventRegistry()

    with pytest.raises(UnknownEventTypeError) as excinfo:
        registry.emit(
            channel_for_run("run-a"),
            "not-registered",
            {"thread_id": "run-a"},
        )

    assert excinfo.value.status_code == 500


@async_test
async def test_subscribe_replays_channel_history_as_sse():
    registry = EventRegistry()
    event = registry.emit(
        channel_for_run("run-a"),
        "state-update",
        {
            "thread_id": "run-a",
            "node": "propose",
            "iteration": 1,
            "ts": "2026-04-25T00:00:00Z",
            "summary": {},
        },
    )

    stream = registry.subscribe(channel_for_run("run-a"), heartbeat_interval=0.01)
    chunk = await anext(stream)
    await stream.aclose()

    assert "event: state-update" in chunk
    assert f"id: {event.event_id}" in chunk
    assert '"thread_id":"run-a"' in chunk
