"""Public SDK smoke tests."""

from __future__ import annotations

import asyncio

from meta_harness import TraceEvent, trace_run, wrap_graph


def test_trace_run_decorator_records_sync_events() -> None:
    seen: list[TraceEvent] = []

    @trace_run(run_id="sdk-test", sink=seen.append)
    def add_one(value: int) -> int:
        return value + 1

    assert add_one(1) == 2
    assert [event.event_type for event in seen] == ["run-start", "run-end"]
    assert add_one._meta_harness_trace == seen  # type: ignore[attr-defined]


def test_trace_run_decorator_records_async_events() -> None:
    seen: list[TraceEvent] = []

    @trace_run(run_id="sdk-async-test", sink=seen.append)
    async def add_two(value: int) -> int:
        return value + 2

    assert asyncio.run(add_two(1)) == 3
    assert [event.event_type for event in seen] == ["run-start", "run-end"]
    assert all(event.run_id == "sdk-async-test" for event in seen)


def test_trace_run_decorator_records_errors() -> None:
    seen: list[TraceEvent] = []

    @trace_run(run_id="sdk-error-test", sink=seen.append)
    def fail() -> None:
        raise RuntimeError("boom")

    try:
        fail()
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")

    assert [event.event_type for event in seen] == ["run-start", "run-error"]
    assert seen[-1].payload["error"] == "boom"


def test_wrap_graph_delegates_sync_invoke() -> None:
    class Graph:
        def invoke(self, value: int) -> int:
            return value + 2

    wrapped = wrap_graph(Graph(), run_id="graph-test")

    assert wrapped.invoke(3) == 5
    assert [event.event_type for event in wrapped.trace_events] == [
        "graph-invoke-start",
        "graph-invoke-end",
    ]


def test_wrap_graph_delegates_async_ainvoke() -> None:
    class Graph:
        async def ainvoke(self, value: int) -> int:
            return value + 3

    wrapped = wrap_graph(Graph(), run_id="graph-test")

    assert asyncio.run(wrapped.ainvoke(4)) == 7
    assert [event.event_type for event in wrapped.trace_events] == [
        "graph-ainvoke-start",
        "graph-ainvoke-end",
    ]
