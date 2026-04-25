"""Run filesystem lifecycle: ``runs/{run_id}/`` layout + helpers.

Layout (per Appendix C §C.10 + INTERFACES.md §2):
    runs/{run_id}/
    ├── manifest.json                 # run config
    ├── pending_eval.json             # proposer→benchmark handoff (current iter)
    ├── frontier_val.json             # current Pareto frontier
    ├── evolution_summary.jsonl       # append-only candidate log
    ├── agents/                       # proposer-written candidate files
    ├── candidates/{name}/
    │   ├── eval-result.json
    │   ├── status.json
    │   └── traces/{task-id}-trial-{N}/...
    └── proposer-sessions/iter-{N}/
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def make_run_dir(repo_root: Path, run_name: str, *, fresh: bool = False) -> Path:
    """Create or return the run directory. Wipes if ``fresh=True``."""
    run_dir = repo_root / "runs" / run_name
    if fresh and run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "agents").mkdir(exist_ok=True)
    (run_dir / "candidates").mkdir(exist_ok=True)
    (run_dir / "proposer-sessions").mkdir(exist_ok=True)
    return run_dir


def write_manifest(run_dir: Path, **fields: Any) -> None:
    """Write run manifest with run config + start time."""
    manifest = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


def append_evolution_summary(run_dir: Path, row: dict[str, Any]) -> None:
    """Append one candidate row to evolution_summary.jsonl."""
    path = run_dir / "evolution_summary.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def write_pending_eval(run_dir: Path, payload: dict[str, Any]) -> None:
    """Write ``pending_eval.json`` (proposer → benchmark handoff)."""
    (run_dir / "pending_eval.json").write_text(json.dumps(payload, indent=2))


def read_pending_eval(run_dir: Path) -> dict[str, Any] | None:
    """Read ``pending_eval.json`` if present, else None."""
    path = run_dir / "pending_eval.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def write_frontier(run_dir: Path, frontier: dict[str, Any]) -> None:
    """Write ``frontier_val.json``."""
    (run_dir / "frontier_val.json").write_text(json.dumps(frontier, indent=2))


def read_frontier(run_dir: Path) -> dict[str, Any] | None:
    """Read ``frontier_val.json`` if present."""
    path = run_dir / "frontier_val.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def candidate_dir(run_dir: Path, candidate_name: str) -> Path:
    """Return the candidate's directory; create if missing."""
    d = run_dir / "candidates" / candidate_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_status(run_dir: Path, candidate_name: str, status: dict[str, Any]) -> None:
    """Write a candidate's ``status.json``."""
    (candidate_dir(run_dir, candidate_name) / "status.json").write_text(
        json.dumps(status, indent=2)
    )
