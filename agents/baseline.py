"""The baseline coding-agent harness — the starting point for evolution.

No overrides. Uses ``CodingAgentHarness`` defaults verbatim. Tested by
the inner-loop pipeline; never modified by the proposer (proposer only
writes run-scoped proposals that are copied into immutable candidate bundles).
"""

from app.meta_harness.harness import CodingAgentHarness


class BaselineHarness(CodingAgentHarness):
    """Baseline. No overrides."""

    pass
