"""Memory placeholder endpoints.

Step 8 is intentionally not implemented yet. These endpoints preserve the
REST contract by returning empty result sets instead of failing while the
PostgresStore-backed memory layer is absent.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field


router = APIRouter(tags=["memory"])


class MemorySearchRequest(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1)


def _namespace(namespace: str) -> list[str]:
    if namespace.startswith("learned_patterns:"):
        return ["learned_patterns", namespace.split(":", 1)[1]]
    return ["learned_patterns", namespace]


@router.get("/memory/{namespace}")
async def list_memory(
    namespace: str,
    limit: int = Query(default=50, ge=1),
) -> dict[str, Any]:
    return {
        "namespace": _namespace(namespace),
        "entries": [],
        "limit": limit,
        "implemented": False,
    }


@router.post("/memory/{namespace}/search")
async def search_memory(
    namespace: str,
    payload: MemorySearchRequest,
) -> dict[str, Any]:
    return {
        "namespace": _namespace(namespace),
        "query": payload.query,
        "limit": payload.limit,
        "results": [],
        "implemented": False,
    }
