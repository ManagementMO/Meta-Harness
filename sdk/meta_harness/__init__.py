"""Meta-Harness — public Python library.

This package exposes the user-facing primitives: ``wrap_graph()`` for
instrumenting an existing LangGraph state graph, ``@trace_run`` for
generic agent loops, and shared dataclasses (``TraceEvent``, ``RunInfo``).
The actual orchestration code lives in the backend's ``app.meta_harness``
namespace; the SDK is intentionally thin to avoid SDK↔backend cycles.
"""

__version__ = "0.1.0"
