"""Evidence-backed refinement REST endpoints."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.runs import get_run_dir
from app.meta_harness.refinements import (
    apply_refinement,
    load_refinement,
    propose_refinement,
    reject_refinement,
    rollback_refinement,
)

router = APIRouter(tags=["refinements"])


class ProposeRefinementRequest(BaseModel):
    kind: Literal["prompt", "memory", "skill", "subagent", "control_flow", "tool_interface"]
    scope: Literal["attempt", "run", "project", "global"]
    target: str
    content: str
    existing_content: str | None = None
    parent_version: str | None = None
    proposed_version: str
    rationale: str
    evidence: list[dict[str, str]] = Field(min_length=1)
    expected_outcome: str


class RejectRefinementRequest(BaseModel):
    reason: str


@router.get("/runs/{run_id}/refinements")
async def list_refinements(run_id: str, request: Request) -> dict[str, Any]:
    run_dir = get_run_dir(request, run_id)
    root = run_dir / "refinements"
    records = []
    if root.exists():
        for path in sorted(root.glob("ref_*/record.json")):
            try:
                records.append(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError):
                continue
    return {"refinements": records}


@router.post("/runs/{run_id}/refinements", status_code=status.HTTP_201_CREATED)
async def create_refinement(
    run_id: str,
    payload: ProposeRefinementRequest,
    request: Request,
) -> dict[str, Any]:
    run_dir = get_run_dir(request, run_id)
    record = propose_refinement(
        run_dir=run_dir,
        run_id=run_id,
        kind=payload.kind,
        scope=payload.scope,
        target=payload.target,
        proposed_content=payload.content.encode("utf-8"),
        existing_content=(
            payload.existing_content.encode("utf-8")
            if payload.existing_content is not None
            else None
        ),
        parent_version=payload.parent_version,
        proposed_version=payload.proposed_version,
        rationale=payload.rationale,
        evidence=payload.evidence,
        expected_outcome=payload.expected_outcome,
    )
    return record.model_dump(mode="json")


@router.post("/runs/{run_id}/refinements/{refinement_id}/apply")
async def apply_run_refinement(
    run_id: str,
    refinement_id: str,
    request: Request,
) -> dict[str, Any]:
    run_dir = get_run_dir(request, run_id)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    try:
        record = apply_refinement(
            run_dir=run_dir,
            repo_root=request.app.state.repo_root,
            run_id=run_id,
            refinement_id=refinement_id,
            mode=manifest.get("mode", "research"),
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return record.model_dump(mode="json")


@router.post("/runs/{run_id}/refinements/{refinement_id}/rollback")
async def rollback_run_refinement(
    run_id: str,
    refinement_id: str,
    request: Request,
) -> dict[str, Any]:
    run_dir = get_run_dir(request, run_id)
    try:
        record = rollback_refinement(
            run_dir=run_dir,
            repo_root=request.app.state.repo_root,
            run_id=run_id,
            refinement_id=refinement_id,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return record.model_dump(mode="json")


@router.post("/runs/{run_id}/refinements/{refinement_id}/reject")
async def reject_run_refinement(
    run_id: str,
    refinement_id: str,
    payload: RejectRefinementRequest,
    request: Request,
) -> dict[str, Any]:
    run_dir = get_run_dir(request, run_id)
    try:
        record = reject_refinement(
            run_dir=run_dir,
            run_id=run_id,
            refinement_id=refinement_id,
            reason=payload.reason,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return record.model_dump(mode="json")


@router.get("/runs/{run_id}/refinements/{refinement_id}")
async def get_run_refinement(
    run_id: str,
    refinement_id: str,
    request: Request,
) -> dict[str, Any]:
    run_dir = get_run_dir(request, run_id)
    try:
        return load_refinement(run_dir, refinement_id).model_dump(mode="json")
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="refinement not found",
        ) from exc
