"""FastAPI application for the Meta-Harness backend."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api import branches, checkpoints, events, forks, memory, runs
from app.api.runs import cancel_active_runs
from app.meta_harness.branches import cancel_all_branches
from app.meta_harness.memory import memory_store as memory_store_cm
from app.meta_harness.persistence import healthcheck, persistence_layer
from app.streaming import StreamingRegistryError


REPO_ROOT = Path(__file__).resolve().parents[2]


def _should_try_persistence(use_persistence: bool | None) -> bool:
    if use_persistence is not None:
        return use_persistence
    mode = os.environ.get("META_HARNESS_API_PERSISTENT", "auto").lower()
    return mode not in {"0", "false", "no", "memory"}


def create_app(
    *,
    repo_root: Path | None = None,
    eval_tasks_dir: Path | None = None,
    use_persistence: bool | None = None,
) -> FastAPI:
    """Create the FastAPI app.

    ``use_persistence=False`` is mainly for tests. The default mode tries
    the shared AsyncPostgresSaver and falls back to per-run in-memory
    checkpointing when Postgres is not reachable.
    """

    env_repo_root = os.environ.get("META_HARNESS_REPO_ROOT")
    repo_root = (repo_root or Path(env_repo_root or REPO_ROOT)).resolve()
    env_eval_tasks_dir = os.environ.get("META_HARNESS_EVAL_TASKS_DIR")
    eval_tasks_dir = eval_tasks_dir or Path(
        env_eval_tasks_dir or (repo_root / "eval" / "tasks")
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        load_dotenv(repo_root / ".env")
        app.state.repo_root = repo_root
        app.state.eval_tasks_dir = eval_tasks_dir
        app.state.checkpointer = None
        app.state.memory_store = None
        app.state.persistence_backend = "memory"
        app.state.persistence_cm = None
        app.state.memory_store_cm = None

        if _should_try_persistence(use_persistence) and await healthcheck():
            cm = persistence_layer()
            app.state.checkpointer = await cm.__aenter__()
            app.state.persistence_cm = cm
            app.state.persistence_backend = "postgres"
            # Best-effort memory store (same Postgres instance)
            try:
                mem_cm = memory_store_cm()
                app.state.memory_store = await mem_cm.__aenter__()
                app.state.memory_store_cm = mem_cm
            except Exception:  # noqa: BLE001 — memory is optional
                pass

        try:
            yield
        finally:
            await cancel_active_runs()
            await cancel_all_branches()
            mem_cm = getattr(app.state, "memory_store_cm", None)
            if mem_cm is not None:
                try:
                    await mem_cm.__aexit__(None, None, None)
                except Exception:  # noqa: BLE001
                    pass
            cm = getattr(app.state, "persistence_cm", None)
            if cm is not None:
                await cm.__aexit__(None, None, None)

    app = FastAPI(
        title="Meta-Harness Backend",
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(StreamingRegistryError)
    async def _streaming_error_handler(_request, exc: StreamingRegistryError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc)},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "version": __version__,
            "persistence": app.state.persistence_backend,
        }

    app.include_router(runs.router)
    app.include_router(checkpoints.router)
    app.include_router(forks.router)
    app.include_router(branches.router)
    app.include_router(events.router)
    app.include_router(memory.router)
    return app


app = create_app()
