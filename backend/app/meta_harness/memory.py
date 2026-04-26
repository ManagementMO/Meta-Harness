"""Cross-run memory via LangGraph's ``AsyncPostgresStore`` (BUILD_ORDER step 8).

Schema design per the step-8 engineering spec:

- **namespace**: ``("learned_patterns", "<domain>")`` — e.g.
  ``("learned_patterns", "coding-agent")``.
- **key**: UUID — dedup is by cumulative evidence, not by overwrite.
- **value**: ``{pattern, mechanism_axis, score_delta, evidence_run_ids,
  created_at}``  — compact text; NO full source code (would blow the
  proposer's context budget).

Ranking strategy (hackathon scope): **recency-weighted top-N** via
``asearch`` with ``limit=N``.  Embeddings (semantic search) are scope
creep for a 36-hour build; they require ``pgvector`` + an embedding
model.  We sort results by ``created_at`` descending and return the
top-N to inject into the proposer's ``--append-system-prompt``.

Dedup strategy: keep both if two runs confirm the same pattern. Each
has its own ``evidence_run_ids`` list so the proposer sees the
cumulative evidence weight.

The store is DISTINCT from ``AsyncPostgresSaver`` (checkpointing).
They share the same Postgres instance but manage different tables
(``store`` vs ``checkpoints``).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from langgraph.store.postgres import AsyncPostgresStore

from app.meta_harness.persistence import get_dsn

# ── store lifecycle ──────────────────────────────────────────────────

DEFAULT_DOMAIN = "coding-agent"


@asynccontextmanager
async def memory_store(
    dsn: str | None = None,
) -> AsyncIterator[AsyncPostgresStore]:
    """Async context manager that yields an ``AsyncPostgresStore``.

    Shares the same DSN as the checkpoint ``persistence_layer`` but
    manages its own ``store`` table (created by ``store.setup()``).
    No embeddings / pgvector — plain key-value with recency sort.
    """
    dsn = dsn or get_dsn()
    async with AsyncPostgresStore.from_conn_string(dsn) as store:
        await store.setup()
        yield store


def _namespace(domain: str = DEFAULT_DOMAIN) -> tuple[str, str]:
    """Return the canonical namespace tuple for a domain."""
    return ("learned_patterns", domain)


# ── write ────────────────────────────────────────────────────────────


async def add_pattern(
    store: AsyncPostgresStore,
    *,
    pattern: str,
    mechanism_axis: str,
    score_delta: float,
    run_id: str,
    domain: str = DEFAULT_DOMAIN,
) -> str:
    """Write one pattern to the memory store. Returns the generated key.

    Called from ``update_frontier`` when a candidate is **accepted**.
    """
    key = uuid.uuid4().hex[:12]
    value = {
        "pattern": pattern,
        "mechanism_axis": mechanism_axis,
        "score_delta": round(score_delta, 4),
        "evidence_run_ids": [run_id],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await store.aput(_namespace(domain), key, value)
    return key


# ── read ─────────────────────────────────────────────────────────────


async def search_patterns(
    store: AsyncPostgresStore,
    *,
    domain: str = DEFAULT_DOMAIN,
    limit: int = 5,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Return the top-N most recent patterns for a domain, optionally
    filtered by ``query``.

    Uses ``asearch`` with a wide pre-filter ``limit`` so a query that
    matches few rows can still scan past stale ones; the final
    ``limit`` is then applied. ``query`` is matched as a
    case-insensitive substring against the ``pattern`` and
    ``mechanism_axis`` fields. Pass ``query=None`` (the default) to
    skip filtering — that's the recency-weighted top-N path the
    proposer uses.
    """
    ns = _namespace(domain)
    pre_limit = limit if query is None else max(limit * 20, 100)
    items = await store.asearch(ns, limit=pre_limit)
    results = []
    for item in items:
        val = item.value if hasattr(item, "value") else item
        if isinstance(val, dict):
            results.append(
                {
                    "key": item.key if hasattr(item, "key") else "?",
                    **val,
                }
            )
    if query:
        needle = query.lower()
        results = [
            r
            for r in results
            if needle in str(r.get("pattern", "")).lower()
            or needle in str(r.get("mechanism_axis", "")).lower()
        ]
    # Sort by created_at descending (newest first) for recency weighting.
    results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return results[:limit]


async def list_namespace(
    store: AsyncPostgresStore,
    *,
    domain: str = DEFAULT_DOMAIN,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List all patterns in a namespace (for CLI ``memory list``).

    Returns up to ``limit`` entries, newest first.
    """
    return await search_patterns(store, domain=domain, limit=limit)


# ── formatting ───────────────────────────────────────────────────────


def format_patterns_for_prompt(patterns: list[dict[str, Any]]) -> str:
    """Render patterns as a Markdown section for ``--append-system-prompt``.

    Compact format to stay within context budget. If no patterns exist,
    returns an empty string (omitted from the prompt entirely).
    """
    if not patterns:
        return ""
    lines = ["## Cross-run memory — learned patterns\n"]
    lines.append(
        "The following patterns were learned from prior evolution runs. "
        "Use them as starting hypotheses — but verify against the current "
        "traces before committing to a candidate.\n"
    )
    for i, p in enumerate(patterns, 1):
        delta = p.get("score_delta", 0)
        sign = "+" if delta >= 0 else ""
        runs = ", ".join(p.get("evidence_run_ids", []))
        lines.append(
            f"{i}. **{p.get('mechanism_axis', 'unknown')}** "
            f"({sign}{delta:.1%} delta): {p.get('pattern', '?')} "
            f"[evidence: {runs}]"
        )
    return "\n".join(lines) + "\n"
