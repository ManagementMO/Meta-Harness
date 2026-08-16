"""Run lifecycle REST endpoints."""

from __future__ import annotations

import asyncio
import difflib
import json
import re
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field

from app.meta_harness import runs as runs_mod
from app.meta_harness.artifacts import atomic_write_json, sha256_file
from app.meta_harness.branches import cancel_branch, list_branches
from app.meta_harness.candidates import (
    candidate_search_roots,
    load_candidate_artifact_any,
    locate_candidate,
)
from app.meta_harness.contracts import RunMode
from app.meta_harness.ledger import (
    lifecycle_state,
    read_events,
    transition_lifecycle,
)
from app.meta_harness.outer import OuterLoopRunner
from app.meta_harness.reports import build_run_report, finalize_run
from app.meta_harness.skill_contract import validate_skill
from app.streaming import emit_run_event


router = APIRouter(tags=["runs"])
_ARTIFACT_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


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
    mode: str
    parent_policy: str
    synthetic: bool
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
    proposer_model: str | None = None
    inner_model: str | None = None
    mode: Literal["research", "autonomous"] = "research"
    parent_policy: Literal["best_accuracy", "pareto_sample"] = "best_accuracy"
    global_memory: bool = False
    fresh: bool = True
    run_name: str | None = None
    proposer: Literal["claude", "mock"] = "claude"
    mock_bench: bool | None = None
    trials: int = Field(default=5, ge=1)
    workers: int = Field(default=3, ge=1)


class FinalizeRunRequest(BaseModel):
    candidate_ids: list[str] | None = None
    trials: int | None = Field(default=None, ge=1)
    workers: int | None = Field(default=None, ge=1)


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
    try:
        validate_skill(resolved)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid skill: {exc}",
        ) from exc
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
    mode: str = "research",
    parent_policy: str = "best_accuracy",
    inner_model: str | None = None,
    proposer_model: str = "opus",
    allow_global_memory: bool = False,
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
        mode=mode,
        parent_policy=parent_policy,
        inner_model=inner_model,
        proposer_model=proposer_model,
        allow_global_memory=allow_global_memory,
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
    updates.setdefault("updated_at", _now())
    manifest.update(updates)
    atomic_write_json(_manifest_path(run_dir), manifest)


def _summary_paths(run_dir: Path) -> list[Path]:
    paths = [run_dir / "evolution_summary.jsonl"]
    branches_root = run_dir / "branches"
    if branches_root.exists():
        paths.extend(sorted(branches_root.glob("*/evolution_summary.jsonl")))
    return paths


def _read_summary_rows(run_dir: Path, *, limit: int = 5) -> list[dict[str, Any]]:
    return _read_all_summary_rows(run_dir)[-limit:]


def _read_all_summary_rows(run_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for path in _summary_paths(run_dir)
        if path.exists()
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def _candidate_artifact_dir(run_dir: Path, candidate_name_or_id: str) -> Path:
    try:
        artifact_root, candidate_id = locate_candidate(run_dir, candidate_name_or_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="candidate not found",
        ) from exc
    candidate_dir = (artifact_root / "candidates" / candidate_id).resolve()
    if not candidate_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="candidate not found",
        )
    return candidate_dir


def _unified_candidate_diff(
    *,
    repo_root: Path,
    run_dir: Path,
    candidate_name: str,
) -> dict[str, Any]:
    del repo_root
    try:
        candidate_root, candidate = load_candidate_artifact_any(
            run_dir,
            candidate_name,
        )
        if candidate.parent_ids:
            parent_root, parent = load_candidate_artifact_any(
                run_dir,
                candidate.parent_ids[0],
            )
        else:
            parent_root, parent = None, None
    except (KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="candidate source not found",
        ) from exc
    candidate_path = candidate_root / candidate.source.artifact_path
    parent_path = (
        parent_root / parent.source.artifact_path
        if parent is not None and parent_root is not None
        else None
    )
    candidate_display_path = candidate_path.relative_to(run_dir).as_posix()
    parent_display_path = (
        parent_path.relative_to(run_dir).as_posix()
        if parent_path is not None
        else "/dev/null"
    )
    parent_text = (
        parent_path.read_text().splitlines(keepends=True)
        if parent_path is not None
        else []
    )
    candidate_text = candidate_path.read_text().splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            parent_text,
            candidate_text,
            fromfile=parent_display_path,
            tofile=candidate_display_path,
        )
    )
    return {
        "candidate": candidate.name,
        "candidate_id": candidate.candidate_id,
        "parent": parent.name if parent is not None else "baseline",
        "parent_id": parent.candidate_id if parent is not None else None,
        "from_path": parent_display_path,
        "to_path": candidate_display_path,
        "diff": diff,
    }


def _format_accuracy(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _candidate_test_output(candidate_dir: Path) -> str:
    chunks: list[str] = []
    eval_path = candidate_dir / "eval-result.json"
    if eval_path.exists():
        eval_result = json.loads(eval_path.read_text())
        chunks.append(
            "\n".join(
                [
                    f"candidate: {eval_result.get('candidate', candidate_dir.name)}",
                    f"accuracy: {_format_accuracy(eval_result.get('accuracy'))}",
                    f"tasks: {eval_result.get('n_tasks', 0)}",
                    f"trials_per_task: {eval_result.get('n_trials_per_task', 0)}",
                ]
            )
        )
    for verify_path in sorted((candidate_dir / "traces").glob("*/*verify.json"))[:10]:
        verify = json.loads(verify_path.read_text())
        chunks.append(
            "\n".join(
                [
                    f"== {verify_path.parent.name} ==",
                    f"tests_pass: {verify.get('tests_pass', False)}",
                    str(verify.get("test_output", "")).strip(),
                ]
            )
        )
    return "\n\n".join(chunk for chunk in chunks if chunk.strip())


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
        "mode": record.mode,
        "parent_policy": record.parent_policy,
        "synthetic": record.synthetic,
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
        "model": manifest.get("proposer_model", manifest.get("model")),
        "mode": manifest.get("mode", "research"),
        "parent_policy": manifest.get("parent_policy", "best_accuracy"),
        "synthetic": manifest.get("synthetic", manifest.get("mock_bench", False)),
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
            "summary_rows": _read_all_summary_rows(run_dir),
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
                "candidate": checkpoint.values_summary.get("best_candidate"),
                "candidate_id": checkpoint.values_summary.get("best_candidate_id"),
            },
            event_id=checkpoint.checkpoint_id,
        )


async def _execute_run(record: RunRecord, initial_state: dict[str, Any]) -> None:
    config = {
        "configurable": {"thread_id": record.thread_id},
        "recursion_limit": 300,
    }
    if lifecycle_state(
        record.run_dir,
        entity_type="run",
        entity_id=record.run_id,
    ) is None:
        for state_name in ("created", "admitted", "running"):
            transition_lifecycle(
                record.run_dir,
                run_id=record.run_id,
                entity_type="run",
                entity_id=record.run_id,
                to_state=state_name,
                thread_id=record.thread_id,
            )
    try:
        final = await record.graph.ainvoke(initial_state, config=config)
    except asyncio.CancelledError:
        record.status = "cancelled"
        _write_manifest_status(record.run_dir, status="cancelled")
        if lifecycle_state(
            record.run_dir,
            entity_type="run",
            entity_id=record.run_id,
        ) == "running":
            transition_lifecycle(
                record.run_dir,
                run_id=record.run_id,
                entity_type="run",
                entity_id=record.run_id,
                to_state="canceled",
                thread_id=record.thread_id,
            )
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced through API + SSE
        record.status = "failed"
        record.error = str(exc)
        _write_manifest_status(record.run_dir, status="failed", error=str(exc))
        if lifecycle_state(
            record.run_dir,
            entity_type="run",
            entity_id=record.run_id,
        ) == "running":
            transition_lifecycle(
                record.run_dir,
                run_id=record.run_id,
                entity_type="run",
                entity_id=record.run_id,
                to_state="failed",
                thread_id=record.thread_id,
                reason=str(exc),
            )
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
        best_candidate=final.get("best_candidate"),
        best_candidate_id=final.get("best_candidate_id"),
        finished_at=_now(),
    )
    if lifecycle_state(
        record.run_dir,
        entity_type="run",
        entity_id=record.run_id,
    ) == "running":
        transition_lifecycle(
            record.run_dir,
            run_id=record.run_id,
            entity_type="run",
            entity_id=record.run_id,
            to_state="succeeded",
            thread_id=record.thread_id,
        )
    await _emit_checkpoint_events(record)


def get_run_record(run_id: str) -> RunRecord | None:
    return run_registry.get(run_id)


def get_run_dir(request: Request, run_id: str) -> Path:
    try:
        run_dir = runs_mod.make_run_path(_repo_root(request), run_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="run not found",
        ) from None
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
        mode=manifest.get("mode", "research"),
        parent_policy=manifest.get("parent_policy", "best_accuracy"),
        inner_model=(manifest.get("policy") or {}).get("inner_model"),
        proposer_model=manifest.get("proposer_model", manifest.get("model", "opus")),
        allow_global_memory=bool(
            (manifest.get("policy") or {}).get("allow_global_memory", False)
        ),
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
    if payload.mode == RunMode.RESEARCH.value and payload.global_memory:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="research mode forbids global memory",
        )
    run_id = payload.run_name if payload.run_name is not None else _generated_run_id()
    try:
        run_dir = runs_mod.make_run_path(repo_root, run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from None
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
        model=payload.proposer_model or payload.model,
        proposer_model=payload.proposer_model or payload.model,
        inner_model=payload.inner_model,
        mode=payload.mode,
        parent_policy=payload.parent_policy,
        global_memory=payload.global_memory,
        synthetic=mock_bench,
        persistence_backend=getattr(request.app.state, "persistence_backend", "memory"),
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
        memory_store=(
            _app_memory_store(request) if payload.global_memory else None
        ),
        mode=payload.mode,
        parent_policy=payload.parent_policy,
        inner_model=payload.inner_model,
        proposer_model=payload.proposer_model or payload.model,
        allow_global_memory=payload.global_memory,
    )
    record = RunRecord(
        run_id=run_id,
        thread_id=run_id,
        status="running",
        started_at=started_at,
        domain=payload.domain,
        skill_path=str(skill_path) if skill_path else payload.skill_path,
        budget=payload.budget,
        model=payload.proposer_model or payload.model,
        mode=payload.mode,
        parent_policy=payload.parent_policy,
        synthetic=mock_bench,
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
        "best_candidate_id": None,
        "active_candidate_ids": [],
        "proposer_prior": "",
        "mode": payload.mode,
        "parent_policy": payload.parent_policy,
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
                    "mode": info.get("mode", "research"),
                    "synthetic": info.get("synthetic", False),
                }
            )
    return {"runs": runs}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> dict[str, Any]:
    run_dir = get_run_dir(request, run_id)
    return _full_run_info(run_dir, run_registry.get(run_id))


@router.get("/runs/{run_id}/candidates/{candidate_identifier}/diff")
async def get_candidate_diff(
    run_id: str,
    candidate_identifier: str,
    request: Request,
) -> dict[str, Any]:
    run_dir = get_run_dir(request, run_id)
    _candidate_artifact_dir(run_dir, candidate_identifier)
    return _unified_candidate_diff(
        repo_root=_repo_root(request),
        run_dir=run_dir,
        candidate_name=candidate_identifier,
    )


@router.get("/runs/{run_id}/candidates/{candidate_identifier}/test-output")
async def get_candidate_test_output(
    run_id: str,
    candidate_identifier: str,
    request: Request,
) -> dict[str, str]:
    run_dir = get_run_dir(request, run_id)
    candidate_dir = _candidate_artifact_dir(run_dir, candidate_identifier)
    return {
        "candidate": candidate_identifier,
        "output": _candidate_test_output(candidate_dir),
    }


@router.get("/runs/{run_id}/candidates/{candidate_identifier}/manifest")
async def get_candidate_manifest(
    run_id: str,
    candidate_identifier: str,
    request: Request,
) -> dict[str, Any]:
    run_dir = get_run_dir(request, run_id)
    try:
        _artifact_root, artifact = load_candidate_artifact_any(
            run_dir,
            candidate_identifier,
        )
    except (KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="candidate not found",
        ) from exc
    return artifact.model_dump(mode="json")


@router.get("/runs/{run_id}/report")
async def get_research_report(run_id: str, request: Request) -> dict[str, Any]:
    return build_run_report(get_run_dir(request, run_id))


@router.get("/runs/{run_id}/events")
async def get_evidence_events(
    run_id: str,
    request: Request,
    event_type: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    attempt_id: str | None = Query(default=None),
    candidate_id: str | None = Query(default=None),
    task_id: str | None = Query(default=None),
    tool_name: str | None = Query(default=None),
    failure_category: str | None = Query(default=None),
    turn: int | None = Query(default=None, ge=0),
    created_after: str | None = Query(default=None),
    created_before: str | None = Query(default=None),
) -> dict[str, Any]:
    run_dir = get_run_dir(request, run_id)
    roots = candidate_search_roots(run_dir)
    seen: set[str] = set()
    events = []
    for root in roots:
        for event in read_events(root):
            payload = event.payload
            if event.event_id in seen:
                continue
            if event_type and event.event_type != event_type:
                continue
            if entity_type and event.entity_type != entity_type:
                continue
            if entity_id and event.entity_id != entity_id:
                continue
            if attempt_id and event.attempt_id != attempt_id:
                continue
            if candidate_id and candidate_id not in {
                event.entity_id,
                payload.get("candidate_id"),
            }:
                continue
            if task_id and payload.get("task_id") != task_id:
                continue
            if tool_name and payload.get("tool_name") != tool_name:
                continue
            if (
                failure_category
                and payload.get("failure_category") != failure_category
            ):
                continue
            if turn is not None and payload.get("turn") != turn:
                continue
            if created_after and event.created_at < created_after:
                continue
            if created_before and event.created_at > created_before:
                continue
            seen.add(event.event_id)
            events.append(event)
    events.sort(key=lambda event: (event.created_at, event.event_id))
    return {"events": [event.model_dump(mode="json") for event in events]}


@router.get("/runs/{run_id}/artifacts/{digest}")
async def download_artifact(
    run_id: str,
    digest: str,
    request: Request,
) -> FileResponse:
    if not _ARTIFACT_DIGEST_RE.fullmatch(digest):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid artifact digest",
        )
    run_dir = get_run_dir(request, run_id)
    for root in candidate_search_roots(run_dir):
        path = root / "artifacts" / "sha256" / digest[:2] / digest
        if path.is_file():
            if sha256_file(path) != digest:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="artifact hash mismatch",
                )
            return FileResponse(
                path,
                media_type="application/octet-stream",
                filename=digest,
                headers={"X-Artifact-SHA256": digest},
            )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="artifact not found",
    )


@router.post("/runs/{run_id}/finalize")
async def finalize_research_run(
    run_id: str,
    payload: FinalizeRunRequest,
    request: Request,
) -> dict[str, Any]:
    run_dir = get_run_dir(request, run_id)
    record = run_registry.get(run_id)
    if record is not None and record.task is not None and not record.task.done():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="run must complete before finalization",
        )
    try:
        return await finalize_run(
            run_dir=run_dir,
            repo_root=_repo_root(request),
            holdout_tasks_dir=_repo_root(request) / "eval" / "holdout",
            candidate_ids=payload.candidate_ids,
            trials=payload.trials,
            workers=payload.workers,
            checkpointer=_app_checkpointer(request),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


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
    for branch in list_branches(run_id=run_id, run_dir=run_dir):
        if branch.status in {"created", "running"}:
            await cancel_branch(branch.thread_id)
    _write_manifest_status(run_dir, status="cancelled")
    return {"status": "cancelled"}
