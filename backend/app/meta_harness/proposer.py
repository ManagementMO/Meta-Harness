"""Proposer node body — claude_wrapper.py-shaped.

Two paths:
- ``mock`` mode (BUILD_ORDER step 5): generates a deterministic stub
  candidate file for fast outer-loop testing, no LLM calls.
- ``claude`` mode (step 6): spawns the ``claude`` CLI subprocess with
  the SKILL.md ``--append-system-prompt``'d, parses stream-json, parses
  the resulting agents/<name>.py + pending_eval.json. Mirrors
  Stanford's reference ``claude_wrapper.py`` shape.

This module is the body of the outer state machine's ``propose`` node
(per Correction 1 — the proposer is graph-internal, not a separate
tier).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_MOCK_HARNESS_TEMPLATE = '''"""Mock candidate harness for outer-loop testing (iteration {iteration}).

Subclasses ``BaselineHarness`` with a hypothetical override that mock
benchmarking interprets as a pre-determined accuracy bump. Real
benchmark runs would actually exercise the override.
"""

from agents.baseline import BaselineHarness


class MockHarness_iter_{iteration}(BaselineHarness):
    """Mock candidate. Hypothesis: {hypothesis}"""

    HYPOTHESIS = {hypothesis_repr}
    EXPECTED_DELTA = {expected_delta}
'''


def mock_propose(
    *,
    run_dir: Path,
    iteration: int,
    parent_name: str | None,
    repo_root: Path,
) -> dict[str, Any]:
    """Generate a mock candidate. Writes the harness file under
    ``agents/_mock_iter_{N}.py`` and ``pending_eval.json`` under the run
    directory. Returns the pending_eval payload."""
    name = f"_mock_iter_{iteration}"
    hypothesis = f"mock hypothesis #{iteration}: pretend we tweaked something"
    expected_delta = 0.05

    harness_src = _MOCK_HARNESS_TEMPLATE.format(
        iteration=iteration,
        hypothesis=hypothesis,
        hypothesis_repr=repr(hypothesis),
        expected_delta=expected_delta,
    )

    # Write to repo-root agents/ so the existing sys.path setup in
    # cli.py picks it up. The .gitignore should exclude agents/_mock_*.py.
    agents_dir = repo_root / "agents"
    agents_dir.mkdir(exist_ok=True)
    harness_path = agents_dir / f"{name}.py"
    harness_path.write_text(harness_src)

    payload: dict[str, Any] = {
        "iteration": iteration,
        "candidates": [
            {
                "name": name,
                "import_path": f"agents.{name}:MockHarness_iter_{iteration}",
                "parent": parent_name,
                "hypothesis": hypothesis,
                "axis": "exploitation",
                "expected_score_delta": expected_delta,
            }
        ],
    }
    (run_dir / "pending_eval.json").write_text(json.dumps(payload, indent=2))

    # Mirror Stanford's proposer-sessions/iter-N/ for shape compatibility.
    sess_dir = run_dir / "proposer-sessions" / f"iter-{iteration}"
    sess_dir.mkdir(parents=True, exist_ok=True)
    (sess_dir / "session.json").write_text(
        json.dumps(
            {
                "mode": "mock",
                "iteration": iteration,
                "exit_code": 0,
                "duration_seconds": 0.0,
                "cost_usd": 0.0,
                "files_written": {f"agents/{name}.py": {"lines_written": harness_src.count("\\n")}},
            },
            indent=2,
        )
    )
    return payload


# ──────────────────────────────────────────────────────────────────────
# Real proposer (claude CLI subprocess) — lands at BUILD_ORDER step 6.
# ──────────────────────────────────────────────────────────────────────


def claude_propose(
    *,
    run_dir: Path,
    iteration: int,
    parent_name: str | None,
    repo_root: Path,
    skill_path: Path,
    proposer_prior: str = "",
    timeout_seconds: int = 2400,
) -> dict[str, Any]:
    """Spawn ``claude`` subprocess with SKILL.md system prompt; parse
    stream-json; return parsed pending_eval. **Stub for step 5.**

    Lands at step 6.
    """
    raise NotImplementedError(
        "claude_propose lands at BUILD_ORDER step 6. Use --proposer mock for step 5."
    )
