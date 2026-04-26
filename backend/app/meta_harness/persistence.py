"""AsyncPostgresSaver setup + connection pool (BUILD_ORDER step 7).

Per Appendix A §A.3:
- Sync ``PostgresSaver`` deadlocks under concurrent use; we use the
  async-native ``AsyncPostgresSaver`` exclusively.
- Pool sized ``max_size=20`` (≈2 connections per concurrent branch).
- ``saver.setup()`` creates the checkpoint tables on first call;
  idempotent on subsequent runs.

Usage:

    async with persistence_layer() as saver:
        graph = workflow.compile(checkpointer=saver)
        await graph.ainvoke(initial_state, config={...})
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

DEFAULT_DSN = "postgresql://meta_harness:meta_harness@localhost:5432/meta_harness"

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def get_dsn() -> str:
    """Return ``POSTGRES_DSN`` from env or the local-dev default."""
    return os.environ.get("POSTGRES_DSN", DEFAULT_DSN)


@asynccontextmanager
async def persistence_layer(
    dsn: str | None = None,
    *,
    min_size: int = 4,
    max_size: int = 20,
    setup: bool = True,
) -> AsyncIterator[AsyncPostgresSaver]:
    """Async context manager that yields an ``AsyncPostgresSaver``
    backed by a sized connection pool.

    Per Appendix A §A.3 Piece 2 — ``max_size=20`` gives ~10 concurrent
    branches at 2 connections each. ``autocommit=True`` to keep
    LangGraph's checkpoint reads/writes from contending on locks.
    ``dict_row`` factory is what ``AsyncPostgresSaver`` expects.
    """
    dsn = dsn or get_dsn()
    async with AsyncConnectionPool(
        conninfo=dsn,
        min_size=min_size,
        max_size=max_size,
        timeout=30,
        kwargs={"row_factory": dict_row, "autocommit": True},
        open=False,
    ) as pool:
        await pool.open()
        saver = AsyncPostgresSaver(pool)
        if setup:
            await saver.setup()
        yield saver


async def healthcheck(dsn: str | None = None) -> bool:
    """Return ``True`` iff Postgres is reachable at the configured DSN.

    NOTE: ``psycopg.AsyncConnection.connect`` rejects an unknown
    ``timeout`` keyword. The libpq parameter is ``connect_timeout``,
    which we wire through the conninfo string so it works on both
    ``postgresql://...`` and key-value DSNs without a kwarg-mismatch
    breaking the entire test suite (which is what happened during the
    step-8/step-9 merge — every Postgres-backed test silently skipped).
    """
    try:
        dsn = dsn or get_dsn()
        sep = "&" if "?" in dsn else "?"
        conn = await AsyncConnection.connect(
            conninfo=f"{dsn}{sep}connect_timeout=5",
            row_factory=dict_row,
            autocommit=True,
        )
        async with conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 - any connection error means unhealthy
        return False
