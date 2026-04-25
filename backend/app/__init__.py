"""Meta-Harness backend application namespace.

Submodules:
- ``app.meta_harness`` — outer + inner state machines, proposer, tools,
  sandbox, persistence, branches, runs (the orchestration core).
- ``app.api`` — FastAPI REST + SSE routers.
- ``app.streaming`` — in-process SSE channel registry.
- ``app.cli`` — the ``meta-harness`` CLI entrypoint (typer).

Note: ``app.meta_harness`` is namespaced under this package and is NOT
the same module as the SDK package ``meta_harness`` (sdk/meta_harness/).
"""

__version__ = "0.1.0"
