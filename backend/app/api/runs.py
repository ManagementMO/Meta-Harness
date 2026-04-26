"""Run lifecycle REST endpoints."""

from __future__ import annotations

import asyncio
import json
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field

from app.meta_harness import runs as runs_mod
from app.meta_harness.branches import cancel_branch, list_branches
from app.meta_harness.outer import OuterLoopRunner
from app.streaming import emit_run_event


router = APIRouter(tags=["runs"])


@dataclass
class RunRecord:
    """In-process record for an API-started outer-loop run."""

    run_id: str
    thread_id: str
    status: str
    started_at: str
    domain: str
    skill_path: str | None
    budget: int
    model: str
    current_iteration: int
    run_dir: Path
    graph: Any
    task: asyncio.Task[Any] | None = None
    error: str | None = None
    checkpointer: Any = None


class CreateRunRequest(BaseModel):
    domain: str = "coding-agent"
    skill_path: str | None = None
    budget: int = Field(default=5, ge=1)
    model: str = "opus"
    fresh: bool = True
    run_name: str | None = None
    proposer: Literal["claude", "mock"] = "claude"
    mock_bench: bool | None = None
    trials: int = Field(default=5, ge=1)
    workers: int = Field(default=3, ge=1)


run_registry: dict[str, RunRecord] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generated_run_id() -> str:
    return "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _repo_root(request: Request) -> Path:
    return request.app.state.repo_root


def _eval_tasks_dir(request: Request) -> Path:
    return request.app.state.eval_tasks_dir


def _app_checkpointer(request: Request) -> Any:
    return getattr(request.app.state, "checkpointer", None)


def _app_memory_store(request: Request) -> Any:
    return getattr(request.app.state, "memory_store", None)


def _default_skill_path(repo_root: Path, domain: str) -> Path:
    return repo_root / "skills" / f"meta-harness-{domain}" / "SKILL.md"


def _resolve_skill_path(
    *,
    repo_root: Path,
    domain: str,
    skill_path: str | None,
    proposer: str,
) -> Path | None:
    if proposer == "mock":
        return None
    if skill_path:
        path = Path(skill_path)
        resolved = path if path.is_absolute() else (repo_root / path).resolve()
    else:
        resolved = _default_skill_path(repo_root, domain)
    if not resolved.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"skill not found: {resolved}",
        )
    return resolved


def _build_graph(
    *,
    run_dir: Path,
    repo_root: Path,
    eval_tasks_dir: Path,
    mock_proposer: bool,
    mock_bench: bool,
    trials: int,
    workers: int,
    skill_path: Path | None,
    checkpointer: Any,
    memory_store: Any = None,
) -> Any:
    runner = OuterLoopRunner(
        run_dir=run_dir,
        repo_root=repo_root,
        eval_tasks_dir=eval_tasks_dir,
        mock_proposer=mock_proposer,
        mock_bench=mock_bench,
        trials=trials,
        bench_workers=workers,
        skill_path=skill_path,
        checkpointer=checkpointer,
        memory_store=memory_store,
    )
    return runner.build()


def _manifest_path(run_dir: Path) -> Path:
    return run_dir / "manifest.json"


def _read_manifest(run_dir: Path) -> dict[str, Any] | None:
    path = _manifest_path(run_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write_manifest_status(run_dir: Path, **updates: Any) -> None:
    manifest = _read_manifest(run_dir) or {}
    manifest.update(updates)
    _manifest_path(run_dir).write_text(json.dumps(manifest, indent=2, default=str))


def _read_summary_rows(run_dir: Path, *, limit: int = 5) -> list[dict[str, Any]]:
    path = run_dir / "evolution_summary.jsonl"
    if not path.exists():
        return []
    rows = [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    return rows[-limit:]


def _best_score(frontier: dict[str, Any] | None) -> float | None:
    if not frontier:
        return None
    best = frontier.get("_best") or {}
    score = best.get("accuracy")
    return float(score) if score is not None else None


def _run_info_from_record(record: RunRecord) -> dict[str, Any]:
    return {
        "run_id": record.run_id,
        "thread_id": record.thread_id,
        "status": record.status,
        "started_at": record.started_at,
        "domain": record.domain,
        "skill_path": record.skill_path,
        "budget": record.budget,
        "model": record.model,
        "current_iteration": record.current_iteration,
    }


def _run_info_from_files(run_dir: Path) -> dict[str, Any]:
    manifest = _read_manifest(run_dir) or {}
    frontier = runs_mod.read_frontier(run_dir)
    rows = _read_summary_rows(run_dir, limit=5)
    current_iteration = manifest.get("current_iteration")
    if current_iteration is None and rows:
        current_iteration = rows[-1].get("iteration")
    return {
        "run_id": manifest.get("run_id", run_dir.name),
        "thread_id": manifest.get("thread_id", manifest.get("run_id", run_dir.name)),
        "status": manifest.get("status", "unknown"),
        "started_at": manifest.get("started_at"),
        "domain": manifest.get("domain", "coding-agent"),
        "skill_path": manifest.get("skill_path"),
        "budget": manifest.get("budget"),
        "model": manifest.get("model"),
        "current_iteration": current_iteration or 0,
        "best_score": _best_score(frontier),
    }


def _full_run_info(run_dir: Path, record: RunRecord | None = None) -> dict[str, Any]:
    base = _run_info_from_record(record) if record else _run_info_from_files(run_dir)
    frontier = runs_mod.read_frontier(run_dir)
    base.update(
        {
            "manifest": _read_manifest(run_dir) or {},
            "frontier_val": frontier,
            "summary_rows": _read_summary_rows(run_dir, limit=5),
            "best_score": _best_score(frontier),
        }
    )
    if record and record.error:
        base["error"] = record.error
    return base


async def _emit_checkpoint_events(record: RunRecord) -> None:
    from app.meta_harness.branches import get_state_history

    try:
        history = await get_state_history(record.graph, thread_id=record.thread_id)
    except Exception:
        return
    for checkpoint in reversed(history):
        emit_run_event(
            record.run_id,
            "checkpoint-written",
            {
                "thread_id": checkpoint.thread_id,
                "checkpoint_id": checkpoint.checkpoint_id,
                "parent_checkpoint_id": checkpoint.parent_checkpoint_id,
                "ts": checkpoint.ts,
                "node": checkpoint.node,
            },
            event_id=checkpoint.checkpoint_id,
        )


async def _execute_run(record: RunRecord, initial_state: dict[str, Any]) -> None:
    config = {
        "configurable": {"thread_id": record.thread_id},
        "recursion_limit": 200,
    }
    try:
        final = await record.graph.ainvoke(initial_state, config=config)
    except asyncio.CancelledError:
        record.status = "cancelled"
        _write_manifest_status(record.run_dir, status="cancelled")
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced through API + SSE
        record.status = "failed"
        record.error = str(exc)
        _write_manifest_status(record.run_dir, status="failed", error=str(exc))
        emit_run_event(
            record.run_id,
            "error",
            {
                "thread_id": record.thread_id,
                "node": "outer_loop",
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        return

    record.status = "completed"
    record.current_iteration = int(final.get("iteration", record.current_iteration))
    _write_manifest_status(
        record.run_dir,
        status="completed",
        current_iteration=record.current_iteration,
        finished_at=_now(),
    )
    await _emit_checkpoint_events(record)


def get_run_record(run_id: str) -> RunRecord | None:
    return run_registry.get(run_id)


def get_run_dir(request: Request, run_id: str) -> Path:
    run_dir = _repo_root(request) / "runs" / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return run_dir


def get_run_graph(request: Request, run_id: str) -> Any:
    record = run_registry.get(run_id)
    if record is not None:
        return record.graph

    run_dir = get_run_dir(request, run_id)
    manifest = _read_manifest(run_dir)
    if manifest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="run manifest not found",
        )

    checkpointer = _app_checkpointer(request)
    if checkpointer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="run graph unavailable without an active in-process record",
        )

    repo_root = _repo_root(request)
    skill_raw = manifest.get("skill_path")
    skill_path = Path(skill_raw) if skill_raw else None
    graph = _build_graph(
        run_dir=run_dir,
        repo_root=repo_root,
        eval_tasks_dir=_eval_tasks_dir(request),
        mock_proposer=bool(manifest.get("mock_proposer", False)),
        mock_bench=bool(manifest.get("mock_bench", False)),
        trials=int(manifest.get("trials", 5)),
        workers=int(manifest.get("workers", 3)),
        skill_path=skill_path,
        checkpointer=checkpointer,
        memory_store=_app_memory_store(request),
    )
    return graph


async def cancel_active_runs() -> None:
    """Best-effort shutdown cleanup for API-started tasks."""

    for record in list(run_registry.values()):
        if record.task is not None and not record.task.done():
            record.task.cancel()
            try:
                await record.task
            except asyncio.CancelledError:
                pass


def clear_run_state() -> None:
    """Clear the in-process run registry. Intended for tests."""

    run_registry.clear()


@router.post("/runs", status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: CreateRunRequest,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    repo_root = _repo_root(request)
    run_id = payload.run_name or _generated_run_id()
    run_dir = repo_root / "runs" / run_id
    if run_id in run_registry and run_registry[run_id].task is not None:
        task = run_registry[run_id].task
        if not task.done():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="run already active",
            )
    if run_dir.exists() and not payload.fresh:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="run already exists",
        )

    skill_path = _resolve_skill_path(
        repo_root=repo_root,
        domain=payload.domain,
        skill_path=payload.skill_path,
        proposer=payload.proposer,
    )
    run_dir = runs_mod.make_run_dir(repo_root, run_id, fresh=payload.fresh)
    mock_proposer = payload.proposer == "mock"
    mock_bench = payload.mock_bench if payload.mock_bench is not None else mock_proposer
    started_at = _now()
    runs_mod.write_manifest(
        run_dir,
        run_id=run_id,
        thread_id=run_id,
        status="running",
        started_at=started_at,
        domain=payload.domain,
        skill_path=str(skill_path) if skill_path else payload.skill_path,
        budget=payload.budget,
        model=payload.model,
        current_iteration=0,
        mock_proposer=mock_proposer,
        mock_bench=mock_bench,
        trials=payload.trials,
        workers=payload.workers,
    )

    checkpointer = _app_checkpointer(request) or MemorySaver()
    graph = _build_graph(
        run_dir=run_dir,
        repo_root=repo_root,
        eval_tasks_dir=_eval_tasks_dir(request),
        mock_proposer=mock_proposer,
        mock_bench=mock_bench,
        trials=payload.trials,
        workers=payload.workers,
        skill_path=skill_path,
        checkpointer=checkpointer,
        memory_store=_app_memory_store(request),
    )
    record = RunRecord(
        run_id=run_id,
        thread_id=run_id,
        status="running",
        started_at=started_at,
        domain=payload.domain,
        skill_path=str(skill_path) if skill_path else payload.skill_path,
        budget=payload.budget,
        model=payload.model,
        current_iteration=0,
        run_dir=run_dir,
        graph=graph,
        checkpointer=checkpointer,
    )
    initial_state = {
        "run_id": run_id,
        "iteration": 0,
        "budget_remaining": payload.budget,
        "candidates": [],
        "frontier": [],
        "best_candidate": None,
        "proposer_prior": "",
    }
    record.task = asyncio.create_task(
        _execute_run(record, initial_state),
        name=f"run:{run_id}",
    )
    run_registry[run_id] = record

    response.headers["Location"] = f"/runs/{run_id}"
    return _run_info_from_record(record)


@router.get("/runs")
async def list_runs(request: Request) -> dict[str, Any]:
    runs_root = _repo_root(request) / "runs"
    runs: list[dict[str, Any]] = []
    if runs_root.exists():
        for run_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
            record = run_registry.get(run_dir.name)
            info = _run_info_from_record(record) if record else _run_info_from_files(run_dir)
            if "best_score" not in info:
                info["best_score"] = _best_score(runs_mod.read_frontier(run_dir))
            runs.append(
                {
                    "run_id": info["run_id"],
                    "thread_id": info["thread_id"],
                    "status": info["status"],
                    "started_at": info["started_at"],
                    "current_iteration": info["current_iteration"],
                    "best_score": info.get("best_score"),
                }
            )
    return {"runs": runs}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> dict[str, Any]:
    run_dir = get_run_dir(request, run_id)
    return _full_run_info(run_dir, run_registry.get(run_id))


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str, request: Request) -> dict[str, str]:
    run_dir = get_run_dir(request, run_id)
    record = run_registry.get(run_id)
    if record and record.task is not None and not record.task.done():
        record.task.cancel()
        try:
            await record.task
        except asyncio.CancelledError:
            pass
    if record:
        record.status = "cancelled"
    for branch in list_branches(run_id=run_id):
        await cancel_branch(branch.thread_id)
    _write_manifest_status(run_dir, status="cancelled")
    return {"status": "cancelled"}
