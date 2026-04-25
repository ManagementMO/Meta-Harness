"""Outer-loop state machine: ``propose → validate → benchmark → update_frontier``.

Per Appendix B §B.6.1 / INTERFACES.md §1.1. Step 5 wires the graph with
mock proposer + optional mock benchmark for fast verification. Real
benchmark integration runs the inner loop per (candidate × task × trial)
and lands when the proposer goes real (step 6+).
"""

from __future__ import annotations

import importlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from app.meta_harness import frontier as fr
from app.meta_harness import proposer as prp
from app.meta_harness import runs as runs_mod
from app.meta_harness.harness import CodingAgentHarness
from app.meta_harness.inner import run_inner_loop
from app.meta_harness.sandbox import sandbox_for
from app.meta_harness.state import MetaHarnessState


# ──────────────────────────────────────────────────────────────────────
# Outer node bodies (closure-built in OuterLoopRunner).
# ──────────────────────────────────────────────────────────────────────


class OuterLoopRunner:
    """Builds the outer LangGraph for one run.

    Flags:
    - ``mock_proposer``: use ``proposer.mock_propose`` (step 5).
    - ``mock_bench``: skip the inner loop and synthesize scores per
      candidate (step 5 fast-path).
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
    ) -> None:
        self.run_dir = run_dir
        self.repo_root = repo_root
        self.eval_tasks_dir = eval_tasks_dir
        self.mock_proposer = mock_proposer
        self.mock_bench = mock_bench
        self.trials = trials
        self.bench_workers = bench_workers
        self.skill_path = skill_path

    # ── propose ───────────────────────────────────────────────────────

    def propose(self, state: MetaHarnessState) -> dict[str, Any]:
        iteration = state["iteration"] + 1
        parent_name = state.get("best_candidate")
        if self.mock_proposer:
            payload = prp.mock_propose(
                run_dir=self.run_dir,
                iteration=iteration,
                parent_name=parent_name,
                repo_root=self.repo_root,
            )
        else:
            if self.skill_path is None:
                raise ValueError("skill_path required for non-mock proposer")
            payload = prp.claude_propose(
                run_dir=self.run_dir,
                iteration=iteration,
                parent_name=parent_name,
                repo_root=self.repo_root,
                skill_path=self.skill_path,
                proposer_prior=state.get("proposer_prior", ""),
            )
        # State carries the candidate dicts (from pending_eval.json).
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
        return {"iteration": iteration, "candidates": new_candidates}

    # ── validate ──────────────────────────────────────────────────────

    def validate(self, state: MetaHarnessState) -> dict[str, Any]:
        candidate = state["candidates"][-1]
        # Repo root must be on sys.path so ``agents.<n>`` imports work.
        if str(self.repo_root) not in sys.path:
            sys.path.insert(0, str(self.repo_root))
        module_path, _, class_name = candidate["import_path"].partition(":")
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            assert issubclass(cls, CodingAgentHarness) or cls.__name__.startswith("MockHarness"), (
                f"{candidate['import_path']} is not a CodingAgentHarness subclass"
            )
            candidate["status"] = "pending"
            valid = True
        except Exception as exc:  # noqa: BLE001 — we want to record any error
            candidate["status"] = "smoke_failed"
            candidate["scores"] = {"error": str(exc)}
            valid = False
        return {"candidates": state["candidates"], "_last_valid": valid}

    # ── benchmark ─────────────────────────────────────────────────────

    def benchmark(self, state: MetaHarnessState) -> dict[str, Any]:
        candidate = state["candidates"][-1]
        if candidate["status"] == "smoke_failed":
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
            # Synthesize scores: each iteration's candidate gets a
            # visible accuracy bump (rounding to N/5 trials means we
            # need ≥0.20 spread between iterations to see arc movement).
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
            avg_tokens = 24000 + (iteration * 800)  # synthetic token count
            wall_time_s = 0.05 * n_tasks * self.trials
        else:
            # Real benchmark: spawn inner loop per (task × trial).
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

            def _one_trial(td: Path, spec: dict, trial_idx: int) -> tuple[str, int, bool]:
                task_id = td.name
                trace_dir = (
                    self.run_dir
                    / "candidates"
                    / candidate["name"]
                    / "traces"
                    / f"{task_id}-trial-{trial_idx}"
                )
                harness = harness_class()
                with sandbox_for(td / "workspace") as sandbox:
                    final = run_inner_loop(
                        harness,
                        task_dict=spec,
                        workspace=sandbox,
                        trace_dir=trace_dir,
                        thread_id=f"outer-{candidate['name']}-{task_id}-trial-{trial_idx}",
                    )
                return task_id, trial_idx, (final.get("score") or 0.0) >= 1.0

            with ThreadPoolExecutor(max_workers=self.bench_workers) as pool:
                futures = [pool.submit(_one_trial, td, spec, t) for td, spec, t in work]
                for fut in as_completed(futures):
                    task_id, trial_idx, passed = fut.result()
                    results[task_id][trial_idx - 1] = passed
            for task_id, trial_results in results.items():
                pr = sum(trial_results) / len(trial_results)
                per_task[task_id] = {"pass_rate": pr, "trials": trial_results}
                total_passes += sum(trial_results)
                total_obs += len(trial_results)
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
        return {"candidates": state["candidates"]}

    # ── update_frontier ───────────────────────────────────────────────

    def update_frontier(self, state: MetaHarnessState) -> dict[str, Any]:
        candidate = state["candidates"][-1]
        # Build the candidates list for Pareto computation. Include any
        # candidate that has been scored — its current status may already
        # be "accepted" or "rejected" from a prior iteration.
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

        # Determine new best + delta + accept/reject.
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

        # status.json per candidate
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

        # evolution_summary.jsonl row
        row = {
            "iteration": state["iteration"],
            "candidate": candidate["name"],
            "import_path": candidate["import_path"],
            "parent_candidate_name": candidate.get("parent"),
            "axis": candidate.get("axis"),
            "hypothesis": candidate.get("hypothesis", ""),
            "scores": {"accuracy": cand_acc, "per_task": (candidate["scores"] or {}).get("per_task", {})},
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
        return g.compile()


def run_outer_loop(
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
) -> MetaHarnessState:
    """Run the outer loop end-to-end. Returns the final state."""
    runner = OuterLoopRunner(
        run_dir=run_dir,
        repo_root=repo_root,
        eval_tasks_dir=eval_tasks_dir,
        mock_proposer=mock_proposer,
        mock_bench=mock_bench,
        trials=trials,
        bench_workers=bench_workers,
        skill_path=skill_path,
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
    final = graph.invoke(
        initial,
        config={"configurable": {"thread_id": run_dir.name}, "recursion_limit": 200},
    )
    return final  # type: ignore[return-value]
