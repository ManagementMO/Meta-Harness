"""Instrument existing graph-like objects with lightweight trace events."""

from __future__ import annotations

import uuid
from typing import Any

from meta_harness.trace import TraceSink, _emit
from meta_harness.types import TraceEvent


class InstrumentedGraph:
    """Thin proxy that traces ``invoke`` and ``ainvoke`` calls."""

    def __init__(
        self,
        graph: Any,
        *,
        run_id: str | None = None,
        sink: TraceSink | None = None,
    ) -> None:
        self.graph = graph
        self.run_id = run_id or uuid.uuid4().hex
        self.sink = sink
        self.trace_events: list[TraceEvent] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.graph, name)

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        """Trace and delegate a synchronous graph invocation."""
        _emit(self.trace_events, self.sink, self.run_id, "graph-invoke-start")
        try:
            result = self.graph.invoke(*args, **kwargs)
        except Exception as exc:
            _emit(
                self.trace_events,
                self.sink,
                self.run_id,
                "graph-invoke-error",
                {"error": str(exc)},
            )
            raise
        _emit(self.trace_events, self.sink, self.run_id, "graph-invoke-end")
        return result

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        """Trace and delegate an asynchronous graph invocation."""
        _emit(self.trace_events, self.sink, self.run_id, "graph-ainvoke-start")
        try:
            result = await self.graph.ainvoke(*args, **kwargs)
        except Exception as exc:
            _emit(
                self.trace_events,
                self.sink,
                self.run_id,
                "graph-ainvoke-error",
                {"error": str(exc)},
            )
            raise
        _emit(self.trace_events, self.sink, self.run_id, "graph-ainvoke-end")
        return result


def wrap_graph(
    graph: Any,
    *,
    run_id: str | None = None,
    sink: TraceSink | None = None,
) -> InstrumentedGraph:
    """Return a traced proxy around a graph-like object."""
    return InstrumentedGraph(graph, run_id=run_id, sink=sink)
