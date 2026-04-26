"""Memory REST endpoints backed by step 8 PostgresStore.

``GET /memory/{namespace}`` lists learned patterns.
``POST /memory/{namespace}/search`` performs recency-weighted pattern search.

Falls back to empty results when the memory store is unavailable
(Postgres down, store not configured) — the frontend treats this
as a valid placeholder.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.meta_harness.memory import (
    format_patterns_for_prompt,
    list_namespace,
    search_patterns,
)


router = APIRouter(tags=["memory"])


class MemorySearchRequest(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1)


def _namespace(namespace: str) -> list[str]:
    if namespace.startswith("learned_patterns:"):
        return ["learned_patterns", namespace.split(":", 1)[1]]
    return ["learned_patterns", namespace]


def _get_memory_store(request: Request) -> Any:
    """Return the app-level memory store, or ``None``."""
    return getattr(request.app.state, "memory_store", None)


@router.get("/memory/{namespace}")
async def list_memory(
    namespace: str,
    request: Request,
    limit: int = Query(default=50, ge=1),
) -> dict[str, Any]:
    store = _get_memory_store(request)
    if store is None:
        return {
            "namespace": _namespace(namespace),
            "entries": [],
            "limit": limit,
            "implemented": False,
        }
    try:
        entries = await list_namespace(store, namespace, limit=limit)
        return {
            "namespace": _namespace(namespace),
            "entries": entries,
            "limit": limit,
            "implemented": True,
        }
    except Exception:  # noqa: BLE001 — memory is best-effort
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
    request: Request,
) -> dict[str, Any]:
    store = _get_memory_store(request)
    if store is None:
        return {
            "namespace": _namespace(namespace),
            "query": payload.query,
            "limit": payload.limit,
            "results": [],
            "implemented": False,
        }
    try:
        patterns = await search_patterns(
            store, namespace, limit=payload.limit
        )
        return {
            "namespace": _namespace(namespace),
            "query": payload.query,
            "limit": payload.limit,
            "results": patterns,
            "formatted": format_patterns_for_prompt(patterns),
            "implemented": True,
        }
    except Exception:  # noqa: BLE001 — memory is best-effort
        return {
            "namespace": _namespace(namespace),
            "query": payload.query,
            "limit": payload.limit,
            "results": [],
            "implemented": False,
        }
