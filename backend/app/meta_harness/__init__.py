"""Meta-Harness backend internal namespace (``app.meta_harness``).

This is the orchestration core: outer + inner state machines, proposer,
6 fixed inner-loop tools, sandbox, persistence, branches, runs.

NOT the same package as the SDK's ``meta_harness`` (sdk/meta_harness/).
Imports from here are ``from app.meta_harness.<module> import ...``.
"""
