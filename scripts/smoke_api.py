"""Smoke-test the Step 10 FastAPI/SSE backend.

Run with a server already listening, for example:

    cd backend
    uv run uvicorn app.main:app --port 8000 --reload

Then from the repo root:

    uv run python scripts/smoke_api.py
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.streaming import (
    EventRegistry,
    REGISTERED_EVENT_TYPES,
    UnknownEventTypeError,
    channel_for_run,
)


BASE_URL = os.environ.get("META_HARNESS_API_URL", "http://localhost:8000")


def request_json(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    expected_status: int = 200,
) -> tuple[dict[str, Any], dict[str, str]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
            headers = dict(response.headers.items())
            status = response.status
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise AssertionError(
            f"{method} {path} returned {exc.code}, expected {expected_status}: {detail}"
        ) from exc
    assert status == expected_status, f"{method} {path}: {status} != {expected_status}"
    return payload, headers


def wait_for_run(run_id: str, status: str, *, timeout_s: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last, _headers = request_json("GET", f"/runs/{run_id}")
        if last["status"] == status:
            return last
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not reach {status}; last={last}")


def collect_sse_events(
    run_id: str,
    expected: set[str],
    *,
    timeout_s: float = 10.0,
) -> set[str]:
    request = urllib.request.Request(BASE_URL + f"/runs/{run_id}/stream")
    seen: set[str] = set()
    current_event: str | None = None
    deadline = time.monotonic() + timeout_s
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            while time.monotonic() < deadline and not expected.issubset(seen):
                raw = response.readline()
                if not raw:
                    break
                line = raw.decode("utf-8").strip()
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                elif not line and current_event:
                    seen.add(current_event)
                    current_event = None
    except socket.timeout:
        pass
    return seen


def payload_for(event_type: str) -> dict[str, Any]:
    base: dict[str, Any] = {"thread_id": "registry-smoke"}
    if event_type == "state-update":
        return {**base, "node": "propose", "iteration": 1, "ts": "now", "summary": {}}
    if event_type == "checkpoint-written":
        return {
            **base,
            "checkpoint_id": "ckpt",
            "parent_checkpoint_id": None,
            "ts": "now",
            "node": "propose",
        }
    if event_type == "candidate-created":
        return {
            **base,
            "candidate": "candidate",
            "import_path": "agents.candidate:CodingAgentHarness",
            "parent": None,
        }
    if event_type == "validate-result":
        return {**base, "candidate": "candidate", "valid": True}
    if event_type == "eval-result":
        return {
            **base,
            "candidate": "candidate",
            "accuracy": 1.0,
            "per_task": {},
            "tokens": {},
            "cost_usd": 0.0,
        }
    if event_type == "frontier-updated":
        return {
            **base,
            "iteration": 1,
            "frontier": ["candidate"],
            "best_candidate": "candidate",
            "delta": 1.0,
        }
    if event_type == "iteration-complete":
        return {**base, "iteration": 1, "status": "improved"}
    if event_type == "fork-created":
        return {
            **base,
            "parent_thread_id": "registry-smoke",
            "parent_checkpoint_id": "ckpt",
            "mods_summary": {"keys": [], "count": 0},
        }
    if event_type == "branch-cancelled":
        return {**base, "reason": "requested"}
    if event_type == "memory-pattern-stored":
        return {
            **base,
            "namespace": ["learned_patterns", "coding-agent"],
            "key": "pattern",
            "score_delta": 0.0,
        }
    if event_type == "error":
        return {**base, "node": "propose", "message": "boom", "traceback": ""}
    raise AssertionError(f"unhandled event type: {event_type}")


def assert_registry_contract() -> None:
    registry = EventRegistry()
    channel = channel_for_run("registry-smoke")
    for event_type in REGISTERED_EVENT_TYPES:
        registry.emit(channel, event_type, payload_for(event_type))
    emitted = {event.event_type for event in registry.history(channel)}
    assert emitted == REGISTERED_EVENT_TYPES
    try:
        registry.emit(channel, "unregistered-event", {"thread_id": "registry-smoke"})
    except UnknownEventTypeError as exc:
        assert exc.status_code >= 500
    else:
        raise AssertionError("unregistered SSE event type did not raise")


def main() -> None:
    health, _headers = request_json("GET", "/health")
    assert health["status"] == "ok"

    run_id = "smoke-api-" + uuid.uuid4().hex[:8]
    created, headers = request_json(
        "POST",
        "/runs",
        {
            "domain": "coding-agent",
            "budget": 2,
            "model": "mock",
            "fresh": True,
            "run_name": run_id,
            "proposer": "mock",
            "mock_bench": True,
            "trials": 1,
            "workers": 1,
        },
        expected_status=201,
    )
    location = headers.get("Location") or headers.get("location")
    assert location == f"/runs/{run_id}"
    assert created["run_id"] == run_id

    info = wait_for_run(run_id, "completed")
    assert info["current_iteration"] == 2

    checkpoints, _headers = request_json("GET", f"/runs/{run_id}/checkpoints")
    checkpoint_rows = checkpoints["checkpoints"]
    assert checkpoint_rows, "expected at least one checkpoint"
    checkpoint_id = next(
        row["checkpoint_id"]
        for row in reversed(checkpoint_rows)
        if row["iteration"] == 0
    )

    detail, _headers = request_json(
        "GET",
        f"/runs/{run_id}/checkpoints/{checkpoint_id}",
    )
    assert detail["checkpoint_id"] == checkpoint_id

    forked, _headers = request_json(
        "POST",
        f"/runs/{run_id}/fork",
        {
            "parent_checkpoint_id": checkpoint_id,
            "mods": {"proposer_prior": "smoke prior"},
        },
        expected_status=202,
    )
    thread_id = forked["thread_id"]
    request_json("POST", f"/runs/{run_id}/branches/{thread_id}/cancel")

    branches, _headers = request_json("GET", f"/runs/{run_id}/branches")
    assert any(branch["thread_id"] == thread_id for branch in branches["branches"])

    trajectory, _headers = request_json("GET", f"/runs/{run_id}/trajectory")
    assert trajectory["trajectory"]["run_id"] == run_id

    memory, _headers = request_json("GET", "/memory/coding-agent")
    assert memory["entries"] == []
    search, _headers = request_json(
        "POST",
        "/memory/coding-agent/search",
        {"query": "schema drift retry", "limit": 5},
    )
    assert search["results"] == []

    expected_stream_events = {
        "state-update",
        "checkpoint-written",
        "candidate-created",
        "validate-result",
        "eval-result",
        "frontier-updated",
        "iteration-complete",
        "fork-created",
        "branch-cancelled",
    }
    seen = collect_sse_events(run_id, expected_stream_events)
    assert expected_stream_events.issubset(seen), (
        f"missing stream events: {sorted(expected_stream_events - seen)}"
    )

    assert_registry_contract()
    print(json.dumps({"status": "ok", "run_id": run_id, "events": sorted(seen)}))


if __name__ == "__main__":
    main()
