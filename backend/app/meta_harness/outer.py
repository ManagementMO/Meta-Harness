"""Outer-loop state machine: ``propose → validate → benchmark → update_frontier``.

Per Appendix B §B.6.1 / INTERFACES.md §1.1. **All nodes are async**
(step 7 refactor) so the outer graph integrates cleanly with
``AsyncPostgresSaver`` and concurrent branches (Appendix A).

The ``benchmark`` node uses ``asyncio.Semaphore`` for bounded
concurrency over (task × trial) tuples — explicitly **not**
``asyncio.gather`` over branches that may interrupt (per Appendix A
§A.4 Gotcha 2). Inner-loop trials don't use ``interrupt()``, so
gather over them is safe.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.meta_harness import frontier as fr
from app.meta_harness import memory as mem
from app.meta_harness import proposer as prp
from app.meta_harness import runs as runs_mod
from app.meta_harness.harness import CodingAgentHarness
from app.meta_harness.inner import run_inner_loop
from app.meta_harness.sandbox import sandbox_for
from app.meta_harness.state import MetaHarnessState
from app.streaming import emit_run_event


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _thread_id(state: MetaHarnessState, config: RunnableConfig | None) -> str:
    configurable = (config or {}).get("configurable", {})
    return str(configurable.get("thread_id") or state["run_id"])


def _summary(state: MetaHarnessState, *, iteration: int | None = None) -> dict[str, Any]:
    return {
        "candidates_count": len(state.get("candidates") or []),
        "budget_remaining": state.get("budget_remaining"),
        "best_candidate": state.get("best_candidate"),
        "iteration": iteration if iteration is not None else state.get("iteration"),
    }


def _emit(
    state: MetaHarnessState,
    config: RunnableConfig | None,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    payload.setdefault("thread_id", _thread_id(state, config))
    emit_run_event(state["run_id"], event_type, payload)


class OuterLoopRunner:
    """Builds the outer LangGraph for one run.

    Flags:
    - ``mock_proposer``: use ``proposer.mock_propose`` (step 5).
    - ``mock_bench``: skip the inner loop and synthesize scores per
      candidate (fast outer-loop testing).
    - ``checkpointer``: ``AsyncPostgresSaver`` (step 7) or ``None`` for
      in-memory.
    """

    def __init__(
        self,
        *,
        run_dir: Path,
        repo_root: Path,
        eval_tasks_dir: Path,
        mock_proposer: bool,
        mock_bench: bool,
        trials: int,
        bench_workers: int,
        skill_path: Path | None = None,
        checkpointer: Any = None,
        memory_store: Any = None,
    ) -> None:
        self.run_dir = run_dir
        self.repo_root = repo_root
        self.eval_tasks_dir = eval_tasks_dir
        self.mock_proposer = mock_proposer
        self.mock_bench = mock_bench
        self.trials = trials
        self.bench_workers = bench_workers
        self.skill_path = skill_path
        self.checkpointer = checkpointer
        self.memory_store = memory_store

    # ── propose ───────────────────────────────────────────────────────

    async def propose(
        self,
        state: MetaHarnessState,
        config: RunnableConfig = None,
    ) -> dict[str, Any]:
        iteration = state["iteration"] + 1
        parent_name = state.get("best_candidate")
        if self.mock_proposer:
            payload = await asyncio.to_thread(
                prp.mock_propose,
                run_dir=self.run_dir,
                iteration=iteration,
                parent_name=parent_name,
                repo_root=self.repo_root,
            )
        else:
            if self.skill_path is None:
                raise ValueError("skill_path required for non-mock proposer")
            # Inject cross-run memory patterns into the proposer prior
            # (step 8). Patterns from prior runs are read from
            # PostgresStore and rendered as a Markdown section.
            proposer_prior = state.get("proposer_prior", "")
            if self.memory_store is not None:
                try:
                    patterns = await mem.search_patterns(
                        self.memory_store, limit=5,
                    )
                    memory_section = mem.format_patterns_for_prompt(patterns)
                    if memory_section:
                        proposer_prior = (
                            (proposer_prior + "\n\n" + memory_section)
                            if proposer_prior
                            else memory_section
                        )
                except Exception:  # noqa: BLE001 — memory is best-effort
                    pass
            # claude_propose spawns a subprocess. Wrap in to_thread to
            # avoid blocking the outer event loop while it runs.
            payload = await asyncio.to_thread(
                prp.claude_propose,
                run_dir=self.run_dir,
                iteration=iteration,
                parent_name=parent_name,
                repo_root=self.repo_root,
                skill_path=self.skill_path,
                proposer_prior=proposer_prior,
            )
        new_candidates = list(state.get("candidates") or [])
        for c in payload["candidates"]:
            new_candidates.append(
                {
                    "name": c["name"],
                    "import_path": c["import_path"],
                    "parent": c.get("parent"),
                    "hypothesis": c.get("hypothesis", ""),
                    "axis": c.get("axis", "exploitation"),
                    "expected_score_delta": c.get("expected_score_delta"),
                    "iteration": iteration,
                    "status": "pending",
                    "scores": None,
                    "delta": None,
                    "cost_usd": None,
                }
            )
            _emit(
                state,
                config,
                "candidate-created",
                {
                    "candidate": c["name"],
                    "import_path": c["import_path"],
                    "parent": c.get("parent"),
                },
            )
        _emit(
            state,
            config,
            "state-update",
            {
                "node": "propose",
                "iteration": iteration,
                "ts": _now(),
                "summary": {
                    **_summary(state, iteration=iteration),
                    "candidates_count": len(new_candidates),
                },
            },
        )
        return {"iteration": iteration, "candidates": new_candidates}

    # ── validate ──────────────────────────────────────────────────────

    async def validate(
        self,
        state: MetaHarnessState,
        config: RunnableConfig = None,
    ) -> dict[str, Any]:
        candidate = state["candidates"][-1]
        if str(self.repo_root) not in sys.path:
            sys.path.insert(0, str(self.repo_root))
        module_path, _, class_name = candidate["import_path"].partition(":")
        error: str | None = None
        try:
            mod = await asyncio.to_thread(importlib.import_module, module_path)
            cls = getattr(mod, class_name)
            assert issubclass(cls, CodingAgentHarness) or cls.__name__.startswith(
                "MockHarness"
            ), f"{candidate['import_path']} is not a CodingAgentHarness subclass"
            candidate["status"] = "pending"
            valid = True
        except Exception as exc:  # noqa: BLE001 — record any error
            candidate["status"] = "smoke_failed"
            candidate["scores"] = {"error": str(exc)}
            error = str(exc)
            valid = False
        payload: dict[str, Any] = {
            "candidate": candidate["name"],
            "valid": valid,
        }
        if error:
            payload["error"] = error
        _emit(state, config, "validate-result", payload)
        _emit(
            state,
            config,
            "state-update",
            {
                "node": "validate",
                "iteration": state["iteration"],
                "ts": _now(),
                "summary": _summary(state),
            },
        )
        return {"candidates": state["candidates"], "_last_valid": valid}

    # ── benchmark ─────────────────────────────────────────────────────

    async def benchmark(
        self,
        state: MetaHarnessState,
        config: RunnableConfig = None,
    ) -> dict[str, Any]:
        candidate = state["candidates"][-1]
        if candidate["status"] == "smoke_failed":
            _emit(
                state,
                config,
                "state-update",
                {
                    "node": "benchmark",
                    "iteration": state["iteration"],
                    "ts": _now(),
                    "summary": _summary(state),
                },
            )
            return {"candidates": state["candidates"]}

        task_dirs = sorted(
            d
            for d in self.eval_tasks_dir.iterdir()
            if d.is_dir() and (d / "task.json").exists()
        )
        n_tasks = len(task_dirs)
        per_task: dict[str, dict[str, Any]] = {}
        total_passes = 0
        total_obs = 0

        if self.mock_bench:
            base_acc = 0.60
            bump_per_iter = 0.20
            iteration = state["iteration"]
            target_acc = min(0.95, base_acc + (iteration - 1) * bump_per_iter)
            for td in task_dirs:
                trials = [True] * int(round(self.trials * target_acc))
                trials += [False] * (self.trials - len(trials))
                pr = sum(trials) / len(trials) if trials else 0.0
                per_task[td.name] = {"pass_rate": pr, "trials": trials}
                total_passes += sum(trials)
                total_obs += len(trials)
            avg_tokens = 24000 + (iteration * 800)
            wall_time_s = 0.05 * n_tasks * self.trials
        else:
            module_path, _, class_name = candidate["import_path"].partition(":")
            mod = importlib.import_module(module_path)
            harness_class = getattr(mod, class_name)

            started = time.monotonic()
            work = [
                (td, json.loads((td / "task.json").read_text()), t)
                for td in task_dirs
                for t in range(1, self.trials + 1)
            ]
            results: dict[str, list[bool]] = {td.name: [False] * self.trials for td in task_dirs}

            sem = asyncio.Semaphore(self.bench_workers)

            async def _one_trial(td: Path, spec: dict, trial_idx: int) -> tuple[str, int, bool]:
                task_id = td.name
                trace_dir = (
                    self.run_dir
                    / "candidates"
                    / candidate["name"]
                    / "traces"
                    / f"{task_id}-trial-{trial_idx}"
                )
                async with sem:
                    harness = harness_class()
                    with sandbox_for(td / "workspace") as sandbox:
                        final = await run_inner_loop(
                            harness,
                            task_dict=spec,
                            workspace=sandbox,
                            trace_dir=trace_dir,
                            thread_id=(
                                f"bench-{candidate['name']}-{task_id}-trial-{trial_idx}"
                            ),
                        )
                return task_id, trial_idx, (final.get("score") or 0.0) >= 1.0

            trial_results = await asyncio.gather(
                *[_one_trial(td, spec, t) for td, spec, t in work],
                return_exceptions=False,
            )
            for task_id, trial_idx, passed in trial_results:
                results[task_id][trial_idx - 1] = passed

            for task_id, ts in results.items():
                pr = sum(ts) / len(ts)
                per_task[task_id] = {"pass_rate": pr, "trials": ts}
                total_passes += sum(ts)
                total_obs += len(ts)
            avg_tokens = 0
            wall_time_s = round(time.monotonic() - started, 2)

        accuracy = total_passes / total_obs if total_obs else 0.0
        eval_result = {
            "candidate": candidate["name"],
            "n_tasks": n_tasks,
            "n_trials_per_task": self.trials,
            "accuracy": round(accuracy, 4),
            "per_task": per_task,
            "tokens": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "cost_usd": 0.0,
            "wall_time_s": wall_time_s,
            "avg_tokens": avg_tokens,
            "_mock_bench": self.mock_bench,
        }
        cand_dir = runs_mod.candidate_dir(self.run_dir, candidate["name"])
        (cand_dir / "eval-result.json").write_text(json.dumps(eval_result, indent=2))

        candidate["scores"] = eval_result
        candidate["status"] = "evaluated"
        _emit(
            state,
            config,
            "eval-result",
            {
                "candidate": candidate["name"],
                "accuracy": eval_result["accuracy"],
                "per_task": eval_result["per_task"],
                "tokens": eval_result["tokens"],
                "cost_usd": eval_result["cost_usd"],
            },
        )
        _emit(
            state,
            config,
            "state-update",
            {
                "node": "benchmark",
                "iteration": state["iteration"],
                "ts": _now(),
                "summary": _summary(state),
            },
        )
        return {"candidates": state["candidates"]}

    # ── update_frontier ───────────────────────────────────────────────

    async def update_frontier(
        self,
        state: MetaHarnessState,
        config: RunnableConfig = None,
    ) -> dict[str, Any]:
        candidate = state["candidates"][-1]
        scored_statuses = {"evaluated", "accepted", "rejected"}
        evaluated = [
            {
                "name": c["name"],
                "accuracy": (c["scores"] or {}).get("accuracy", 0.0),
                "avg_tokens": (c["scores"] or {}).get("avg_tokens", 0),
            }
            for c in state["candidates"]
            if c["status"] in scored_statuses and c.get("scores")
        ]
        per_task_bests: dict[str, dict[str, Any]] = {}
        for c in state["candidates"]:
            if c["status"] not in scored_statuses or not c.get("scores"):
                continue
            for task_id, info in (c["scores"] or {}).get("per_task", {}).items():
                cur = per_task_bests.get(task_id)
                if cur is None or info["pass_rate"] > cur["pass_rate"]:
                    per_task_bests[task_id] = {
                        "best_candidate": c["name"],
                        "pass_rate": info["pass_rate"],
                    }

        frontier = fr.build_frontier_val(state["iteration"], evaluated, per_task_bests)
        runs_mod.write_frontier(self.run_dir, frontier)

        prev_best = state.get("best_candidate")
        prev_best_acc = 0.0
        for c in state["candidates"]:
            if c["name"] == prev_best:
                prev_best_acc = (c["scores"] or {}).get("accuracy", 0.0)
                break
        cand_acc = (candidate["scores"] or {}).get("accuracy", 0.0)
        delta = cand_acc - prev_best_acc if prev_best else cand_acc
        candidate["delta"] = round(delta, 4)
        accepted = candidate["status"] == "evaluated" and (
            prev_best is None or cand_acc > prev_best_acc
        )
        candidate["status"] = "accepted" if accepted else "rejected"

        runs_mod.write_status(
            self.run_dir,
            candidate["name"],
            {
                "candidate": candidate["name"],
                "accepted": accepted,
                "parent": candidate.get("parent"),
                "delta": candidate["delta"],
                "reason": "accepted" if accepted else "regression",
            },
        )

        # Step 8: write cross-run memory pattern on accepted candidate.
        if accepted and self.memory_store is not None:
            try:
                await mem.add_pattern(
                    self.memory_store,
                    pattern=(
                        f"{candidate.get('hypothesis', 'unknown hypothesis')} "
                        f"— overrode {candidate.get('axis', 'unknown')} axis"
                    ),
                    mechanism_axis=candidate.get("axis", "unknown"),
                    score_delta=candidate["delta"],
                    run_id=state["run_id"],
                )
            except Exception:  # noqa: BLE001 — memory write is best-effort
                pass

        row = {
            "iteration": state["iteration"],
            "candidate": candidate["name"],
            "import_path": candidate["import_path"],
            "parent_candidate_name": candidate.get("parent"),
            "axis": candidate.get("axis"),
            "hypothesis": candidate.get("hypothesis", ""),
            "scores": {
                "accuracy": cand_acc,
                "per_task": (candidate["scores"] or {}).get("per_task", {}),
            },
            "delta": candidate["delta"],
            "outcome": (
                f"{cand_acc:.1%} ({candidate['delta']:+.1%})" if cand_acc else "failed"
            ),
            "tokens": (candidate["scores"] or {}).get("avg_tokens", 0),
            "cost_usd": candidate.get("cost_usd") or 0.0,
        }
        runs_mod.append_evolution_summary(self.run_dir, row)

        new_best = candidate["name"] if accepted else prev_best
        new_frontier_names = frontier.get("_pareto_names", [])
        _emit(
            state,
            config,
            "frontier-updated",
            {
                "iteration": state["iteration"],
                "frontier": new_frontier_names,
                "best_candidate": new_best,
                "delta": candidate["delta"],
            },
        )
        _emit(
            state,
            config,
            "iteration-complete",
            {
                "iteration": state["iteration"],
                "status": "improved" if accepted else "no_improvement",
            },
        )
        _emit(
            state,
            config,
            "state-update",
            {
                "node": "update_frontier",
                "iteration": state["iteration"],
                "ts": _now(),
                "summary": _summary(state),
            },
        )
        return {
            "candidates": state["candidates"],
            "frontier": new_frontier_names,
            "best_candidate": new_best,
            "budget_remaining": state["budget_remaining"] - 1,
        }

    # ── routing + compile ─────────────────────────────────────────────

    def _route_after_update(self, state: MetaHarnessState) -> str:
        return "propose" if state["budget_remaining"] > 0 else "end"

    def build(self) -> Any:
        g: StateGraph = StateGraph(MetaHarnessState)
        g.add_node("propose", self.propose)
        g.add_node("validate", self.validate)
        g.add_node("benchmark", self.benchmark)
        g.add_node("update_frontier", self.update_frontier)

        g.add_edge(START, "propose")
        g.add_edge("propose", "validate")
        g.add_edge("validate", "benchmark")
        g.add_edge("benchmark", "update_frontier")
        g.add_conditional_edges(
            "update_frontier",
            self._route_after_update,
            {"propose": "propose", "end": END},
        )
        return (
            g.compile(checkpointer=self.checkpointer)
            if self.checkpointer is not None
            else g.compile()
        )


async def run_outer_loop(
    *,
    run_dir: Path,
    repo_root: Path,
    eval_tasks_dir: Path,
    mock_proposer: bool,
    mock_bench: bool,
    trials: int,
    bench_workers: int,
    budget: int,
    skill_path: Path | None = None,
    checkpointer: Any = None,
    memory_store: Any = None,
) -> MetaHarnessState:
    """Run the outer loop end-to-end (async). Returns the final state."""
    runner = OuterLoopRunner(
        run_dir=run_dir,
        repo_root=repo_root,
        eval_tasks_dir=eval_tasks_dir,
        mock_proposer=mock_proposer,
        mock_bench=mock_bench,
        trials=trials,
        bench_workers=bench_workers,
        skill_path=skill_path,
        checkpointer=checkpointer,
        memory_store=memory_store,
    )
    runs_mod.write_manifest(
        run_dir,
        run_id=run_dir.name,
        budget=budget,
        trials=trials,
        mock_proposer=mock_proposer,
        mock_bench=mock_bench,
    )
    initial: MetaHarnessState = {
        "run_id": run_dir.name,
        "iteration": 0,
        "budget_remaining": budget,
        "candidates": [],
        "frontier": [],
        "best_candidate": None,
        "proposer_prior": "",
    }
    graph = runner.build()
    final = await graph.ainvoke(
        initial,
        config={"configurable": {"thread_id": run_dir.name}, "recursion_limit": 200},
    )
    return final  # type: ignore[return-value]


async def resume_outer_loop(
    *,
    run_dir: Path,
    repo_root: Path,
    eval_tasks_dir: Path,
    checkpointer: Any,
    skill_path: Path | None = None,
) -> MetaHarnessState:
    """Resume an interrupted run from its last Postgres checkpoint.

    Reads the run's manifest.json to recover the original config
    (mock_proposer, mock_bench, trials, etc.) and resumes via
    ``graph.ainvoke(None, config={"thread_id": run_dir.name})``.
    """
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"manifest.json missing in {run_dir}; cannot resume without run config"
        )
    manifest = json.loads(manifest_path.read_text())
    runner = OuterLoopRunner(
        run_dir=run_dir,
        repo_root=repo_root,
        eval_tasks_dir=eval_tasks_dir,
        mock_proposer=manifest.get("mock_proposer", False),
        mock_bench=manifest.get("mock_bench", False),
        trials=manifest.get("trials", 5),
        bench_workers=3,
        skill_path=skill_path,
        checkpointer=checkpointer,
    )
    graph = runner.build()
    # ``None`` input + existing thread_id → resume from last checkpoint.
    final = await graph.ainvoke(
        None,
        config={"configurable": {"thread_id": run_dir.name}, "recursion_limit": 200},
    )
    return final  # type: ignore[return-value]
