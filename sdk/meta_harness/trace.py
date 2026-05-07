"""Generic run tracing decorator for public SDK users."""

from __future__ import annotations

import functools
import inspect
import uuid
from collections.abc import Callable
from typing import Any, TypeVar, overload

from meta_harness.types import TraceEvent

F = TypeVar("F", bound=Callable[..., Any])
TraceSink = Callable[[TraceEvent], None]


def _emit(
    events: list[TraceEvent],
    sink: TraceSink | None,
    run_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    event = TraceEvent(
        run_id=run_id,
        event_type=event_type,
        payload=payload or {},
        sequence=len(events),
    )
    events.append(event)
    if sink is not None:
        sink(event)


@overload
def trace_run(fn: F) -> F: ...


@overload
def trace_run(
    fn: None = None,
    *,
    run_id: str | None = None,
    sink: TraceSink | None = None,
) -> Callable[[F], F]: ...


def trace_run(
    fn: F | None = None,
    *,
    run_id: str | None = None,
    sink: TraceSink | None = None,
) -> F | Callable[[F], F]:
    """Trace start/end/error events around a sync or async callable.

    The wrapper stores emitted events on ``_meta_harness_trace`` so users
    can inspect them without running the backend service.
    """

    def decorate(func: F) -> F:
        events: list[TraceEvent] = []

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                rid = run_id or uuid.uuid4().hex
                _emit(events, sink, rid, "run-start", {"function": func.__name__})
                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    _emit(
                        events,
                        sink,
                        rid,
                        "run-error",
                        {"function": func.__name__, "error": str(exc)},
                    )
                    raise
                _emit(events, sink, rid, "run-end", {"function": func.__name__})
                return result

            async_wrapper._meta_harness_trace = events  # type: ignore[attr-defined]
            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            rid = run_id or uuid.uuid4().hex
            _emit(events, sink, rid, "run-start", {"function": func.__name__})
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                _emit(
                    events,
                    sink,
                    rid,
                    "run-error",
                    {"function": func.__name__, "error": str(exc)},
                )
                raise
            _emit(events, sink, rid, "run-end", {"function": func.__name__})
            return result

        wrapper._meta_harness_trace = events  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    if fn is not None:
        return decorate(fn)
    return decorate
