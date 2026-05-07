"""FastAPI REST behavior tests (BUILD_ORDER step 10)."""

from __future__ import annotations

import shutil
import sys
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.runs import clear_run_state
from app.main import create_app
from app.meta_harness.branches import clear_branch_state
from app.streaming import channel_for_run, event_registry


REPO_ROOT = Path(__file__).resolve().parents[2]


TEST_TMP_ROOT = REPO_ROOT / "backend" / ".api-test-tmp"


def _make_test_repo() -> Path:
    for module_name in list(sys.modules):
        if module_name == "agents" or module_name.startswith("agents."):
            sys.modules.pop(module_name, None)
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    repo_root = TEST_TMP_ROOT / f"repo-{uuid.uuid4().hex[:8]}"
    agents_dir = repo_root / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "__init__.py").write_text("")
    (agents_dir / "baseline.py").write_text(
        "from app.meta_harness.harness import CodingAgentHarness\n\n"
        "class BaselineHarness(CodingAgentHarness):\n"
        "    pass\n"
    )
    return repo_root


def _cleanup_repo(repo_root: Path) -> None:
    if repo_root.exists():
        shutil.rmtree(repo_root)


def _cleanup(repo_root: Path, run_name: str) -> None:
    run_dir = repo_root / "runs" / run_name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    for path in (repo_root / "agents").glob("_mock_iter_*.py"):
        path.unlink()


def _wait_for_status(client: TestClient, run_name: str, status: str) -> dict:
    deadline = time.monotonic() + 5
    last = {}
    while time.monotonic() < deadline:
        response = client.get(f"/runs/{run_name}")
        response.raise_for_status()
        last = response.json()
        if last["status"] == status:
            return last
        time.sleep(0.05)
    raise AssertionError(f"run did not reach {status}; last={last}")


def test_run_ids_reject_path_traversal():
    clear_run_state()
    clear_branch_state()
    event_registry.clear()
    repo_root = _make_test_repo()
    outside = repo_root / "outside"
    outside.mkdir()
    (outside / "sentinel.txt").write_text("keep")

    app = create_app(
        repo_root=repo_root,
        eval_tasks_dir=REPO_ROOT / "eval" / "tasks",
        use_persistence=False,
    )
    try:
        with TestClient(app) as client:
            for run_name in ("..", "../outside", "nested/child", "%2E%2E", ""):
                response = client.post(
                    "/runs",
                    json={
                        "budget": 1,
                        "fresh": True,
                        "run_name": run_name,
                        "proposer": "mock",
                        "mock_bench": True,
                        "trials": 1,
                        "workers": 1,
                    },
                )
                assert response.status_code == 422

            for path in ("/runs/..", "/runs/%2E%2E", "/runs/nested%2Fchild"):
                response = client.get(path)
                assert response.status_code in {404, 405}

        assert (outside / "sentinel.txt").read_text() == "keep"
    finally:
        clear_run_state()
        clear_branch_state()
        event_registry.clear()
        _cleanup_repo(repo_root)


def test_dev_dashboard_origin_can_read_api():
    clear_run_state()
    clear_branch_state()
    event_registry.clear()
    repo_root = _make_test_repo()

    app = create_app(
        repo_root=repo_root,
        eval_tasks_dir=REPO_ROOT / "eval" / "tasks",
        use_persistence=False,
    )
    try:
        with TestClient(app) as client:
            response = client.get(
                "/health",
                headers={"Origin": "http://localhost:3000"},
            )
            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    finally:
        clear_run_state()
        clear_branch_state()
        event_registry.clear()
        _cleanup_repo(repo_root)


def test_run_checkpoint_fork_branch_memory_api_flow():
    clear_run_state()
    clear_branch_state()
    event_registry.clear()
    run_name = f"api-test-{uuid.uuid4().hex[:8]}"
    repo_root = _make_test_repo()
    _cleanup(repo_root, run_name)

    app = create_app(
        repo_root=repo_root,
        eval_tasks_dir=REPO_ROOT / "eval" / "tasks",
        use_persistence=False,
    )
    try:
        with TestClient(app) as client:
            health = client.get("/health")
            assert health.status_code == 200
            assert health.json()["persistence"] == "memory"

            created = client.post(
                "/runs",
                json={
                    "domain": "coding-agent",
                    "budget": 1,
                    "model": "mock",
                    "fresh": True,
                    "run_name": run_name,
                    "proposer": "mock",
                    "mock_bench": True,
                    "trials": 1,
                    "workers": 1,
                },
            )
            assert created.status_code == 201
            assert created.headers["Location"] == f"/runs/{run_name}"
            body = created.json()
            assert body["run_id"] == run_name
            assert body["thread_id"] == run_name
            assert body["status"] == "running"

            info = _wait_for_status(client, run_name, "completed")
            assert info["current_iteration"] == 1
            assert info["frontier_val"]["iteration"] == 1

            diff = client.get(f"/runs/{run_name}/candidates/_mock_iter_1/diff")
            assert diff.status_code == 200
            assert "agents/_mock_iter_1.py" in diff.json()["diff"]

            test_output = client.get(
                f"/runs/{run_name}/candidates/_mock_iter_1/test-output"
            )
            assert test_output.status_code == 200
            assert "accuracy:" in test_output.json()["output"]

            listed = client.get("/runs")
            assert listed.status_code == 200
            assert any(item["run_id"] == run_name for item in listed.json()["runs"])

            checkpoints = client.get(f"/runs/{run_name}/checkpoints")
            assert checkpoints.status_code == 200
            checkpoint_rows = checkpoints.json()["checkpoints"]
            assert checkpoint_rows
            checkpoint_id = next(
                row["checkpoint_id"]
                for row in reversed(checkpoint_rows)
                if row["iteration"] == 0
            )

            detail = client.get(f"/runs/{run_name}/checkpoints/{checkpoint_id}")
            assert detail.status_code == 200
            assert detail.json()["checkpoint_id"] == checkpoint_id
            assert "state" in detail.json()

            forked = client.post(
                f"/runs/{run_name}/fork",
                json={
                    "parent_checkpoint_id": checkpoint_id,
                    "mods": {"proposer_prior": "api test prior"},
                },
            )
            assert forked.status_code == 202
            fork_thread_id = forked.json()["thread_id"]
            assert fork_thread_id.startswith(f"{run_name}.fork.")

            branches = client.get(f"/runs/{run_name}/branches")
            assert branches.status_code == 200
            assert any(
                branch["thread_id"] == fork_thread_id
                for branch in branches.json()["branches"]
            )

            trajectory = client.get(f"/runs/{run_name}/trajectory")
            assert trajectory.status_code == 200
            assert trajectory.json()["trajectory"]["run_id"] == run_name

            cancel = client.post(f"/runs/{run_name}/branches/{fork_thread_id}/cancel")
            assert cancel.status_code == 200
            assert cancel.json()["status"] in {"cancelled", "completed"}

            memory = client.get("/memory/coding-agent")
            assert memory.status_code == 200
            assert memory.json()["entries"] == []

            search = client.post(
                "/memory/coding-agent/search",
                json={"query": "schema drift retry", "limit": 5},
            )
            assert search.status_code == 200
            assert search.json()["results"] == []

            event_types = {
                event.event_type
                for event in event_registry.history(channel_for_run(run_name))
            }
            assert {
                "state-update",
                "checkpoint-written",
                "candidate-created",
                "validate-result",
                "eval-result",
                "frontier-updated",
                "iteration-complete",
                "fork-created",
                "branch-cancelled",
            }.issubset(event_types)
    finally:
        clear_run_state()
        clear_branch_state()
        event_registry.clear()
        # Remove stale sys.path entries and cached modules so
        # later test_outer.py imports resolve cleanly.
        stale = str(repo_root)
        sys.path[:] = [p for p in sys.path if p != stale]
        for module_name in list(sys.modules):
            if module_name == "agents" or module_name.startswith("agents."):
                sys.modules.pop(module_name, None)
        _cleanup_repo(repo_root)
