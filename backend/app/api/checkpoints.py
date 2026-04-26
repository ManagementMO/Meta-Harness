"""Checkpoint history REST endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.api.runs import get_run_dir, get_run_graph
from app.meta_harness.branches import get_checkpoint_state, get_state_history


router = APIRouter(tags=["checkpoints"])


@router.get("/runs/{run_id}/checkpoints")
async def list_checkpoints(run_id: str, request: Request) -> dict[str, Any]:
    get_run_dir(request, run_id)
    graph = get_run_graph(request, run_id)
    history = await get_state_history(graph, thread_id=run_id)
    return {"checkpoints": [record.to_dict() for record in history]}


@router.get("/runs/{run_id}/checkpoints/{checkpoint_id}")
async def get_checkpoint(
    run_id: str,
    checkpoint_id: str,
    request: Request,
) -> dict[str, Any]:
    get_run_dir(request, run_id)
    graph = get_run_graph(request, run_id)
    history = await get_state_history(graph, thread_id=run_id)
    record = next((item for item in history if item.checkpoint_id == checkpoint_id), None)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="checkpoint not found",
        )
    try:
        state = await get_checkpoint_state(
            graph,
            thread_id=run_id,
            checkpoint_id=checkpoint_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    return {
        "checkpoint_id": checkpoint_id,
        "thread_id": run_id,
        "state": state,
        "ts": record.ts,
        "node": record.node,
    }
