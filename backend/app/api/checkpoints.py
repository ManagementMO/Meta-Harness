"""Checkpoint history REST endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api.runs import get_run_dir, get_run_graph
from app.meta_harness.branches import (
    get_checkpoint_state,
    get_state_history,
    list_branches,
)


router = APIRouter(tags=["checkpoints"])


@router.get("/runs/{run_id}/checkpoints")
async def list_checkpoints(
    run_id: str,
    request: Request,
    thread_id: str | None = Query(default=None),
) -> dict[str, Any]:
    run_dir = get_run_dir(request, run_id)
    graph = get_run_graph(request, run_id)
    thread_ids = [thread_id] if thread_id else [
        run_id,
        *[
            branch.thread_id
            for branch in list_branches(run_id=run_id, run_dir=run_dir)
        ],
    ]
    records = []
    for current_thread_id in dict.fromkeys(thread_ids):
        try:
            records.extend(
                await get_state_history(graph, thread_id=str(current_thread_id))
            )
        except Exception:
            continue
    return {"checkpoints": [record.to_dict() for record in records]}


@router.get("/runs/{run_id}/checkpoints/{checkpoint_id}")
async def get_checkpoint(
    run_id: str,
    checkpoint_id: str,
    request: Request,
    thread_id: str | None = Query(default=None),
) -> dict[str, Any]:
    run_dir = get_run_dir(request, run_id)
    graph = get_run_graph(request, run_id)
    thread_ids = [thread_id] if thread_id else [
        run_id,
        *[
            branch.thread_id
            for branch in list_branches(run_id=run_id, run_dir=run_dir)
        ],
    ]
    record = None
    resolved_thread_id = None
    for current_thread_id in dict.fromkeys(thread_ids):
        history = await get_state_history(graph, thread_id=str(current_thread_id))
        record = next(
            (item for item in history if item.checkpoint_id == checkpoint_id),
            None,
        )
        if record is not None:
            resolved_thread_id = str(current_thread_id)
            break
    if record is None or resolved_thread_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="checkpoint not found",
        )
    try:
        state = await get_checkpoint_state(
            graph,
            thread_id=resolved_thread_id,
            checkpoint_id=checkpoint_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    return {
        "checkpoint_id": checkpoint_id,
        "thread_id": resolved_thread_id,
        "state": state,
        "ts": record.ts,
        "node": record.node,
    }
