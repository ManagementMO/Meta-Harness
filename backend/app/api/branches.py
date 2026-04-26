"""Branch metadata and trajectory REST endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.api.runs import get_run_dir
from app.meta_harness.branches import (
    cancel_branch,
    get_branch,
    list_branches,
    reconstruct_trajectory,
)
from app.streaming import emit_run_event


router = APIRouter(tags=["branches"])


@router.get("/runs/{run_id}/branches")
async def list_run_branches(run_id: str, request: Request) -> dict[str, Any]:
    get_run_dir(request, run_id)
    return {
        "branches": [branch.to_dict() for branch in list_branches(run_id=run_id)]
    }


@router.get("/runs/{run_id}/trajectory")
async def get_run_trajectory(run_id: str, request: Request) -> dict[str, Any]:
    get_run_dir(request, run_id)
    return {"trajectory": reconstruct_trajectory(run_id)}


@router.post("/runs/{run_id}/branches/{thread_id}/cancel")
async def cancel_run_branch(
    run_id: str,
    thread_id: str,
    request: Request,
) -> dict[str, str]:
    get_run_dir(request, run_id)
    if get_branch(thread_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="branch not found",
        )
    try:
        metadata = await cancel_branch(thread_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None

    emit_run_event(
        run_id,
        "branch-cancelled",
        {
            "thread_id": thread_id,
            "reason": "requested",
        },
    )
    return {"status": metadata.status}
