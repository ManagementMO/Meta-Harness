"""The baseline coding-agent harness — the starting point for evolution.

No overrides. Uses ``CodingAgentHarness`` defaults verbatim. Tested by
the inner-loop pipeline; never modified by the proposer (proposer only
writes new files under ``runs/{run_id}/agents/``).
"""

from app.meta_harness.harness import CodingAgentHarness


class BaselineHarness(CodingAgentHarness):
    """Baseline. No overrides."""

    pass
