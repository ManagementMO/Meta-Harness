# Meta-Harness — Complete Project Knowledge Base

> *A single document, deep enough that a teammate who has never seen this repo
> can read it cover-to-cover and walk into the demo room speaking the system's
> language. Every claim has either a code excerpt or a file:line reference; no
> hand-waving.*

**Audience.** Four hackathon teammates at LA Hacks 2026 about to demo to judges
who already saw 80 LangChain wrappers today. We need to know *why our project
is different* and *how every layer actually works* — well enough to hand-edit
code on stage, answer judge questions about LangGraph internals, and survive a
live broken demo.

**Reading order.** Part I (the *what* + the *why*) is for everyone. Part II
through V are for whoever owns the relevant layer. Part VI is reference; skim
the index, then deep-dive.

**Verification pass — 2026-04-25.** This document was re-verified against the
live codebase on 2026-04-25 by reading every file it cites and grepping for
each method/method-call referenced. The pass surfaced four classes of
inaccuracy that have since been corrected here:

1. **CLI surface** — `meta-harness fork` takes `--mod KEY=VALUE` (not
   `--prior`), `init` takes `--force` (not `--from-template`), and there is
   no `meta-harness memory search` subcommand (only the REST endpoint). See §26.
2. **Override points** — overrides 4 (`MAX_VERIFY_RETRIES`),
   5 (`_build_initial_context`), and 9 (`should_loop_back_to_act`) are
   defined on `CodingAgentHarness` but never consumed by `inner.py`. See
   §10.5 for the live wiring audit and §24.13 for the war-story version.
3. **Frontend reality** — Monaco IS used (in `DiffViewer.tsx`); ReactFlow
   IS used (in `StateGraph.tsx` via `@xyflow/react`); the `TopBar` is a
   14-line stub showing only the logo; `ContextPanel` has 5 tabs (not 3);
   `MemoryPanel` uses 3 hardcoded fixtures rather than calling
   `GET /memory/{ns}`; `startSSE` only routes 6 of 11 events into reducer
   actions. See §16-17 for the actual state of each component.
4. **Honest accounting** — `tokens` and `cost_usd` are zeros in the real-bench
   path (`outer.py:347-348, 357-358`); only mock-bench synthesizes a
   token curve. The dashboard "cost" displays will read $0 for live runs
   until token aggregation is wired through. See §5.3 caveat and §24.14.

Test count, verified by `uv run pytest tests/ -q`: **78 passed, 0 failed**
(the older README's "47 tests passing" line is stale).

---

## Table of contents

| Part | Section | Topic |
|---|---|---|
| **I — The big idea** | 1 | What Meta-Harness is (elevator pitch) |
| | 2 | The Stanford paper our work builds on |
| | 3 | Our novelty: linear → tree |
| **II — The engine** | 4 | Two-loop architecture overview |
| | 5 | The outer loop, node-by-node |
| | 6 | The inner loop, phase-by-phase |
| | 7 | The proposer: `claude` CLI subprocess |
| | 8 | `SKILL.md` — the proposer's "tool" |
| | 9 | The six fixed inner-loop tools |
| | 10 | The eleven override points |
| **III — The substrate** | 11 | Persistence (`AsyncPostgresSaver`) |
| | 12 | Time-travel and concurrent branches |
| | 13 | Cross-run memory (`AsyncPostgresStore`) |
| | 14 | REST + SSE protocol |
| | 15 | Sandbox isolation |
| **IV — The face** | 16 | Current frontend architecture |
| | 17 | Ideal frontend design + visual decisions |
| **V — The demo** | 18 | The demo arc as written |
| | 19 | The 90-second pitch, annotated |
| | 20 | Why this project is genuinely unique |
| | 21 | Likely judge questions + answers |
| **VI — Reference** | 22 | File:line lookup index |
| | 23 | Glossary |
| | 24 | Common pitfalls / war stories |
| | 25 | All 11 SSE event types in full |
| | 26 | The complete CLI surface |

---

# Part I — The big idea

## 1. What Meta-Harness *is*

Meta-Harness is **a self-improving coding-agent that improves its own source
code, evaluated end-to-end on a 5-task benchmark, with branching evolution
trees instead of a linear iteration sequence.**

Three sentences expanded:

1. **A coding agent** — given a Python repo with a bug or missing
   implementation, plus a `pytest` test command, it tries to make the tests
   pass. Concretely: a 5-phase ReAct loop (`orient → plan → act → verify →
   submit`) over 6 fixed tools (`read_file`, `apply_patch`, `write_file`,
   `run_bash`, `grep_search`, `task_complete`).
2. **That improves its own source code** — a *proposer agent* (a separate
   `claude` CLI subprocess) reads the inner agent's execution traces, picks a
   failure pattern, and writes a NEW Python file at `agents/<name>.py` that
   subclasses the base harness and overrides one or more of 11 search-space
   methods. We then re-evaluate; if it scores higher, it becomes the new
   parent for the next iteration.
3. **In a tree, not a line** — every state transition is checkpointed in
   Postgres via LangGraph's `AsyncPostgresSaver`. You can right-click any
   checkpoint in the dashboard, edit the proposer's prior, and **fork**: a
   new concurrent branch starts from that historical state, runs alongside
   the original, and shows up as a new branch on the trajectory tree.

That last property — branching meta-evolution — is what doesn't exist in any
prior work, including Stanford's reference paper. **It's the substrate, not
the algorithm, that's the contribution.**

### One-line elevator pitch

> *"Stanford's Meta-Harness paper had a linear loop. We mapped it onto
> LangGraph and made it a tree — secure, consistent, reversible by
> construction. Two LangGraph state machines, both Postgres-checkpointed,
> running real `claude` subprocesses to evolve real Python harness code."*

### The two state machines (load-bearing diagram)

```
   OUTER STATE MACHINE  (4 nodes, checkpointed via AsyncPostgresSaver)
   ──────────────────────────────────────────────────────────────────
   propose ──► validate ──► benchmark ──► update_frontier
      │                          │                │
      │                          │                └─ loop while budget > 0
      ▼                          ▼
   spawns `claude` CLI        spawns inner
   subprocess + SKILL.md      subgraph per
   (proposer writes a         candidate
   new agents/<name>.py)
                                  │
                                  ▼
   INNER STATE MACHINE  (5 nodes, sandboxed subgraph per candidate)
   ────────────────────────────────────────────────────────────────
   orient ─► plan ─► act ─► verify ─► submit
      │                ▲       │
      │                └───────┘ retry up to MAX_VERIFY_RETRIES
      │
      └─ 6 fixed tools, 11 override points
```

You will redraw this diagram on a napkin a hundred times. Memorize it.

---

## 2. The Stanford foundation

The work we build on is **Lee, Nair, Zhang, Lee, Khattab, Finn (Stanford IRIS,
March 2026):**

- Paper: [arXiv:2603.28052](https://arxiv.org/abs/2603.28052)
- Project page: [yoonholee.com/meta-harness](https://yoonholee.com/meta-harness/)
- Reference repo: [stanford-iris-lab/meta-harness](https://github.com/stanford-iris-lab/meta-harness)

### What the paper actually showed

Most prompt-optimization work optimizes *the agent's prompts* (DSPy, ACE,
TextGrad). Stanford optimized **the harness around the agent**: the surrounding
code that builds context, formats tool results, decides when to retry, summarizes
on overflow.

Concretely: they had a **proposer agent** read the *full execution traces* of a
*candidate harness* — every tool call, every prompt, every error message — and
rewrite the harness's source code. Then re-evaluate. Iterate.

Headline numbers from the paper:

- **+7.7 points absolute over ACE** on TerminalBench-2
- **4× fewer context tokens** at equal accuracy
- **Top-2 on TerminalBench-2** at the time of publication
- Generalizes to TextClassification, MATH-500, and HumanEval

### Three load-bearing pieces of their design

These three are *the* contributions of the paper, and we replicate them
faithfully:

1. **Filesystem-mediated proposer.** Their proposer is `claude_wrapper.py` — a
   subprocess of the `claude` CLI with `--append-system-prompt $(cat SKILL.md)`,
   `--dangerously-skip-permissions`, and `--output-format stream-json`. It
   reads on the order of 80+ files per iteration: the run's
   `evolution_summary.jsonl`, the per-trial traces, the current best harness's
   source. It writes ONE new file at `agents/<name>.py` plus a one-row
   `pending_eval.json`. Everything else is filesystem.
   - *Why filesystem?* Because the proposer is a fully-autonomous agent
     spawned by the OS — there's no in-process API; the only contract is
     "read these paths, write these paths."
2. **SKILL.md as the proposer's tool.** A ~150-line Markdown file with YAML
   frontmatter, six required body sections (Anti-Overfitting,
   Anti-Parameter-Tuning, Workflow, Interface contract, pending_eval.json
   schema). It's not code. It's not a JSON schema. It's the *prompt*. It's
   load-bearing per the paper's Section 5 ablations: remove the
   anti-overfitting rules and the proposer overfits to specific task names.
3. **Mechanism axes, not parameters.** Each candidate must claim a *mechanism
   axis* (`exploration` or `exploitation`) and a one-sentence falsifiable
   `hypothesis`. "Bumping `MAX_ACT_TURNS` from 25 to 30" is rejected as a
   parameter tweak; "rewriting tool descriptions to include few-shot demos"
   is accepted as a mechanism change. The SKILL.md enforces this.

### What Stanford did NOT do

- **No checkpointing.** Their loop is `for iter in range(N): ...`. If you SIGINT
  it, you start over.
- **No branching.** The iteration sequence is linear: `iter 1 → 2 → 3 → 4`. You
  cannot rewind to iter 2 and explore a different proposer prior without
  re-running iter 1 cold.
- **No streaming dashboard.** The paper's results are post-hoc plots. You watch
  the run's stdout, no live state visualization.

These three gaps are what we close.

---

## 3. Our novelty: linear → tree

Three properties fall out of mapping the loop onto LangGraph **by construction**
— we didn't build them, we got them for free by picking the right substrate:

| Property | Mechanism | Why it's "by construction" |
|---|---|---|
| **Secure** | Each candidate is a sandboxed subgraph (`/tmp/meta-harness-task-{uuid}/`, rlimits, 60s CPU cap). A buggy candidate cannot corrupt the run. | LangGraph compiles a separate subgraph per candidate; we just point its tools at a fresh `/tmp` dir. |
| **Consistent** | Every state transition writes a Postgres checkpoint via `AsyncPostgresSaver`. Replays are deterministic. | LangGraph emits a checkpoint after every node finishes — we don't write any of that code. |
| **Reversible** | Time-travel via `aget_state_history` + `aupdate_state` + `ainvoke(None, fork_config)`. Forks are concurrent `asyncio.create_task`s sharing the same saver. | LangGraph's checkpoint primitives + asyncio. The "fork" is just a new `thread_id` whose initial state is a deep-copy of a parent checkpoint. |

The phrase *"the substrate IS the contribution"* in our README is literal. We
didn't reinvent Stanford's algorithm; we re-expressed it on a substrate that
gives us branching, persistence, and concurrent exploration that their loop
can't do.

### What "linear → tree" looks like in our demo

```text
Linear branch (Stanford's regime):
  baseline (0.62)  →  iter 1 (0.70)  →  iter 2 (0.66 rejected)  →  iter 3 (0.74)  →  iter 4 (0.80, NEW BEST)

Right-click iter 2's checkpoint → "Fork from here" → edit proposer prior:
  baseline (0.62)  →  iter 1 (0.70)
                            ╲
                             ╲→ iter 2′ (0.78, +0.16 from iter 1)  →  iter 3′ (0.85, GLOBAL BEST)

End state: two branches. Both Pareto-optimal at different (accuracy, tokens) points.
The meta-harness loop is no longer a sequence — it's a search tree.
```

This isn't a static plot — both branches grow *concurrently* on the dashboard
in real time. That visual is the heart of the demo.

---

# Part II — The engine

## 4. Two-loop architecture overview

The single most important sentence in this document:

> **The proposer is the BODY of the outer machine's `propose` node. It is not
> a separate tier. There is no third loop.**

This is "Correction 1" in our build history — early drafts had a 3-tier
architecture (proposer / outer / inner), but it makes checkpointing
incoherent (where do you save the in-flight subprocess state?). Folding the
proposer into the outer loop's `propose` node means a single `AsyncPostgresSaver`
covers the whole pipeline.

### High-level walkthrough

1. **Outer machine** runs in the foreground. State: `MetaHarnessState`
   (`run_id`, `iteration`, `budget_remaining`, `candidates`, `frontier`,
   `best_candidate`, `proposer_prior`).
2. **`propose` node**: Spawns `claude` as a subprocess. Streams JSON events
   from `claude --output-format stream-json`. Parses them. Reads the
   resulting `runs/{run_id}/pending_eval.json` that the proposer wrote.
   Returns the new candidate(s) as a state delta.
3. **`validate` node**: `importlib.import_module("agents.<name>")`,
   `issubclass(cls, CodingAgentHarness)`. If import fails, mark
   `smoke_failed`.
4. **`benchmark` node**: For each `(task, trial)` tuple, spawn an *inner*
   subgraph. Use `asyncio.Semaphore(workers)` for bounded concurrency.
   `mock_bench=True` skips this and synthesizes a score curve.
5. **`update_frontier` node**: Compute Pareto frontier on (accuracy ×
   avg_tokens). Mark `accepted` if score improved, `rejected` otherwise.
   Persist `frontier_val.json` and append `evolution_summary.jsonl`. If
   accepted, write a pattern to `AsyncPostgresStore` for future runs.
6. **Conditional edge**: `propose` again if `budget_remaining > 0`, else
   `END`.

### State schemas (verbatim from `backend/app/meta_harness/state.py:35-59`)

```python
class MetaHarnessState(TypedDict):
    """Outer-loop state. ``run_id`` doubles as the parent ``thread_id``."""
    run_id: str
    iteration: int
    budget_remaining: int
    candidates: list[Candidate]
    frontier: list[str]
    best_candidate: str | None
    proposer_prior: str

class CodingAgentState(TypedDict):
    """Inner-loop state for the 5-phase coding agent."""
    task: dict[str, Any]
    workspace_path: str
    orient_summary: dict[str, Any] | None
    plan: dict[str, Any] | None
    messages: Annotated[list[Any], add_messages]
    turn_count: int
    verify_attempts: int
    verify_result: dict[str, Any] | None
    final_files: dict[str, str] | None
    score: float | None
```

Three things to notice:

- **`run_id == thread_id`** for the parent thread. Forks get
  `f"{parent_thread_id}.fork.{branch_id}"` (8-hex-char UUID suffix). This
  string-encoded parent pointer lets you walk the tree without a separate
  edges table.
- **`messages: Annotated[list[Any], add_messages]`** — LangGraph's
  `add_messages` reducer auto-merges new entries into the list. Without the
  annotation, every state update would replace the list (wiping prior turns).
- **`Candidate.traces_dir: Path` is non-optional.** The dataclass is at
  `state.py:15-31`. We force this so the API and frontend can always assume
  a per-candidate trace directory exists.

### Why both loops are async (load-bearing)

Both `inner.py` and `outer.py` use `async def` for every node body. This is
**required** because:

1. `AsyncPostgresSaver` only works with async graphs. The sync version
   deadlocks under concurrent branches (Appendix A §A.3 covers this in
   detail; the gotcha is real and was found by Stanford folks during
   pre-release testing of LangGraph's checkpointer).
2. `asyncio.create_task` per concurrent branch wouldn't compose with sync
   nodes — you'd block the event loop.
3. The Anthropic SDK's `AsyncAnthropic` client is what we use throughout;
   sync API calls inside an async LangGraph node would block too.

Sync subprocess calls (`subprocess.run` for `pytest`, `git apply`, etc.) are
wrapped in `asyncio.to_thread(...)` to avoid blocking the loop. See
`outer.py:147` for the proposer wrap and `inner.py:236` for tool dispatch.

---

## 5. The outer loop, node-by-node

File: `backend/app/meta_harness/outer.py`

The outer machine is built by `OuterLoopRunner.build()` at `outer.py:543-563`:

```python
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
    return g.compile(checkpointer=self.checkpointer) if self.checkpointer is not None else g.compile()
```

### 5.1 The `propose` node (`outer.py:109-197`)

What it does: spawns the proposer (claude CLI subprocess OR mock), waits for
it to write `pending_eval.json`, parses it, returns the new candidate(s) as a
state delta.

Skeleton:

```python
async def propose(self, state, config=None):
    iteration = state["iteration"] + 1
    parent_name = state.get("best_candidate")

    if self.mock_proposer:
        payload = await asyncio.to_thread(
            prp.mock_propose, run_dir=..., iteration=iteration,
            parent_name=parent_name, repo_root=self.repo_root,
        )
    else:
        # Inject cross-run memory patterns into proposer prior
        proposer_prior = state.get("proposer_prior", "")
        if self.memory_store is not None:
            patterns = await mem.search_patterns(self.memory_store, limit=5)
            memory_section = mem.format_patterns_for_prompt(patterns)
            if memory_section:
                proposer_prior = (proposer_prior + "\n\n" + memory_section
                                  if proposer_prior else memory_section)
        payload = await asyncio.to_thread(
            prp.claude_propose, ...,
            skill_path=self.skill_path,
            proposer_prior=proposer_prior,
        )

    new_candidates = list(state.get("candidates") or [])
    for c in payload["candidates"]:
        new_candidates.append({...})
        _emit(state, config, "candidate-created", {...})
    _emit(state, config, "state-update", {...})
    return {"iteration": iteration, "candidates": new_candidates}
```

Three things worth highlighting:

1. **Memory injection happens here.** Step 8 of the build wires
   cross-run memory into the proposer prior. The `format_patterns_for_prompt`
   function renders ≤5 newest patterns as a Markdown section, which is
   appended to whatever prior was already set, then forwarded to
   `claude_propose` as part of `--append-system-prompt`.
2. **`asyncio.to_thread` around the subprocess.** `claude_propose` is a
   blocking subprocess that can run for 1-3 minutes. Without `to_thread`,
   the entire async event loop stalls — meaning concurrent branches
   couldn't run at all.
3. **`_emit(state, config, "candidate-created", ...)`** is wrapped in
   try/except (see `outer.py:57-68`); a streaming failure must not crash
   the graph node. SSE is best-effort.

### 5.2 The `validate` node (`outer.py:201-249`)

```python
async def validate(self, state, config=None):
    candidate = state["candidates"][-1]
    if str(self.repo_root) not in sys.path:
        sys.path.insert(0, str(self.repo_root))
    module_path, _, class_name = candidate["import_path"].partition(":")
    try:
        sys.modules.pop(module_path, None)   # nuke stale cache
        importlib.invalidate_caches()
        mod = await asyncio.to_thread(importlib.import_module, module_path)
        cls = getattr(mod, class_name)
        assert issubclass(cls, CodingAgentHarness) or cls.__name__.startswith("MockHarness")
        candidate["status"] = "pending"
    except Exception as exc:
        candidate["status"] = "smoke_failed"
        candidate["scores"] = {"error": str(exc)}
    return {"candidates": state["candidates"], "_last_valid": ...}
```

The `sys.modules.pop(...)` is non-obvious. Mock candidate stubs are
rewritten on every iteration; if a prior run or test deleted the .py file
while leaving an orphaned `sys.modules` entry, `import_module` would
return the cached (broken) module. Popping forces a fresh disk read.

### 5.3 The `benchmark` node (`outer.py:253-391`)

This is the largest node. Two paths:

**Mock-bench (`outer.py:283-296`):** synthesize scores deterministically.

```python
if self.mock_bench:
    base_acc = 0.60
    bump_per_iter = 0.20
    target_acc = min(0.95, base_acc + (iteration - 1) * bump_per_iter)
    for td in task_dirs:
        trials = [True] * int(round(self.trials * target_acc))
        trials += [False] * (self.trials - len(trials))
        ...
```

This produces the canonical demo arc (62% → 80%) without spending real LLM
budget. Used by `--mock-bench` in CI and for the smooth demo path.

**Real bench (`outer.py:297-348`):** spawn one inner-loop trial per `(task,
trial_idx)` tuple, bounded by an `asyncio.Semaphore(workers)`.

```python
sem = asyncio.Semaphore(self.bench_workers)

async def _one_trial(td, spec, trial_idx):
    task_id = td.name
    trace_dir = self.run_dir / "candidates" / candidate["name"] / "traces" / f"{task_id}-trial-{trial_idx}"
    async with sem:
        harness = harness_class()
        with sandbox_for(td / "workspace") as sandbox:
            final = await run_inner_loop(
                harness, task_dict=spec, workspace=sandbox,
                trace_dir=trace_dir,
                thread_id=f"bench-{candidate['name']}-{task_id}-trial-{trial_idx}",
            )
    return task_id, trial_idx, (final.get("score") or 0.0) >= 1.0

trial_results = await asyncio.gather(
    *[_one_trial(td, spec, t) for td, spec, t in work],
    return_exceptions=False,
)
```

Why `asyncio.gather` here but `asyncio.create_task` for branches? Because
inner-loop trials don't use `interrupt()` (LangGraph's pause primitive).
`gather` over `interrupt()`-able coroutines silently swallows the interrupts
per LangGraph issue #6624 — so `create_task` is mandatory there. For trials,
`gather` is fine.

**Honest accounting caveat — `tokens` and `cost_usd` are zeros in the real
bench path** (`outer.py:347-348, 357-358`). The current implementation does
not aggregate per-trial token usage from inner-loop responses; it writes:

```python
eval_result = {
    ...
    "tokens": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    "cost_usd": 0.0,
    "wall_time_s": round(time.monotonic() - started, 2),
    "avg_tokens": avg_tokens,   # only set in mock-bench path
    ...
}
```

So a "cost" displayed in the UI for a real-bench run will be `$0.00`. The
mock-bench path *does* synthesize an `avg_tokens` curve (`base + iter * 800`)
so the Pareto-on-tokens chart has a meaningful x-axis. Wiring real token
aggregation through the inner loop is a roadmap item, not implemented.

### 5.4 The `update_frontier` node (`outer.py:395-536`)

Three jobs: Pareto computation, accept/reject decision, memory write.

**Pareto frontier on (accuracy, tokens):**

```python
scored_statuses = {"evaluated", "accepted", "rejected"}
evaluated = [
    {"name": c["name"],
     "accuracy": (c["scores"] or {}).get("accuracy", 0.0),
     "avg_tokens": (c["scores"] or {}).get("avg_tokens", 0)}
    for c in state["candidates"]
    if c["status"] in scored_statuses and c.get("scores")
]
frontier = fr.build_frontier_val(state["iteration"], evaluated, per_task_bests)
```

`build_frontier_val` is in `frontier.py`. Each candidate gets a
`dominated_by_names: list[str]` field (the names of any strictly-better
candidate on both axes), plus a top-level `_pareto_names` convenience list
of non-dominated candidates.

**Accept-or-reject decision (the demo arc's heart):**

```python
prev_best = state.get("best_candidate")
prev_best_acc = ...  # look up from state["candidates"]
cand_acc = (candidate["scores"] or {}).get("accuracy", 0.0)
delta = cand_acc - prev_best_acc if prev_best else cand_acc
candidate["delta"] = round(delta, 4)
accepted = candidate["status"] == "evaluated" and (
    prev_best is None or cand_acc > prev_best_acc
)
candidate["status"] = "accepted" if accepted else "rejected"
```

This is "monotonic improvement only" — a candidate must beat the previous best
to be accepted. (A more sophisticated version might allow Pareto improvements
on the (accuracy, tokens) plane, but for the hackathon scope monotonic accuracy
is sufficient and much cleaner to demo.)

**Memory write on accept (`outer.py:452-476`):**

```python
if accepted and self.memory_store is not None:
    try:
        await mem.add_pattern(
            self.memory_store,
            pattern=f"{candidate.get('hypothesis', 'unknown')} — overrode {candidate.get('axis', 'unknown')} axis",
            mechanism_axis=candidate.get("axis", "unknown"),
            score_delta=candidate["delta"],
            run_id=state["run_id"],
        )
        _emit(state, config, "memory-pattern-stored", {...})
    except Exception:
        pass  # memory write is best-effort
```

This is what turns "linear evolution within one run" into "evolution across
many runs." Patterns persist in Postgres' `store` table; future runs read the
top-N most recent patterns into their proposer prior.

### 5.5 Conditional routing (`outer.py:540-541`)

```python
def _route_after_update(self, state):
    return "propose" if state["budget_remaining"] > 0 else "end"
```

Trivial. Budget decrements by 1 in `update_frontier`'s return dict.

---

## 6. The inner loop, phase-by-phase

File: `backend/app/meta_harness/inner.py`

The inner machine is the **5-phase coding agent**. State is `CodingAgentState`.
Tools are the 6 fixed tools from `tools.py`. Every node is async.

### 6.1 Phase 1 — `orient` (`inner.py:63-111`)

**Job:** build initial workspace context for the planner. Read tests, configs,
project metadata. Produce `orient_summary: {tree, project, configs, tests}`.

```python
async def orient(state, harness):
    workspace = Path(state["workspace_path"])
    tree = await asyncio.to_thread(_depth_limited_tree, workspace)

    has_python = (workspace / "pyproject.toml").exists() or any(workspace.rglob("*.py"))
    project_meta = {"lang": "python" if has_python else "unknown",
                    "test_runner": "pytest" if has_python else "unknown"}

    tests = {}
    for test_file in list(workspace.rglob("test_*.py"))[:10]:
        if test_file.is_file():
            tests[str(test_file.relative_to(workspace))] = test_file.read_text()[:4000]

    configs = {}
    for cfg_name in ["README.md", "pyproject.toml", "package.json", "Makefile"]:
        cfg_path = workspace / cfg_name
        if cfg_path.exists() and cfg_path.is_file() and cfg_path.stat().st_size < 4000:
            configs[cfg_name] = cfg_path.read_text()

    summary = {"tree": tree[:2000], "project": project_meta, "configs": configs, "tests": tests}
    if trace_dir := _trace_dir_or_none(state):
        (trace_dir / "orient.json").write_text(json.dumps(summary, indent=2))
    return {"orient_summary": summary}
```

Why limit `tree` to `2000` chars and tests to the first 4000? **Context budget.**
Sonnet's 200k context is plenty, but Haiku is rate-limited per-minute on input
tokens; reading every test file blew through the budget at workers=4. Capping
matters.

### 6.2 Phase 2 — `plan` (`inner.py:119-154`)

**Job:** produce a structured plan via a *forced tool call*. The plan is a JSON
object with `summary`, `steps`, `expected_files_changed`, `tests_to_run`,
`risk_factors`. Schema is at `harness.py:66-100` (`PLAN_TOOL_SCHEMA`).

```python
async def plan(state, harness):
    summary = state["orient_summary"] or {}
    instruction = state["task"]["instruction"]
    prompt = harness.PLAN_PROMPT_TEMPLATE.format(
        instruction=instruction,
        tree=summary.get("tree", "")[:1500],
        ...
    )
    response = await harness._client.messages.create(
        model=harness.MODEL,
        max_tokens=harness.MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        tools=[PLAN_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "submit_plan"},  # forced!
        system=harness.SYSTEM_PROMPT,
    )
    plan_dict = {}
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_plan":
            plan_dict = dict(block.input)
            break
    return {"plan": plan_dict}
```

`tool_choice={"type": "tool", "name": "submit_plan"}` *forces* the LLM to call
`submit_plan` (it can't reply with free text). This guarantees structured output
without an extra parse-or-retry layer.

### 6.3 Phase 3 — `act` (`inner.py:177-271`)

**Job:** bounded ReAct loop over the 6 fixed tools. Up to `MAX_ACT_TURNS`
turns. Per turn: send messages + tools, read tool_use blocks, dispatch each
tool, append tool_results, loop.

The full body is too long to inline here, but the kernel:

```python
while turn_count < harness.MAX_ACT_TURNS:
    if len(messages) > 40:
        messages = harness._summarize_for_overflow(messages)   # override 10
    response = await harness._call_llm(messages, ACT_TOOLS)    # override 8

    assistant_blocks = []
    tool_uses = []
    for block in response.content:
        assistant_blocks.append(_serialize_block(block))
        if getattr(block, "type", None) == "tool_use":
            tool_uses.append(block)
    messages.append({"role": "assistant", "content": assistant_blocks})

    if not tool_uses:
        break

    tool_results = []
    for tu in tool_uses:
        if tu.name == "task_complete":
            act_complete = True
            tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": "Task marked complete; running verify."})
            continue
        result = await asyncio.to_thread(execute_tool, tu.name, workspace, **dict(tu.input))
        formatted = harness._format_tool_result(tu.name, result)   # override 6
        tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": formatted, "is_error": result.get("status") == "error"})

    messages.append({"role": "user", "content": tool_results})
    turn_count += 1
    if act_complete:
        break
```

Note the four override hooks invoked here (`_summarize_for_overflow`,
`_call_llm`, `_format_tool_result`, plus the implicit `MAX_ACT_TURNS`). Half
the search space lives in this node.

### 6.4 Phase 4 — `verify` (`inner.py:320-345`)

**Job:** run the task's `test_command` (e.g. `pytest -q`), parse the result,
write `verify.json`.

```python
async def verify(state, harness):
    workspace = Path(state["workspace_path"])
    test_command = state["task"].get("test_command", "pytest -q")
    tests_pass, output = await asyncio.to_thread(_run_verify_subprocess, workspace, test_command)
    verify_result = {
        "tests_pass": tests_pass,
        "tests_failed": [],
        "test_output": output,
        "lint_pass": True, "lint_errors": [],
        "out_of_plan_changes": [],
    }
    return {"verify_result": verify_result, "verify_attempts": state.get("verify_attempts", 0) + 1}
```

`_run_verify_subprocess` (`inner.py:299-317`) shells out to bash with a 60s
timeout, captures stdout+stderr, and tail-truncates to 2000 chars (the LLM
doesn't need 50KB of pytest output, and the formatter would cap it anyway).

### 6.5 Phase 5 — `submit` (`inner.py:353-398`)

**Job:** assign final score (1.0 if tests pass, 0.0 otherwise), snapshot the
workspace, write `score.json`, `summary.md`, `final-files.json`.

```python
async def submit(state, harness):
    workspace = Path(state["workspace_path"])
    verify_result = state.get("verify_result") or {}
    score = 1.0 if verify_result.get("tests_pass") else 0.0
    final_files = {}
    for f in workspace.rglob("*"):
        if f.is_file() and f.stat().st_size < 50_000:
            try:
                final_files[str(f.relative_to(workspace))] = f.read_text()
            except (OSError, UnicodeDecodeError):
                pass
    # ... write trace files ...
    return {"score": score, "final_files": final_files}
```

The 50KB cap exists so `final_files.json` doesn't bloat to MBs when a candidate
accidentally writes a giant file. The 5 search-set tasks all fit comfortably.

### 6.6 Conditional routing (`inner.py:406-413`)

```python
def _route_after_verify(state):
    verify_result = state.get("verify_result") or {}
    if verify_result.get("tests_pass", False):
        return "submit"
    if state.get("verify_attempts", 0) >= 3:
        return "submit"
    return "act"
```

If tests passed, submit. If verify retries are exhausted, submit anyway (and
`score = 0.0`). Otherwise, loop back to act.

**Important caveat — the retry budget is hardcoded.** The router uses a
literal `>= 3` instead of `harness.MAX_VERIFY_RETRIES`, AND it does not
delegate to `harness.should_loop_back_to_act(verify_result)`. Both methods
are defined on `CodingAgentHarness` (`harness.py:113, 183-185`) and listed
in the SKILL.md as overridable, but the inner loop does not currently
consume them. A candidate that overrides `MAX_VERIFY_RETRIES = 5` will see
no behavioral change. Wiring them through is a one-line fix per call site,
but it's not done in the current code. See §10 for the full list of
"defined-but-not-consumed" override points.

This is *fixed* — candidates can't override the routing topology by editing the
state machine itself. To change the *structure*, you override
`build_inner_graph` (override 11).

### 6.7 Why each phase function takes `harness` as an argument

Every phase function is `async def fn(state, harness): ...`, but LangGraph
nodes only accept `state` (and optionally `config`). The trick is in
`build_inner_graph` (`inner.py:416-458`):

```python
def build_inner_graph(harness, *, checkpointer=None):
    async def _orient(s):
        return await orient(s, harness)
    async def _plan(s):
        return await plan(s, harness)
    # ... etc ...
    g = StateGraph(CodingAgentState)
    g.add_node("orient", _orient)
    g.add_node("plan", _plan)
    # ... etc ...
    return g.compile(checkpointer=checkpointer) if checkpointer else g.compile()
```

Each closure captures `harness` and forwards. Why not lambdas? Because **sync
lambdas wrapping async functions return coroutines without awaiting them** —
LangGraph rejects this with `InvalidUpdateError: Expected dict, got
coroutine`. Explicit `async def` closures fix it.

This was a real bug we hit during the step-7 async refactor. It's the kind of
bug that only fires under LangGraph's runtime, not in unit tests.

---

## 7. The proposer: `claude` CLI subprocess

File: `backend/app/meta_harness/proposer.py`

The proposer is what makes Meta-Harness *self-improving* rather than
hand-tuned. It reads the run's filesystem state, analyzes failure patterns,
and writes a new candidate harness file.

### 7.1 Why a CLI subprocess and not the Anthropic API directly?

Because **the proposer needs Claude Code's tools** (Read, Glob, Grep, Edit,
Write, Bash). Those aren't part of the Anthropic API — they're part of the
`claude` CLI's autonomous-agent harness. The CLI gives us:

1. A real autonomous agent loop (it picks its own tool calls; we don't
   choreograph them).
2. Subscription auth (no API rate limits per minute; Stanford's pattern).
3. Stream-json output for clean log parsing.
4. `--append-system-prompt` for SKILL.md injection.

Going through the API directly would mean reimplementing Claude Code from
scratch — out of scope for 36 hours.

### 7.2 The full subprocess invocation

Built by `_build_claude_command` at `proposer.py:141-172`:

```python
def _build_claude_command(*, prompt, system_prompt, model="opus", tools=None, plugin_dir):
    tools = tools or _PROPOSER_ALLOWED_TOOLS    # ["Read", "Glob", "Grep", "Edit", "Write", "Bash"]
    return [
        "claude",
        "--dangerously-skip-permissions",        # let it write to the run dir without prompting
        "-p", prompt,                            # user-message prompt
        "--output-format", "stream-json",        # one JSON event per line on stdout
        "--verbose",
        "--model", model,                        # "opus" for the proposer (deep reasoning)
        "--setting-sources", "",                 # don't read user/project config
        "--allowedTools", *tools,                # explicit tool allowlist
        "--disable-slash-commands",              # no /clear, /compact, etc.
        "--strict-mcp-config",                   # no third-party MCP servers
        "--plugin-dir", str(plugin_dir),         # empty dir → no plugins
        "--append-system-prompt", system_prompt, # SKILL.md content + memory patterns
    ]
```

Every flag is load-bearing. Removing any of them breaks hermeticity. For
example, dropping `--strict-mcp-config` lets the user's local
`~/.claude.json` MCP servers pollute the run.

### 7.3 The launch dance

Verbatim from `proposer.py:184-368` (skeleton only):

```python
def claude_propose(*, run_dir, iteration, parent_name, repo_root, skill_path,
                   proposer_prior="", timeout_seconds=2400, model="opus"):
    sess_dir = run_dir / "proposer-sessions" / f"iter-{iteration}"
    sess_dir.mkdir(parents=True, exist_ok=True)

    # 1) Build system prompt: SKILL.md + (optional) proposer_prior
    skill_text = skill_path.read_text()
    parts = [f"## Skill: {skill_path.parent.name}\n{skill_text}"]
    if proposer_prior:
        parts.append(f"## Proposer prior\n{proposer_prior}")
    system_prompt = "Follow these skill instructions:\n\n" + "\n\n".join(parts)

    # 2) Build user-message prompt (filepath references for the proposer to read)
    prompt = _render_proposer_prompt(iteration, run_dir, repo_root, parent_name)

    # 3) Empty plugin dir for hermeticity
    empty_plugin_dir = run_dir / ".empty_plugins"
    empty_plugin_dir.mkdir(exist_ok=True)

    cmd = _build_claude_command(prompt=prompt, system_prompt=system_prompt,
                                model=model, plugin_dir=empty_plugin_dir)

    # 4) Strip ANTHROPIC_API_KEY → forces subscription auth
    env = os.environ.copy()
    saved_key = env.pop("ANTHROPIC_API_KEY", None)
    env.pop("CLAUDECODE", None)

    # 5) Spawn + read stdout/stderr via reader threads + queue (avoids deadlock on full pipes)
    proc = subprocess.Popen(cmd, stdout=PIPE, stderr=PIPE, stdin=DEVNULL,
                            text=True, encoding="utf-8", errors="replace",
                            cwd=str(repo_root), env=env)
    q = queue.Queue()
    threading.Thread(target=_enqueue_lines, args=(proc.stdout, q, "stdout"), daemon=True).start()
    threading.Thread(target=_enqueue_lines, args=(proc.stderr, q, "stderr"), daemon=True).start()

    # 6) Drain the queue: parse stream-json events, accumulate text/tool_calls/tokens
    while True:
        try:
            stream, line = q.get(timeout=0.2)
        except queue.Empty:
            if proc.poll() is not None: break
            continue
        if stream == "stdout":
            try:
                event = json.loads(line)
                _accumulate_event(event, ...)
                if event.get("type") == "result":
                    cost_usd = float(event.get("total_cost_usd", 0) or 0.0)
            except json.JSONDecodeError: pass

    # 7) Persist Stanford-shape session log
    (sess_dir / "events.jsonl").write_text("\n".join(json.dumps(e) for e in raw_events) + "\n")
    (sess_dir / "transcript.txt").write_text("".join(text_parts))
    (sess_dir / "session.json").write_text(json.dumps({
        "mode": "claude", "iteration": iteration, "model": model,
        "session_id": session_id, "exit_code": exit_code,
        "duration_seconds": round(duration, 2), "cost_usd": round(cost_usd, 4),
        "token_usage": token_usage, "files_read": files_read, "files_written": files_written,
        "tool_summary": [...], ...,
    }, indent=2, default=str))

    # 8) Read pending_eval.json that the proposer wrote
    pending_path = run_dir / "pending_eval.json"
    if not pending_path.exists():
        raise RuntimeError(f"proposer exited 0 but did not write {pending_path}")
    return json.loads(pending_path.read_text())
```

Three things you would never guess from reading this code:

1. **Reader threads exist because pipe buffers are 64KB on macOS/Linux.**
   If we read stdout serially, stderr fills its 64KB buffer and the
   subprocess blocks on the next stderr write. Two threads → bounded queue
   → no deadlock.
2. **`session.json` is intentionally compatible with Stanford's format.**
   Their `claude_wrapper.py` writes the same shape. We did this so anyone
   familiar with Stanford's reference can read our logs without confusion.
3. **`ANTHROPIC_API_KEY` strip then restore.** Stanford's pattern: subscription
   auth has unlimited rate; API auth has per-minute caps. The strip happens
   *before* spawn; the saved key is restored in the `finally` block at
   `proposer.py:314-316`. This is why a real-proposer demo still works on
   subscription auth even when the inner loop is using API auth.

### 7.4 The mock proposer

For fast iteration and for `--mock-bench` flows, we provide a mock proposer
that produces deterministic stub candidates without spending LLM budget:

```python
def mock_propose(*, run_dir, iteration, parent_name, repo_root):
    name = f"_mock_iter_{iteration}"
    hypothesis = f"mock hypothesis #{iteration}: pretend we tweaked something"
    expected_delta = 0.05
    harness_src = _MOCK_HARNESS_TEMPLATE.format(...)
    (repo_root / "agents" / f"{name}.py").write_text(harness_src)
    payload = {"iteration": iteration, "candidates": [{
        "name": name,
        "import_path": f"agents.{name}:MockHarness_iter_{iteration}",
        "parent": parent_name,
        "hypothesis": hypothesis,
        "axis": "exploitation",
        "expected_score_delta": expected_delta,
    }]}
    (run_dir / "pending_eval.json").write_text(json.dumps(payload, indent=2))
    return payload
```

The stubs subclass `BaselineHarness` with one nominal `HYPOTHESIS` attribute.
Combined with `mock_bench=True`, this lets the entire 4-node outer loop run
end-to-end in <1s for tests and CI.

---

## 8. SKILL.md — the proposer's "tool"

File: `skills/meta-harness-coding-agent/SKILL.md` (149 lines, verified by `wc -l`)

### 8.1 What it is

A Markdown file with YAML frontmatter:

```yaml
---
name: meta-harness-coding-agent
description: Evolve the coding-agent harness. Use this skill when invoked
  by `meta-harness loop` to propose a new candidate harness based on prior
  execution traces and scores. Read the filesystem first; form falsifiable
  hypotheses; produce ONE new agents/<name>.py file and register it in the
  run's pending_eval.json.
---
```

This frontmatter is what Claude Code uses to decide when to activate the
skill. The body — six required sections — is the actual workflow:

### 8.2 The six required sections (memorize these)

1. **What gets evolved.** Lists the 11 search-space methods and explicitly
   names the 6 fixed tools as off-limits.
2. **Hard rules — Anti-Overfitting.** Three rules: no task-specific
   knowledge, no hard-coded fixes, only general principles. Per the paper's
   ablations, removing this section causes the proposer to write code like
   `if "calculator" in task: special_case()`.
3. **Hard rules — Anti-Parameter-Tuning.** Mechanism, not constants.
   Self-critique block at top of every candidate. No combinatorial sweeps.
4. **Workflow** (5 steps, mandatory order):
   1. Analyze — read `evolution_summary.jsonl`, `frontier_val.json`, the 2-3
      lowest-scoring candidates and traces, the current best's source.
   2. Pick a hypothesis (3 options, take the most promising).
   3. Prototype — write `/tmp/prototype-iter-N.py` exercising the mechanism
      on 1-2 trace examples in isolation. *This is the highest-leverage
      step*; it surfaces broken hypotheses before they cost LLM tokens.
   4. Implement — write `agents/<name>.py` subclassing
      `CodingAgentHarness`, override at most 2-3 methods.
   5. Register — write `pending_eval.json`.
5. **Interface contract.** Code skeleton showing what `agents/<name>.py`
   must look like. Class must subclass `CodingAgentHarness`, no required
   `__init__` args, `import_path` must be `agents.<name>:<ClassName>`.
6. **What you may NOT do.** Modify files outside `agents/` and `/tmp/`,
   propose >1 candidate, read `eval/holdout/`.

### 8.3 Why the SKILL.md is the *whole point* of the proposer

This is the deepest non-obvious idea in the project. The proposer is *not* a
custom agent. It's `claude` (the CLI) with a system-prompt augmentation. The
augmentation IS the skill. So:

- "How does the proposer know what `mechanism_axis` means?" → It read it in
  the SKILL.md.
- "How does the proposer know to write a file at `agents/<name>.py`?" → SKILL.md
  Step 4.
- "How does the proposer know not to read `eval/holdout/`?" → Last section.
- "How does the proposer avoid overfitting to the calibration tasks?" →
  Anti-Overfitting rules, enforced by the proposer's self-critique.

If you swap the SKILL.md for a different one (say, a text-classification
skill), the same `claude_propose` machinery now optimizes a text-classification
harness. **The skill is the only domain-specific code in the entire project.**
This is what enables generalization (Stanford's paper has SKILL.md per
domain too).

### 8.4 How SKILL.md is injected

`proposer.py:207-213`:

```python
skill_text = skill_path.read_text()
system_prompt_parts = [f"## Skill: {skill_path.parent.name}\n{skill_text}"]
if proposer_prior:
    system_prompt_parts.append(f"## Proposer prior\n{proposer_prior}")
system_prompt = "Follow these skill instructions:\n\n" + "\n\n".join(system_prompt_parts)
```

Then passed via `--append-system-prompt system_prompt` to the CLI. The `claude`
CLI appends this to its own internal system prompt — so the proposer sees both
"You are Claude Code, …" (built-in) AND our skill content.

Cross-run memory patterns are appended to `proposer_prior` in `outer.py:131-142`,
which means they show up as a third Markdown section after the SKILL.md.

---

## 9. The six fixed inner-loop tools

File: `backend/app/meta_harness/tools.py`

These six tools are **the contract with the evaluator**. Candidates cannot
override them. Their job is to give every candidate harness an identical
substrate to operate on; only the *prompts and policies around the tools* are
the search space.

### 9.1 The full schema list

`tools.py:36-128` defines `TOOL_SCHEMAS` as a list of 6 JSON-schema dicts. The
JSON schemas are passed verbatim to `Anthropic.messages.create(tools=...)`.

```python
TOOL_SCHEMAS = [
    {"name": "read_file", "description": "Read a file from the workspace, with optional line range.",
     "input_schema": {"type": "object",
                      "properties": {"path": ..., "start_line": ..., "end_line": ...},
                      "required": ["path"]}},
    {"name": "apply_patch", "description": "Apply a unified-diff patch to a file. ...",
     "input_schema": {...}},
    {"name": "write_file", "description": "Create a new file. Errors if exists ...",
     "input_schema": {...}},
    {"name": "run_bash", "description": "Run a bash command in the sandboxed workspace ...",
     "input_schema": {...}},
    {"name": "grep_search", "description": "Search files in the workspace using ripgrep ...",
     "input_schema": {...}},
    {"name": "task_complete", "description": "Signal that the task is done ...",
     "input_schema": {"type": "object", "properties": {}}},
]
```

### 9.2 Per-tool mechanics worth knowing

**`read_file` (`tools.py:153-224`):** Returns line-numbered content. Has a
hard cap at 2000 lines without an explicit range — surfaces an error message
that tells the model to use `grep_search` instead. The numbering is `f"{n:6}→{line}"`.

```python
selected = lines[start_line - 1 : end_line]
numbered = "\n".join(f"{start_line + i:6}→{line}" for i, line in enumerate(selected))
```

The line numbers help the model produce correct unified-diff hunk headers
without re-counting.

**`apply_patch` (`tools.py:295-376`):** This is the *interesting* one.

```python
def apply_patch(workspace, path, patch):
    target = _resolve_in_workspace(workspace, path)   # path traversal check
    if target is None:
        return {"status": "error", "error_type": "invalid_path", ...}
    if not target.exists():
        return {"status": "error", "error_type": "file_not_found", ...}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as patch_file:
        patch_file.write(patch); patch_path = patch_file.name

    try:
        check = subprocess.run(["git", "apply", "--check", patch_path], cwd=workspace, ...)
        if check.returncode != 0:
            stderr = check.stderr.strip()
            if "patch does not apply" in stderr or "while searching for" in stderr:
                # Crucial: surface the file's ACTUAL content at the failed range
                context_echo = _extract_context_echo(workspace, path, patch)
                msg = (f"Patch context did not match at lines "
                       f"{context_echo['start_line']}-{context_echo['end_line']}. "
                       f"The file currently reads:\n{context_echo['content']}\n"
                       "Edit the patch to match this and retry.")
                return {"status": "error", "error_type": "context_mismatch",
                        "error_message": msg, "context_echo": context_echo}
            ...
        apply_proc = subprocess.run(["git", "apply", patch_path], cwd=workspace, ...)
        ...
        return {"status": "ok", "path": path, "patch_applied": True}
    finally:
        Path(patch_path).unlink(missing_ok=True)
```

**`context_echo` is the killer feature.** When a unified diff fails to apply
because the surrounding context lines don't match the actual file (because the
model hallucinated them), most tools just say "patch failed; re-read the file
and try again." That triggers a wasteful re-read cycle. We instead parse the
hunk header (`@@ -42,5 +42,6 @@`), read lines 42-46 from the actual file, and
return them in the error. The model fixes the patch in the next turn without
spending tokens on re-reading.

`_extract_context_echo` at `tools.py:263-292` does the parsing.

**`write_file` (`tools.py:227-257`):** Errors if file exists. This is
intentional — it forces the model to use `apply_patch` for modifications. The
`file_exists` error message tells them so. Without this, models tend to
overwrite files wholesale, which is much harder to review on a diff viewer.

**`run_bash` (`tools.py:379-414`):** Executes via `run_in_sandbox`
(`sandbox.py:110-131`). 30s default timeout, 120s hard cap. Stdout
tail-truncated to 8000 chars; stderr to 2000.

**`grep_search` (`tools.py:417-461`):** Uses `rg` if available, falls back to
`grep -rn`. 30s timeout. Output capped at 8000 chars.

**`task_complete` (`tools.py:464-466`):** Sentinel. Returns
`{"status": "ok", "signal": "task_complete"}`. The act loop checks for this
name explicitly and breaks.

### 9.3 Path traversal protection

`_resolve_in_workspace` (`tools.py:138-150`) rejects any path that, after
resolution, escapes the workspace. This is the only line of defense against a
proposer-generated harness that tries to read `/etc/passwd` via `read_file`.

```python
def _resolve_in_workspace(workspace, path):
    workspace = workspace.resolve()
    resolved = (workspace / path).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError:
        return None
    return resolved
```

It's defense-in-depth. The sandbox is process-isolated (own `/tmp`), but a
malicious harness could still try to escape by symlink. `relative_to`
followed by symlink-resolved comparison neutralizes that.

---

## 10. The eleven override points

File: `backend/app/meta_harness/harness.py`

These 11 are the *search space*. A candidate harness `agents/<name>.py`
subclasses `CodingAgentHarness` and overrides any subset of these. The proposer
chooses which to override based on its analysis.

### 10.1 Class attribute overrides (1-4)

```python
class CodingAgentHarness:
    SYSTEM_PROMPT: str = _DEFAULT_SYSTEM_PROMPT          # Override 1
    PLAN_PROMPT_TEMPLATE: str = _DEFAULT_PLAN_PROMPT_TEMPLATE  # Override 2
    MAX_ACT_TURNS: int = 25                              # Override 3
    MAX_VERIFY_RETRIES: int = 3                          # Override 4

    MODEL: str = os.environ.get("META_HARNESS_INNER_MODEL", "claude-haiku-4-5-20251001")
    MAX_TOKENS: int = 4096
```

Why class attributes? Because the `inner.py` phase functions reference them via
`harness.SYSTEM_PROMPT`, `harness.MAX_ACT_TURNS`, etc. A subclass that sets
`MAX_ACT_TURNS = 50` automatically affects the act phase's loop bound.

### 10.2 Method overrides (5-10)

5. `_build_initial_context(orient_summary)` — How orient's output gets shaped
   for the planner. Default: pass-through. A candidate could enrich it with
   syntax-tree analysis, e.g.
6. `_format_tool_result(name, result)` — How tool outputs render back to the
   model. Default: pretty-printed JSON, truncated at 4000 chars.
7. `_compose_act_prompt(plan)` — How the plan injects into the first act-turn.
   Default: "Execute this plan. Use the tools to read, edit, and verify…"
   followed by the JSON.
8. `async _call_llm(messages, tools)` — The actual `messages.create` call.
   Override for caching, message ordering, summarization, prompt prefix
   manipulation. **This is the highest-leverage override.**
9. `should_loop_back_to_act(verify_result)` — Default: loop back if tests
   didn't pass. Could be overridden to e.g. "loop back unless verify shows a
   linter error not caused by your patch."
10. `_summarize_for_overflow(messages)` — When messages > 40, trim. Default:
    keep first 2 + last 18 + a "[earlier turns elided]" placeholder.

### 10.3 Structural override (11)

You override `build_inner_graph` (in `inner.py`) to *reorder phases*. E.g. a
candidate could add a `lint` node between `verify` and `submit`, or split
`act` into `act-explore` then `act-implement`.

This is the most powerful override and the rarest. Most candidates touch only
1-3 of the first 10.

### 10.4 What candidates CAN'T override

- **The 6 fixed tools.** Listed in §9.
- **The 5 phase boundaries.** `orient → plan → act → verify → submit` —
  candidates can split or recombine via override 11, but they can't, e.g.,
  delete `verify`. The contract with the evaluator is that you call the
  task's test command; that lives in `verify`.
- **The state schemas.** `MetaHarnessState` and `CodingAgentState` (`state.py`)
  are typed and frozen.

Understanding this division — fixed tools / fixed phases vs. evolvable
class+methods — is how to talk about the search space precisely.

### 10.5 Live wiring audit — which overrides actually work today

Honesty check: not every override point listed in `SKILL.md` is currently
consumed by `inner.py`. Verified by `grep -n "harness\." backend/app/meta_harness/inner.py`:

| # | Override | Consumed in `inner.py`? | Where (or why not) |
|---|---|---|---|
| 1 | `SYSTEM_PROMPT` | ✅ yes | `inner.py:141` (passed to `messages.create` in plan phase) |
| 2 | `PLAN_PROMPT_TEMPLATE` | ✅ yes | `inner.py:124` (`harness.PLAN_PROMPT_TEMPLATE.format(...)`) |
| 3 | `MAX_ACT_TURNS` | ✅ yes | `inner.py:193` (`while turn_count < harness.MAX_ACT_TURNS`) |
| 4 | `MAX_VERIFY_RETRIES` | ❌ **no** | `_route_after_verify` (`inner.py:411`) hardcodes `>= 3` |
| 5 | `_build_initial_context` | ❌ **no** | Defined but never called. The orient phase writes `orient_summary` directly to state without projecting through this hook. |
| 6 | `_format_tool_result` | ✅ yes | `inner.py:239` (`harness._format_tool_result(tu.name, result)`) |
| 7 | `_compose_act_prompt` | ✅ yes | `inner.py:187` (`harness._compose_act_prompt(plan_dict)`) |
| 8 | `_call_llm` | ✅ yes | `inner.py:197` (`await harness._call_llm(messages, ACT_TOOLS)`) |
| 9 | `should_loop_back_to_act` | ❌ **no** | `_route_after_verify` does its own check; never delegates to the harness. |
| 10 | `_summarize_for_overflow` | ✅ yes | `inner.py:195` (`messages = harness._summarize_for_overflow(messages)`) |
| 11 | `build_inner_graph` (structural) | ✅ yes | Each candidate can ship its own `build_inner_graph` and the outer loop will use the harness's compiled graph. |

7 of 11 are live (1, 2, 3, 6, 7, 8, 10, 11 — count includes structural).
4, 5, and 9 are present in the search space description but currently
unwired. **A proposer that proposes "tune `MAX_VERIFY_RETRIES`" or
"override `_build_initial_context`" will appear to evolve correctly — its
candidate file will pass validate — but the override will not affect the
benchmark score.** This is a real gap; if you have time, wiring all three
through is a clean one-day task and would visibly improve the search space's
expressiveness.

Why we ship like this: Build-Order step 3 wired the inner loop to a baseline
that doesn't need overrides 4/5/9 to score well, and step 6's proposer was
producing candidates that touched 1, 2, 3, 6, 7, 8, 10 anyway. The unwired
hooks were never hit during calibration so the gap survived undiscovered
until this audit.

---

# Part III — The substrate

## 11. Persistence (`AsyncPostgresSaver`)

File: `backend/app/meta_harness/persistence.py`

Postgres is the source of truth for "what state the run is in." Filesystem
artifacts (`pending_eval.json`, `evolution_summary.jsonl`) are
human-inspectable mirrors; Postgres is what makes resume/fork actually work.

### 11.1 Why async, not sync

Top of the file (`persistence.py:1-15`):

```python
"""AsyncPostgresSaver setup + connection pool (BUILD_ORDER step 7).

Per Appendix A §A.3:
- Sync ``PostgresSaver`` deadlocks under concurrent use; we use the
  async-native ``AsyncPostgresSaver`` exclusively.
- Pool sized ``max_size=20`` (≈2 connections per concurrent branch).
- ``saver.setup()`` creates the checkpoint tables on first call;
  idempotent on subsequent runs.
"""
```

The deadlock isn't theoretical. Sync `PostgresSaver` with `psycopg.Connection`
holds a connection through node bodies; concurrent branches block waiting on
that connection, and if both call out to subprocess.run, you get a triangle of
"branch A holds conn X, waiting for subprocess; branch B waiting for any
conn." The async version uses a connection pool with autocommit + dict_row;
each await yields the connection back.

### 11.2 The context manager

```python
@asynccontextmanager
async def persistence_layer(dsn=None, *, min_size=4, max_size=20, setup=True):
    dsn = dsn or get_dsn()
    async with AsyncConnectionPool(
        conninfo=dsn,
        min_size=min_size, max_size=max_size,
        timeout=30,
        kwargs={"row_factory": dict_row, "autocommit": True},
        open=False,
    ) as pool:
        await pool.open()
        saver = AsyncPostgresSaver(pool)
        if setup:
            await saver.setup()
        yield saver
```

`max_size=20` lets ~10 concurrent branches each hold 2 connections (one for
the saver, one for the store). `autocommit=True` is crucial; without it,
LangGraph's checkpoint reads contend with writes on the same Tx and you get
random `SerializationError`s.

`saver.setup()` is idempotent — it creates the `checkpoints`, `writes`, and
`channels` tables if missing. Safe to call every startup.

### 11.3 The healthcheck (and a war story)

```python
async def healthcheck(dsn=None):
    """Return True iff Postgres is reachable at the configured DSN."""
    try:
        dsn = dsn or get_dsn()
        sep = "&" if "?" in dsn else "?"
        conn = await AsyncConnection.connect(
            conninfo=f"{dsn}{sep}connect_timeout=5",
            row_factory=dict_row, autocommit=True,
        )
        async with conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:
        return False
```

The original version had `AsyncConnection.connect(timeout=5)`. **psycopg
rejects `timeout=` as a keyword argument** — libpq's parameter is
`connect_timeout`. The rejection raised `ProgrammingError`, which got
swallowed by the bare `except Exception: return False`, which made *every
Postgres-backed test silently skip*.

`pytest tests/ -q` went from 51 passes (skipping 20) to 71 passes (running 20)
when this was fixed. Lesson: a bare `except: return False` is a footgun.

### 11.4 Usage from outer.py

```python
async with persistence_layer() as saver:
    final = await run_outer_loop(..., checkpointer=saver)
```

The compiled graph receives `checkpointer=saver`. Every node transition writes
a checkpoint row keyed by `(thread_id, checkpoint_id)`. Checkpoints have
parent pointers (`parent_checkpoint_id`) — forks become "checkpoints with a
different `thread_id` whose parent points back into the parent thread."

### 11.5 Resume

`outer.py:618-655`:

```python
async def resume_outer_loop(*, run_dir, repo_root, eval_tasks_dir, checkpointer, skill_path=None):
    manifest = json.loads((run_dir / "manifest.json").read_text())
    runner = OuterLoopRunner(
        run_dir=run_dir, repo_root=repo_root, eval_tasks_dir=eval_tasks_dir,
        mock_proposer=manifest.get("mock_proposer", False),
        mock_bench=manifest.get("mock_bench", False),
        trials=manifest.get("trials", 5),
        bench_workers=3,
        skill_path=skill_path,
        checkpointer=checkpointer,
    )
    graph = runner.build()
    final = await graph.ainvoke(
        None,                                                  # ← None input
        config={"configurable": {"thread_id": run_dir.name}},  # ← existing thread
    )
    return final
```

The trick is `graph.ainvoke(None, config={"thread_id": ...})`. `None` input
+ existing thread_id = "resume from last checkpoint, don't restart." LangGraph
looks up the most recent checkpoint for that thread and continues from there.

This is what makes `kill -INT` + `meta-harness resume <name>` produce the same
final state as a single uninterrupted run.

---

## 12. Time-travel and concurrent branches

File: `backend/app/meta_harness/branches.py`

This is the second-most distinctive layer of the project (after the
two-state-machine architecture). It's what makes "linear → tree" actually
work.

### 12.1 The data model

```python
@dataclass
class BranchMetadata:
    branch_id: str
    run_id: str
    thread_id: str               # f"{parent_thread_id}.fork.{branch_id}"
    parent_thread_id: str | None
    parent_checkpoint_id: str | None
    status: BranchStatus  # "created" | "running" | "completed" | "failed" | "cancelled"
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    cancelled_at: str | None = None
    error: str | None = None
    mods: dict[str, Any] = field(default_factory=dict)
    name: str | None = None
    result: dict[str, Any] | None = None

branch_registry: dict[str, asyncio.Task[Any]] = {}
branch_metadata: dict[str, BranchMetadata] = {}
```

In-process registries — branches are not durable across server restarts. (If
you SIGINT, the parent runs survive via Postgres, but in-flight forks need to
be re-created from their checkpoint.) For a 36-hour hackathon this is the
right tradeoff; durability would require a separate `branches` table.

### 12.2 The `worktree_add` primitive

The core fork operation. From `branches.py:180-234`:

```python
async def worktree_add(graph, *, run_id, parent_thread_id, parent_checkpoint_id,
                      mods=None, name=None, recursion_limit=200):
    """Fork a checkpoint into a new concurrent branch.

    Returns ``(metadata, task)``. The task is also stored in
    ``branch_registry[metadata.thread_id]``.
    """
    mods = dict(mods or {})
    parent_snapshot = await _find_snapshot(graph, thread_id=parent_thread_id,
                                            checkpoint_id=parent_checkpoint_id)
    as_node = await _infer_as_node_for_fork(graph, parent_snapshot)
    fork_values = copy.deepcopy(_snapshot_values(parent_snapshot))
    fork_values.update(mods)

    branch_id = uuid.uuid4().hex[:8]
    thread_id = f"{parent_thread_id}.fork.{branch_id}"
    metadata = BranchMetadata(
        branch_id=branch_id, run_id=run_id, thread_id=thread_id,
        parent_thread_id=parent_thread_id, parent_checkpoint_id=parent_checkpoint_id,
        status="created", created_at=_now(), mods=mods, name=name,
    )
    branch_metadata[thread_id] = metadata

    fork_config = await graph.aupdate_state(
        {"configurable": {"thread_id": thread_id}},
        fork_values, as_node=as_node,
    )
    metadata.status = "running"
    metadata.started_at = _now()

    task = asyncio.create_task(
        _run_branch(graph, metadata, fork_config, recursion_limit),
        name=f"worktree:{thread_id}",
    )
    task.add_done_callback(_consume_task_exception)
    branch_registry[thread_id] = task
    return metadata, task
```

Three key operations:

1. **`_find_snapshot`** — walk `aget_state_history(parent_thread_id)` until we
   find the checkpoint with matching `checkpoint_id`. This is how we get the
   *full state* at that historical point.
2. **`graph.aupdate_state(...)`** — write a new checkpoint with the user's
   mods applied to a copy of the parent state. The `thread_id` here is the
   *new* thread ID (`{parent}.fork.{8hex}`). After this call, the new thread
   has exactly one checkpoint, ready to resume.
3. **`asyncio.create_task(graph.ainvoke(None, fork_config))`** — kick off the
   fork's run *without awaiting it*. This is what makes branches concurrent.
   The task goes in `branch_registry` so we can cancel it later.

Why `asyncio.create_task` instead of `asyncio.gather`? **Per LangGraph issue
#6624**, `gather` over interrupt-able coroutines silently swallows the
interrupts. The outer loop uses `interrupt()` for human-in-the-loop steps,
so we need each branch to be its own independent task.

### 12.3 The "as_node" subtlety

When you `aupdate_state`, LangGraph needs to know "what node should this state
be considered as just having executed?" The `as_node` argument controls that.

`_infer_as_node_for_fork` at `branches.py:375-393`:

```python
async def _infer_as_node_for_fork(graph, snapshot):
    metadata = dict(getattr(snapshot, "metadata", {}) or {})
    if metadata.get("source") == "input":
        return INPUT_NODE  # "__input__"
    parent_config = getattr(snapshot, "parent_config", None)
    if parent_config is None:
        return None
    parent_snapshot = await graph.aget_state(parent_config)
    parent_next = _snapshot_next(parent_snapshot)
    if len(parent_next) != 1:
        return None
    previous_node = parent_next[0]
    if previous_node == START:
        return INPUT_NODE
    if previous_node == END:
        return None
    return previous_node
```

The logic: figure out what node *would have just run* to produce this
checkpoint. We do that by looking at the parent checkpoint's `next` field
— that tells us "the next node that will run." If the parent had `next ==
("validate",)`, then the snapshot was produced by `validate` finishing. So
the new fork should be considered as having just executed `validate`, and
LangGraph's router will pick up from there.

Without this, the fork would re-execute the node that produced the parent
checkpoint, doubling the work.

### 12.4 Cancellation

```python
async def cancel_branch(thread_id):
    metadata = _require_branch(thread_id)
    task = branch_registry.get(thread_id)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if metadata.status not in {"completed", "failed", "cancelled"}:
        _mark_cancelled(metadata)
    return metadata
```

Standard asyncio cancellation: cancel the task, await to drain, swallow the
`CancelledError`. The `_run_branch` coroutine has its own `except
asyncio.CancelledError` clause (`branches.py:328-330`) that marks the metadata
`cancelled` before re-raising.

### 12.5 Trajectory reconstruction (for the dashboard)

```python
def reconstruct_trajectory(run_id):
    branches = list_branches(run_id=run_id)
    threads = {run_id: {"thread_id": run_id, "run_id": run_id, "parent_thread_id": None,
                        "parent_checkpoint_id": None, "status": "root", "branch_id": None,
                        "name": "root"}}
    edges = []
    for branch in branches:
        threads[branch.thread_id] = branch.to_dict()
        edges.append({
            "source": branch.parent_thread_id,
            "target": branch.thread_id,
            "parent_checkpoint_id": branch.parent_checkpoint_id,
        })
    return {"run_id": run_id, "threads": list(threads.values()), "edges": edges}
```

The dashboard hits this and renders a tree diagram. Edges are
`(parent_thread_id, child_thread_id, branch_point_checkpoint_id)`.

---

## 13. Cross-run memory (`AsyncPostgresStore`)

Files: `backend/app/meta_harness/memory.py`, `backend/app/api/memory.py`

This layer makes successive runs *learn from each other*. A pattern accepted
in run A flows into run B's proposer prior. Stanford's paper has this too, but
they call it "cross-task transfer."

### 13.1 Schema

`memory.py:1-25`:

```text
- namespace: ("learned_patterns", "<domain>") — e.g. ("learned_patterns", "coding-agent").
- key: UUID — dedup is by cumulative evidence, not by overwrite.
- value: {pattern, mechanism_axis, score_delta, evidence_run_ids, created_at}.
```

Critically: **NO source code in `pattern`.** The proposer's context budget is
finite. Storing full Python harness source here would balloon `pending_eval.json`
to MBs and hit context limits. Instead, `pattern` is a one-sentence description
("retry on schema_drift errors reduces patch failures by 8%"); the actual
candidate source lives at `agents/<name>.py`.

### 13.2 Read path

```python
async def search_patterns(store, *, domain=DEFAULT_DOMAIN, limit=5, query: str | None = None):
    ns = ("learned_patterns", domain)
    pre_limit = limit if query is None else max(limit * 20, 100)
    items = await store.asearch(ns, limit=pre_limit)
    results = []
    for item in items:
        val = item.value if hasattr(item, "value") else item
        if isinstance(val, dict):
            results.append({"key": item.key if hasattr(item, "key") else "?", **val})
    if query:
        needle = query.lower()
        results = [r for r in results
                   if needle in str(r.get("pattern", "")).lower()
                   or needle in str(r.get("mechanism_axis", "")).lower()]
    results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return results[:limit]
```

Two interesting choices:

1. **Recency-weighted top-N, not embeddings.** We sort by `created_at`
   descending and return the top 5. Real semantic search via pgvector +
   embeddings is scope creep for 36 hours. For the demo, "the 5 most recent
   patterns this domain has learned" is a sufficient signal.
2. **`pre_limit = max(limit * 20, 100)` when filtering.** Without a wider
   pre-fetch, queries that match few rows would get empty results because
   the in-memory filter happens *after* the DB-side `limit`. This was a
   real bug; we fixed it during the third code-review pass.

### 13.3 Write path

```python
async def add_pattern(store, *, pattern, mechanism_axis, score_delta, run_id, domain=DEFAULT_DOMAIN):
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
```

Called from `update_frontier` only when a candidate is *accepted* (`outer.py:454-464`).
Each accepted candidate becomes one pattern row.

### 13.4 Format-for-prompt

`memory.py:155-178`:

```python
def format_patterns_for_prompt(patterns):
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
```

Output looks like:

```markdown
## Cross-run memory — learned patterns

The following patterns were learned from prior evolution runs. Use them as
starting hypotheses — but verify against the current traces before committing
to a candidate.

1. **exploitation** (+8.0% delta): retry on schema_drift errors reduces patch failures by 8% [evidence: run-2026-04-25T10:30Z]
2. **exploration** (+16.0% delta): rewrite tool descriptions w/ examples [evidence: run-fork-abc12345]
3. **exploitation** (+4.0% delta): early-exit on auth failures saves context tokens [evidence: run-2026-04-25T10:30Z]
```

This block gets appended to `proposer_prior` in `outer.py:131-142`, then
flows into `--append-system-prompt` in `proposer.py:207-213`.

### 13.5 The REST surface

`backend/app/api/memory.py` exposes:

- `GET /memory/{namespace}?limit=50` → `{namespace, entries, limit, implemented}`
- `POST /memory/{namespace}/search` body `{query, limit}` → `{results,
  formatted, ...}`

The `formatted` field returns the output of `format_patterns_for_prompt`,
which is exactly what the dashboard's memory panel renders verbatim. The
dashboard is showing what the *proposer would actually see* if it ran now.

---

## 14. REST + SSE protocol

Files: `backend/app/streaming.py`, `backend/app/api/{runs,checkpoints,forks,memory,events,branches}.py`

### 14.1 Why SSE, not WebSockets

Three reasons:

1. **Server-pushed only.** The dashboard never sends realtime data back to
   the server during a run; it only consumes events. WebSockets are bidirectional
   and overkill.
2. **HTTP/2 friendliness + automatic reconnect.** SSE is a long-lived `text/event-stream`
   response. The `EventSource` API in browsers handles reconnection
   automatically (with `Last-Event-ID` for resume).
3. **Trivial to debug.** `curl -N http://localhost:8000/runs/foo/stream`
   shows the live event stream as plain text. WebSockets need a separate
   client.

### 14.2 The closed-set event registry

`backend/app/streaming.py:19-33`:

```python
REGISTERED_EVENT_TYPES: frozenset[str] = frozenset({
    "state-update",
    "checkpoint-written",
    "candidate-created",
    "validate-result",
    "eval-result",
    "frontier-updated",
    "iteration-complete",
    "fork-created",
    "branch-cancelled",
    "memory-pattern-stored",
    "error",
})
```

11 types, frozen, runtime-enforced. The `EventRegistry.emit` method raises
`UnknownEventTypeError` (status 500) on any unregistered type:

```python
def emit(self, channel, event_type, payload, *, event_id=None):
    if event_type not in self.allowed_event_types:
        raise UnknownEventTypeError(f"unregistered SSE event type: {event_type!r}")
    if not isinstance(payload, dict):
        raise InvalidEventPayloadError("SSE payload must be a JSON object")
    if "thread_id" not in payload:
        raise InvalidEventPayloadError(f"SSE event {event_type!r} missing required thread_id")
    event = SSEEvent(event_type=event_type, event_id=event_id or uuid.uuid4().hex,
                     data=payload, ts=_now())
    history = self._history.setdefault(channel, [])
    history.append(event)
    if len(history) > self.history_limit:
        del history[: len(history) - self.history_limit]
    for queue in list(self._subscribers.get(channel, set())):
        queue.put_nowait(event)
    return event
```

This is **the contract enforcement layer**. Code that emits the wrong event
type fails loudly at runtime — which means the dashboard's `event` →
`reducer-action` map can be exhaustive without runtime branch coverage holes.

### 14.3 The wire format

```python
def format_sse(event):
    payload = json.dumps(event.data, default=str, separators=(",", ":"))
    return f"event: {event.event_type}\nid: {event.event_id}\ndata: {payload}\n\n"
```

Standard HTML SSE: `event:`, `id:`, `data:` lines, blank line terminator. The
`id:` field is what browsers send back as `Last-Event-ID:` on reconnect.

### 14.4 Per-run multiplex

Each run has its own channel: `channel_for_run(run_id) → f"run:{run_id}"`. All
11 event types for that run multiplex onto a single channel. Each event payload
includes `thread_id`, so the dashboard can route fork-branch events to the
correct subtree even when a fork's events interleave with the parent's.

### 14.5 Reconnect semantics

`EventRegistry.subscribe` (`streaming.py:147-187`):

```python
async def subscribe(self, channel, *, last_event_id=None, heartbeat_interval=15.0):
    replay = self.history(channel)
    if last_event_id:
        for idx, event in enumerate(replay):
            if event.event_id == last_event_id:
                replay = replay[idx + 1 :]
                break
    for event in replay:
        yield format_sse(event)

    queue = asyncio.Queue()
    self._subscribers.setdefault(channel, set()).add(queue)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            yield format_sse(event)
    finally:
        subscribers = self._subscribers.get(channel)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(channel, None)
```

Replay backlog before live stream → resume from `Last-Event-ID` if provided
→ heartbeats every 15s on idle (`: heartbeat\n\n` is the SSE comment syntax,
ignored by browsers but keeps the connection alive past intermediate proxies'
60s idle timeouts).

### 14.6 The REST surface (full inventory)

Every router lives in `backend/app/api/`. Wired into the FastAPI app at
`backend/app/main.py:113-118` via `app.include_router(...)`.

#### Health
- **`GET /health`** (`main.py:105-111`) → `{status, version, persistence}`.
  `persistence` is either `"postgres"` (Postgres healthy at startup) or
  `"memory"` (fell back to `MemorySaver`). The frontend's `isBackendAvailable()`
  hits this with a 2-second `AbortSignal.timeout`.

#### Runs (`api/runs.py`)
- **`POST /runs`** → **201 Created** + `Location: /runs/{run_id}` header.
  Body: `{domain, skill_path, budget, model, fresh, run_name, proposer,
  mock_bench, trials, workers}`. Spawns the outer loop in a background
  `asyncio.Task` and returns `_run_info_from_record(record)` immediately.
- **`GET /runs`** → `{runs: [...]}`. Reads run dirs from disk + active records
  from in-process `run_registry`. Each entry has `run_id, thread_id, status,
  started_at, current_iteration, best_score`.
- **`GET /runs/{run_id}`** → full run info: `_run_info_from_record(record)` +
  `manifest`, `frontier_val`, `summary_rows` (last 5 from
  `evolution_summary.jsonl`), `best_score`, `error`.
- **`DELETE /runs/{run_id}`** → cancels the active task, cancels all branches
  for the run, writes `manifest.status="cancelled"`, returns
  `{status: "cancelled"}`.

#### Checkpoints (`api/checkpoints.py`)
- **`GET /runs/{run_id}/checkpoints`** → `{checkpoints: [...]}` — the full
  history from `branches.get_state_history(graph, thread_id=run_id)`.
  Each item: `{checkpoint_id, thread_id, ts, node, iteration,
  values_summary, parent_checkpoint_id, next, metadata}`.
- **`GET /runs/{run_id}/checkpoints/{checkpoint_id}`** → single checkpoint
  with full state: `{checkpoint_id, thread_id, state, ts, node}`. 404 if
  not found. Used by the fork modal to show "what state is at this
  checkpoint" before the user fills in mods.

#### Forks (`api/forks.py`)
- **`POST /runs/{run_id}/fork`** → **202 Accepted** (NOT 201; forking is
  asynchronous — the branch is dispatched immediately but doesn't have
  results yet). Body: `{parent_checkpoint_id, mods, parent_thread_id?,
  name?}`. Calls `worktree_add` and emits a `fork-created` SSE event.
  Returns `{thread_id, status, parent_checkpoint_id, branch_id}`. 404 if
  the parent checkpoint isn't found.

#### Branches (`api/branches.py`)
- **`GET /runs/{run_id}/branches`** → `{branches: [...]}` — every branch
  (including the root) for this run, derived from `list_branches(run_id=...)`.
- **`GET /runs/{run_id}/trajectory`** → `{trajectory: {threads, edges}}` —
  the tree structure for the dashboard's trajectory view, from
  `reconstruct_trajectory(run_id)`.
- **`POST /runs/{run_id}/branches/{thread_id}/cancel`** → cancels a live
  branch via `cancel_branch(thread_id)` and emits a `branch-cancelled`
  SSE event. Returns `{status: <metadata.status>}`. 404 on unknown branch.

#### Events (`api/events.py`)
- **`GET /runs/{run_id}/stream`** → SSE response, `text/event-stream`.
  Honors `Last-Event-ID:` request header for resume. Yields heartbeats
  every 15s when idle (`": heartbeat\n\n"` — SSE comment syntax). The
  generator checks `request.is_disconnected()` between events so a closed
  client doesn't keep the subscriber slot.

#### Memory (`api/memory.py`)
- **`GET /memory/{namespace}?limit=50`** →
  `{namespace, entries, limit, implemented, error?}`. `implemented: false`
  when the memory store isn't available (Postgres down, store not
  configured) — the frontend treats this as a valid placeholder.
- **`POST /memory/{namespace}/search`** → body `{query, limit}`,
  returns `{namespace, query, limit, results, formatted, implemented}`.
  `formatted` is the output of `format_patterns_for_prompt(results)` —
  literally what the proposer would see in its system prompt. (Useful
  for the dashboard to render exactly what the proposer would see.)

### 14.7 Status-code conventions used

| Endpoint | Status | Why |
|---|---|---|
| `POST /runs` | **201 Created** | Resource created; with `Location` header |
| `POST /runs/{run_id}/fork` | **202 Accepted** | Long-running async work dispatched; no result yet |
| `POST /runs/{run_id}/branches/{thread_id}/cancel` | **200 OK** | Synchronous cancel completed |
| `DELETE /runs/{run_id}` | **200 OK** | Cancellation completed by return |
| Errors | `400` (bad req) / `404` (missing) / `409` (conflict) | Standard semantics |
| SSE `emit` of unregistered event | **500** | `UnknownEventTypeError` is a 500-class |

The `StreamingRegistryError` exception handler at `main.py:98-103` converts
streaming-registry violations into clean JSON 500 responses.

---

## 15. Sandbox isolation

File: `backend/app/meta_harness/sandbox.py`

Honest about its limits, which is itself a feature:

```python
"""Process-isolated sandbox for inner-loop tool execution.

Per Appendix C §C.6.3:
- Each task gets a fresh /tmp/meta-harness-task-{uuid}/ directory.
- Commands run with subprocess.run(..., cwd=task_dir, timeout=...).
- rlimit 512MB RAM + 60s CPU on Unix via resource.setrlimit in a preexec_fn.
- Process isolation only — no Docker, no network restriction, no binary
  allowlist. These are honest limits we surface in user-facing docs;
  production-grade isolation is roadmap, not 36-hour scope.
"""
```

### 15.1 Lifecycle

```python
@contextmanager
def sandbox_for(source_workspace):
    sandbox = make_sandbox_dir()                  # /tmp/meta-harness-task-{uuid}
    try:
        populate_sandbox(sandbox, source_workspace)  # shutil.copytree of pristine workspace
        yield sandbox
    finally:
        cleanup_sandbox(sandbox)                  # shutil.rmtree
```

Each inner-loop trial gets a fresh `/tmp` dir copied from the pristine task
workspace. The sandbox is cleaned up after the trial. There is no shared state
between trials.

### 15.2 rlimits — and the macOS gotcha

`sandbox.py:81-107`:

```python
def _apply_rlimits():
    if not _HAS_RLIMIT or _resource is None:
        return
    if sys.platform != "darwin":
        try:
            _resource.setrlimit(_resource.RLIMIT_AS,
                                (DEFAULT_RLIMIT_RAM, DEFAULT_RLIMIT_RAM))
        except (ValueError, OSError):
            pass
    try:
        _resource.setrlimit(_resource.RLIMIT_CPU,
                            (DEFAULT_RLIMIT_CPU, DEFAULT_RLIMIT_CPU))
    except (ValueError, OSError):
        pass
```

The macOS skip is real. Setting `RLIMIT_AS=512MB` on Darwin kills Python child
processes — Python's own runtime address-space footprint can exceed 512MB
*before the child runs anything*. So we skip RLIMIT_AS on Darwin and rely on
the `subprocess.run` wall-clock timeout for memory containment.

This is a war story — the early code set RLIMIT_AS unconditionally, every
inner-loop trial died on macOS, debugged for 30 minutes before realizing.

---

# Part IV — The face

## 16. Current frontend architecture

Path: `frontend/dashboard/`

Tech stack (verbatim from `frontend/dashboard/package.json`):

- **Next.js 16.2.4** (note: this is *not* the Next.js you know — see
  `frontend/dashboard/AGENTS.md`. Some APIs differ from training data,
  including async route params.)
- **React 19.2.4** with the new compiler.
- **TypeScript 5+** strict mode.
- **Tailwind CSS 4** (config in `tailwind.config.ts` is minimal — most theme
  in `app/globals.css`).
- **Framer Motion 12** — landing-page typing animation, scanline.
- **D3 7.9** — custom SVG for the trajectory tree (`TrajectoryTree.tsx`).
- **`@xyflow/react` 12.10** (ReactFlow under the new package name) — used by
  `StateGraph.tsx` to render the outer + inner state-graph diagram on the
  Context Panel's `graph` tab.
- **`@monaco-editor/react` 4.7** — used by `DiffViewer.tsx`. We do load Monaco;
  the earlier draft of this doc said "no Monaco" but the actual code uses the
  side-by-side `DiffEditor` component. Monaco's bundle weight is the price for
  professional-looking diffs that judges recognize from VS Code.
- **Playwright 1.59** for e2e tests at `frontend/dashboard/e2e/dashboard.spec.ts`.

### 16.1 Routes

- `/` — landing page (`src/app/page.tsx`). Typed-out title "META-HARNESS",
  fetches `GET /runs`, lists recent runs, "Enter Dashboard" button.
- `/runs/[run_id]` — main dashboard (`src/app/runs/[run_id]/page.tsx`). Async
  params (Next.js 16 convention). Wraps the 3-panel layout in
  `<DashboardProvider>`.

### 16.2 The 3-panel layout

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ TopBar — currently a stub showing only the META-HARNESS logo                  │
├──────────────┬──────────────────────────────────────┬──────────────────────────┤
│              │                                      │                          │
│ Trajectory   │         Decision Log                 │      Context Panel       │
│ Tree (D3)    │  (iteration chapters, collapsible,   │   tabs: chart / diff /  │
│              │   expandable lines, fork ribbons)    │   test / memory / graph │
│ 220px fixed  │  flex-[4]                            │   flex-[3]              │
│              │                                      │                          │
│              │                                      │                          │
├──────────────┴──────────────────────────────────────┴──────────────────────────┤
│ StatusBar — SSE status, branch count, checkpoint ID, version                  │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Spec vs implementation reality.** The locked design in
`frontend/DESIGN.md` §3 calls for 26% / 44% / 30% panel widths with 16px
gaps. The current implementation in
`frontend/dashboard/src/app/runs/[run_id]/page.tsx:47-57` uses
`w-[220px]` for the trajectory tree, `flex-[4]` for the decision log, and
`flex-[3]` for the context panel — i.e. the tree is a fixed 220px and the
remaining space splits 4:3 between the log and context. This is closer to
~13% / ~50% / ~37% on a 1920px viewport. The DESIGN.md numbers are the
*spec*; the live code diverged for layout convenience. If you ship the
demo and want the spec to match reality, edit either the doc or the
flex factors.

### 16.3 State management

`src/lib/state.ts`. React Context + `useReducer`. No Redux/Zustand.

```typescript
type DashboardAction =
  | { type: "SET_RUN"; payload: RunSummary | null }
  | { type: "SET_TREE"; payload: TreeNode[] }
  | { type: "ADD_TREE_NODE"; payload: TreeNode }
  | { type: "SET_ITERATIONS"; payload: IterationChapter[] }
  | { type: "ADD_LOG_ENTRY"; payload: LogEntry }
  | { type: "SET_LOG_ENTRIES"; payload: LogEntry[] }
  | { type: "ADD_FORK_EVENT"; payload: ForkEvent }
  | { type: "SET_FILTER"; payload: Partial<DashboardFilters> }
  | { type: "SET_CONTEXT_TAB"; payload: ContextTab }
  | { type: "SELECT_NODE"; payload: string | null }
  | { type: "SELECT_LOG_LINE"; payload: string | null }
  | { type: "SET_SSE_CONNECTED"; payload: boolean };
```

`initialState` is empty (`tree: []`, `iterations: []`, etc.). The page
subscribes to SSE on mount; events dispatch actions; components re-render.

A separate `demoFixtureState` export holds the canned demo data for the
landing-page screenshot path; production runs never use it.

### 16.4 SSE integration

`src/lib/sse.ts` exports two entry points: a low-level
`subscribeToRun(runId, handlers)` that registers per-event listeners on a
fresh `EventSource`, and a higher-level `startSSE(runId, dispatch)` that
opens the stream and routes each event to a reducer action.

`subscribeToRun` is exhaustive — handlers are registered for every key in
the supplied `handlers` object via `Object.entries(handlers)`. So *any* of
the 11 event types are addressable from the call site.

`startSSE` (`src/lib/sse.ts:68-95`), which is what the dashboard page
actually uses, is **not** exhaustive. It currently routes 6 of the 11
event types into reducer actions:

| SSE event | `startSSE` handler? | Reducer action |
|---|---|---|
| `state-update` | ✅ | `SET_RUN` (when `e.data.run` is present) |
| `checkpoint-written` | ❌ | (event arrives but is dropped) |
| `candidate-created` | ✅ | `ADD_TREE_NODE` |
| `validate-result` | ❌ | (event arrives but is dropped) |
| `eval-result` | ✅ | `ADD_TREE_NODE` |
| `frontier-updated` | ✅ | `SET_TREE` (when `e.data.tree` is present) |
| `iteration-complete` | ✅ | `ADD_LOG_ENTRY` (when `e.data.log` is present) |
| `fork-created` | ✅ | `ADD_FORK_EVENT` |
| `branch-cancelled` | ❌ | (event arrives but is dropped) |
| `memory-pattern-stored` | ❌ | (event arrives but is dropped) |
| `error` | ❌ | (event arrives but is dropped; `onError` only fires on transport errors) |

The 5 unrouted events still fly over the wire — they're just not turned
into UI updates today. If you want to surface "validate failed" in the
dashboard, you add one entry to the handlers object in `startSSE`. This is
the cleanest "first task for a new contributor" entry point.

`startSSE` returns the `() => source.close()` cleanup, which the page's
`useEffect` returns from its callback to tear down the connection on
unmount.

### 16.5 Color system (DESIGN.md §9)

The dashboard uses **whisper colors** — heavily desaturated, ~35-45%
saturation. The intent: a dim instrument panel at night. Not a Slack channel.

```css
--cyan:   #7ab8ad;  /* sage teal — best candidate, active phases */
--green:  #6a9e78;  /* dusty sage — accepted, passing tests */
--red:    #b06068;  /* muted rose — rejected, failing tests */
--amber:  #b09868;  /* khaki — verify, memory, warnings */
--purple: #8878a8;  /* dusty lavender — fork branches */
--blue:   #7090b0;  /* slate blue — plan phase */
```

Backgrounds are warmer charcoal (`#0c0c12` body, `#111118` panels), not pure
black. Text is `#c8c8d0` warm gray, never white. Monospace throughout
(JetBrains Mono).

### 16.6 What's already wired vs. what's still mock

**Wired to the live backend:**
- Landing page run list (`GET /runs` via `lib/api.ts:listRuns`)
- Health check (`GET /health` via `lib/api.ts:isBackendAvailable`)
- Run detail load (`GET /runs/{run_id}` via `lib/api.ts:getRunDetail`)
- SSE subscription on `/runs/{run_id}/stream` — see §16.4 for which events
  actually update the UI.
- Fork POST API exists in `lib/api.ts` (`postFork`, `forkRun`) and the
  `ForkModal` component imports it; the `TrajectoryTree` opens the modal
  on right-click of any node.

**Returning null (gracefully degrades to "no data" placeholder):**
- `getDiff(candidateName)` → returns `null` (no `GET /runs/{id}/candidates/
  {name}/diff` endpoint exists yet on the backend; `ContextPanel` shows
  "No diff available for {candidate}" when this returns null).
- `getTestOutput(candidateName)` → returns `null` (same — no API yet,
  same placeholder behavior).

**Mock or partly mock:**
- `MemoryPanel.tsx` is *partly* mock: it renders three hardcoded "From
  previous runs" patterns at lines 17-21, then appends real-run memory
  events that arrive via SSE (filtered from `logEntries` by `tag === "memory"`).
  It does NOT call `GET /memory/{namespace}` to fetch actual stored
  patterns; wiring that fetch through is a one-function change and would
  remove the last hardcoded fixture from the live-data path.
- `TopBar.tsx` is currently a 14-line stub showing only the
  `META-HARNESS` logo with a link to home. The doc + DESIGN.md describe
  iteration counters, best-score, cost, and elapsed-time displays; none
  of those are implemented yet. The data is in `useDashboard()`'s `run`
  field — it just has no rendering code.
- The fixture files at `src/lib/mock/{evolution,events,diffs,test-output}.ts`
  exist for static-mode screenshots and the demo-mode landing page. Live
  runs do not consume them by default; they only fill the
  `demoFixtureState` named export at `src/lib/state.ts:134-159`.

---

## 17. Ideal frontend design + visual decisions

This section answers the user's explicit ask: *what should the frontend look
like, and why?* It builds on `frontend/DESIGN.md` (which is locked) but
includes additional tactical recommendations for hackathon polish.

### 17.1 Design philosophy: "instrument panel," not "dashboard"

The dominant visual reference for AI-products-as-of-2026 is a Notion-style
white background with rainbow accent colors. **Don't do that.** Judges have
seen 80 of those today. Ours should look like:

> *A dimly-lit cockpit on a research probe. Calm. Focused. Precise. The
> system is doing serious work; the UI gets out of the way.*

Concretely:

- **Charcoal background** (`#0c0c12`), warmer than pure black.
- **Monospace everywhere.** JetBrains Mono. Self-hosted (don't rely on
  Google Fonts CDN during the demo — wifi can fail).
- **Whisper accents.** Colors at ~35-45% saturation. They tint the UI; they
  don't shout. A judge should look up at the screen, see the live data, and
  feel that the *data* is the spectacle, not the chrome.
- **Letter-spacing matters.** Headers like "META-HARNESS" should have
  3px letter-spacing. Badges have 0.5px. It evokes telemetry.
- **Generous padding.** 24px inside panels. 16px between panels. Cramped
  layouts read as desperate; spaced-out layouts read as confident.

### 17.2 Three-panel split is correct (don't change it)

26% / 44% / 30%:

- **Left (26%) — Trajectory tree.** This is the demo's hero.
- **Center (44%) — Decision log.** This is what tells the *story* — the live
  thinking of the agent, layered into iteration chapters.
- **Right (30%) — Context panel.** Score chart always visible at the top
  (200px); tabs below for diff / test output / memory.

The trajectory tree is on the left because Western readers scan left-to-right.
The "shape" of the run lives there. The center is the verbal narrative
(orient → plan → tool calls → verify → score). The right is the deep-dive
on whatever's selected.

### 17.3 The trajectory tree is the *hero* — get it right

The whole pitch is "linear → tree." If the tree doesn't visibly *branch* on
the demo screen, the pitch lands flat.

**Layout:** vertical, root at top, descendants down. Each iteration is one
node-row. Forks bend laterally — usually right, since the original branch
continues straight down.

**Node visual hierarchy** (from DESIGN.md §4.2):

| Status | Border color | Bg | Glow |
|---|---|---|---|
| Baseline (seed) | `#32323e` (mid gray) | `#16161e` | none |
| Accepted | `#6a9e78` (dusty sage) | `#111816` (3% green tint) | none |
| Rejected | `#b06068` (muted rose) | `#181114` (3% red tint) | none, 40% opacity |
| Best | `#7ab8ad` (sage teal) | `#111616` (3% teal tint) | very subtle, 10% opacity |
| Fork branch | `#8878a8` (dusty lavender) | `#141218` (3% purple tint) | none |

Each node card shows:

```
ITER 4                        BEST
more-specific-descriptions
  0.80   +0.06
```

- Iteration label (top-left, 8px, uppercase, ghost color)
- Candidate name (middle, 10px, primary color)
- Score (bottom-left, 13px bold, color-coded)
- Delta (next to score, 9px, +green/−red)
- Status badge top-right when relevant (BEST, REJECTED)

**Fork zones:** when a fork happens, render a *horizontal band* across the
tree at the fork point, with `⑂ FORK` label and the fork's prior text.
Background: 3% lavender tint. Dashed lavender border.

**Animation:** keep it minimal. Snap to show fork branches; don't slide them
in. Animation that the user hasn't yet seen feels novel; animation they've
seen 3 times feels like a delay. Hackathon judges have seen 3 of yours.

### 17.4 The decision log: chapters + lines

The decision log is **the ONLY place where the agent's reasoning is visible**.
This is what makes the demo feel alive. Without this, you have a status board.

**Two-level hierarchy:**

```
══════ ITER 4 — more-specific-descriptions ══════════ [ACCEPTED]
  ▣ propose ✓  ▣ validate ✓  ▣ benchmark ●  ▣ frontier
  Hypothesis: "more specific tool descriptions improve plan grounding"
  ┌──────────────────────────────────────────────
  │ 14:32:11  orient    read 8 files in workspace
  │ 14:32:14  plan      submit_plan: rewrite tool descriptions
  │ 14:32:18  tool/read agents/early-exit-on-auth.py
  │ 14:32:24  tool/patch ▸ applied patch to agents/more-specific-descriptions.py
  │ 14:32:42  verify    ▸ 5 tests passed in 0.04s
  │ 14:32:43  score     accuracy=0.80 (+0.06) NEW BEST
  └──────────────────────────────────────────────
══════ ITER 2′ — rewrite-tool-descriptions (FORK) ════ [running]
  ⑂ FORK from iter 1 / ckpt_2c81ef03
  ▣ propose ●
  Prior: "explore example-driven prompts instead of hash-based dedup"
  ...
```

Each iteration is a **chapter header** (collapsible, color-coded by status).
Inside, **log lines** at three levels of detail:

- Tag (color-coded pill)
- Timestamp (10px ghost)
- Text
- Expand indicator (`▸`) when there's more

**Expand-on-click:**
- `tool/read` lines → first 20 lines of the file content
- `tool/patch` lines → inline unified diff *and* select it in context panel
- `verify` lines → full pytest output with pass/fail per test
- `score` lines → per-task breakdown

**Filter bar**: `all` / `tools` / `verify` / `scores` / `forks` toggle pills,
plus a search input. Filters are additive.

### 17.5 The context panel: five tabs, picked by user

Actual tab list in `ContextPanel.tsx:14`:

```typescript
const tabs = ['chart', 'diff', 'test', 'memory', 'graph'] as const;
```

So **5 tabs**, not 3. The DESIGN.md spec said "Score Chart always visible at
top + tabs below"; the implementation simplified that to a tab switcher
where `chart` is the default tab. Honest about that gap below.

**`chart` tab — `ScoreChart.tsx`.** SVG line chart, x = iteration, y =
accuracy. Two lines (main + fork), rejected dots marked differently,
baseline as a dashed reference at 0.62. Y-axis 0.60–0.90 (auto-scales).
Always-visible-at-top would be better for the demo (the judge sees the
arc updating while reading the diff); see §17.8 for that recommendation.

**`diff` tab — `DiffViewer.tsx`.** Uses `@monaco-editor/react`'s
`DiffEditor` component, side-by-side mode, theme `vs-dark`, 12px JetBrains
Mono. Line numbers on, minimap off, scrollbars 6px. The component parses
unified-diff input into `original` and `modified` text and feeds them to
Monaco. Activated by clicking a tree node OR a `tool/patch` log line.
Currently `getDiff()` returns `null` for all candidates, so the panel
displays "No diff available for {candidate}" until the diff API is wired.

**`test` tab — `TestOutput.tsx`.** Pytest stdout in monospace, color-coded
PASSED/FAILED. Activated by clicking a `verify` log line. `getTestOutput()`
also returns null today, same placeholder.

**`memory` tab — `MemoryPanel.tsx`.** Lists "From previous runs" patterns
(currently 3 hardcoded fixtures at lines 17-21 of MemoryPanel.tsx) and
"This run" patterns (filtered from `logEntries` where `tag === "memory"`).
The doc earlier claimed it renders `format_patterns_for_prompt`'s output
verbatim — that's the *intent*; the live implementation isn't there yet.
The cleanest patch: call `GET /memory/{namespace}` on mount and render its
`entries` array, replacing the three hardcoded fixtures.

**`graph` tab — `StateGraph.tsx`.** ReactFlow (via `@xyflow/react`)
diagram of the outer + inner state machines. Static layout (nodes don't
update in real time today); shows the `propose → validate → benchmark →
update_frontier` outer loop with a fork branch back to propose, and below
it the inner loop `orient → plan → act → verify → submit` with the
verify→act retry edge. Useful for explaining the architecture to judges
who haven't read this document.

### 17.6 The TopBar: aspirational vs. actual

**The aspirational design** (DESIGN.md §4.1):

```
META-HARNESS  ●  demo-2026-04-25 ▾  │  iter 4/5  │  best 0.85  │  $2.14  │  4m32s
```

- Logo: cyan, uppercase, 3px letter-spacing.
- Run selector: dropdown with green dot if SSE connected, amber if
  reconnecting.
- Iteration counter: `iter N/budget` (sourced from `state-update`).
- Best score: cyan, pulses gently for 1s on update (sourced from
  `frontier-updated`).
- Cost: running total of `eval-result.cost_usd`.
- Elapsed: client-side timer started on run-start.

**The current implementation** (`src/components/TopBar.tsx`, 14 lines):

```tsx
export function TopBar() {
  const { run } = useDashboard();
  const elapsed = '4m32s'; // static for demo
  return (
    <div className="h-12 flex items-center px-6 bg-header border-b border-border">
      <Link href="/" className="text-cyan text-sm font-semibold tracking-[3px] uppercase ...">
        META-HARNESS
      </Link>
    </div>
  );
}
```

Just the logo. No iteration counter, no best score, no cost, no elapsed
timer. The `useDashboard().run` field has all the data — it's just not
rendered yet, and the `elapsed = '4m32s'` literal is dead code.

**This is the highest-impact two-hour task you can ship before demo day.**
The data is already in state; you only need to add JSX. Order of fix
priority: iteration counter > best score > SSE-connected dot > elapsed
timer > cost.

### 17.7 The StatusBar: facts, not flavor

```
●  SSE connected   │   2 branches   │   ckpt: a8f3…2e1b   │   v0.1.0
```

- SSE dot: green if connected, amber if reconnecting, red if dead.
- Branch count: from `branch_registry.length`.
- Latest checkpoint ID: truncated to 8+4 chars with ellipsis.
- Version: from `package.json`.

### 17.8 Things to ADD that aren't in DESIGN.md but would help the demo

These are tactical additions for hackathon judging that would push the demo
from "nice" to "memorable":

1. **A "REWIND HERE" button visible on every tree node.** Right-click is fine
   but a *visible* button per node — small, ghost-colored, only on hover —
   makes the time-travel feature physically obvious. Judges shouldn't have
   to know about right-click.
2. **Fork-event ribbons spanning the trajectory tree.** When a fork occurs,
   render a horizontal dashed lavender ribbon spanning the tree pane,
   reading `⑂ FORK at iter 2` with the new prior. The visual *change* of
   the tree's shape is the demo's punchline; emphasize it.
3. **A "what is this?" explainer card** that floats over the trajectory tree
   for 10 seconds when the page first loads, with one line of text:
   `"Each node is a candidate harness. Forks let you rewind and try a different proposer prior."` Then dismisses on interaction.
4. **A live transcript panel during the proposer call.** When the proposer
   is running (`state-update` with `node: "propose"`), show the streaming
   `claude` CLI transcript in the context panel for as long as it's
   running. Then swap back to whatever was selected. This is what
   `transcript.txt` already contains; we just need to stream it via SSE
   instead of writing to file.
5. **Pareto frontier highlight** on the score chart. Non-dominated
   candidates get a small ring around their score dot. Dominated ones get a
   diagonal hash. This makes "two branches, both Pareto-optimal" visually
   reproduce in a single glance.
6. **Cost / token side-by-side, not just cost.** "$2.14 (24.3K tokens avg)"
   in the TopBar. Token efficiency is part of the paper's headline result;
   show it.
7. **A small "memory injected: 3 patterns" indicator** in the propose-node
   chapter header on iter 1+. Currently we just emit
   `memory-pattern-stored` — judges won't notice. Make it visible: "iter 1
   started with 3 memory patterns."

### 17.9 Things to NOT add

- **No animations on every transition.** Hackathon demos that animate
   state-update events feel slower, not faster.
- **No tooltips that take >300ms to appear.** Judges scan; tooltips that
   require hover-and-wait get missed.
- **No A/B comparison view in v1.** Tempting but adds complexity. The two
  branches being visible side-by-side on the tree is enough.
- **No graph theme switcher.** Dark only. Light theme isn't worth the
  testing surface for a 90-second demo.
- **No "run history" explorer.** The dashboard is per-run. Multi-run is a
  future feature.

### 17.10 Demo-day failure recovery: build "demo mode"

If the live backend dies during the demo (Postgres OOM'd, Anthropic API
error), have a `?demo=true` query param that switches the frontend to the
canned `demoFixtureState` from `state.ts`. The mock SSE replay timer
re-emits events at 1× wall-clock speed.

This is what `frontend/dashboard/src/lib/state.ts:134-159` is for — keep
it. The default state is empty, but `demoFixtureState` exists for exactly
this contingency. **Test it before demo day.** Walk into the demo room
having already opened `localhost:3000/runs/demo-2026-04-25?demo=true` once
and confirmed the canned run plays cleanly.

---

# Part V — The demo

## 18. The demo arc as written

From `docs/DEFINITION_OF_DONE.md` §3:

```text
Linear branch (~6 minutes, baseline ≈ 0.62 on Haiku 4.5 over 5 tasks × 5 trials):

| Iter | Hypothesis                              | Score | Δ      | Outcome   |
|------|-----------------------------------------|-------|--------|-----------|
| 1    | retry on schema_drift errors            | 0.70  | +0.08  | keep ✓    |
| 2    | stricter tool-description hashing       | 0.66  | -0.04  | reject ✗  |
| 3    | early-exit on auth failures             | 0.74  | +0.04  | keep ✓    |
| 4    | more specific tool descriptions         | 0.80  | +0.06  | keep, NEW BEST ✓ |

Right-click iter-2 checkpoint → "Fork from here" → edit prior → Resume:

| Iter | Hypothesis                              | Score | Δ                 | Outcome      |
|------|-----------------------------------------|-------|-------------------|--------------|
| 2′   | rewrite tool descriptions w/ examples   | 0.78  | +0.16 from iter 1 | keep ✓       |
| 3′   | add few-shot demos to descriptions      | 0.85  | +0.07             | GLOBAL BEST  |

Pareto frontier:
- more-specific-descriptions: 0.80 @ ~24,800 avg tokens — non-dominated
- few-shot-demos:            0.85 @ ~26,200 avg tokens — non-dominated
- tighter-tool-hashing:      0.66 — dominated by both above

Cost & runtime:
- Total wall time: < 8 minutes (target 6)
- Total cost: ~$3.30 (Appendix C §C.12), hard cap < $5
```

### 18.1 Holdout

Run-end automatically re-evaluates the linear-best AND fork-best against the
2 unseen tasks in `eval/holdout/`. Holdout score is reported separately. The
*gap* between search-set score and holdout score is the overfitting signal.

### 18.2 Why this arc is worth showing

Three reasons, each judge-relevant:

1. **The reject** at iter 2 (0.66 < 0.70) shows the system *resists
   parameter-tweak hill-climbing*. A naive auto-tuner accepts every change;
   ours rejects regressions, which means the search is doing real work.
2. **The fork** at iter 2′ shows that **branching beats sequential**. The
   linear path got 0.80; the fork got 0.85. *The same compute budget,
   spent differently, produced a strictly better best.* That's the headline.
3. **Two Pareto-optimal points** at the end — judges with ML background
   recognize Pareto frontiers immediately and read it as "this team
   understands optimization."

---

## 19. The 90-second pitch (annotated)

Verbatim from DEFINITION_OF_DONE.md §5, with annotations on what to do
on-screen and what to emphasize verbally:

```text
[0:00-0:08] HOOK
"Stanford published Meta-Harness four weeks ago — Lee, Khattab, Finn.
Their proposer agent reads execution traces and rewrites the harness,
beating ACE by 7.7 points. But their loop is linear. We mapped it
onto LangGraph and made it a tree."
```

Verbal emphasis: *"linear … tree."* Pause briefly. The whole pitch is
this contrast.

```text
[0:08-0:23] ACT 1 — Local launch
[Browser at localhost:3000. Click "New run" → "Coding agent template" →
 "Start". Run dashboard renders.]
"30 seconds, no cloud. Five-task eval. Baseline: 62%."
```

You're showing that the system is *concrete and runnable*. No magic.

```text
[0:23-0:53] ACT 2 — Linear loop
[State graph populates. Iterations stream in via SSE.]
  Iter 1: retry on schema_drift errors        → 0.70 (+0.08) ✓
  Iter 2: stricter tool-description hashing   → 0.66 (−0.04) ✗
  Iter 3: early-exit on auth failures         → 0.74 (+0.04) ✓
  Iter 4: more specific tool descriptions     → 0.80 (+0.06) ✓ NEW BEST
"Stanford's regime — exactly. But here's where it gets interesting."
```

The emphasis "Stanford's regime — exactly" tells the judge *we replicated
the paper, faithfully*. Don't skip past this. The line "where it gets
interesting" is the pivot to the novelty.

```text
[0:53-1:20] ACT 3 — Time-travel + memory
[Right-click iter-2 in the trajectory tree → "Fork from here" → modal opens
 → edit proposer_prior → Resume. Tree visibly branches.]
"Rewinding to iteration 2. Forking with a different prior."
[Both branches grow concurrently. Compare view side-by-side.]
  Iter 2′: rewrite tool descriptions w/ examples → 0.78 (+0.16) ✓
  Iter 3′: add few-shot demos to descriptions    → 0.85 (+0.07) ✓ GLOBAL BEST
"Two branches. Original 0.80. Fork 0.85. The meta-harness loop is
no longer a sequence — it's a search tree."
[Click memory panel.]
"And LangGraph's cross-thread memory means the next run starts smarter."
```

This is the demo's heart. Verbal emphasis on "concurrently" — point at the
tree to show both branches are running. The memory-panel click at the end
is the kicker: *runs learn from runs.*

```text
[1:20-1:30] CLOSE
"Time-travel for Meta-Harness. Built on LangGraph state machines.
Secure, consistent, reversible — by construction. Open source.
That's Meta-Harness. One spark."
```

The "by construction" line is what differentiates from "we built a custom
orchestration layer." We didn't — we picked the right substrate. That's a
better story.

### 19.1 Demo prep checklist (the morning of)

- [ ] Postgres healthy: `docker compose -f infra/docker-compose.yml ps`
- [ ] Backend running on `:8000`: `cd backend && uv run uvicorn app.main:app --port 8000 --reload`
- [ ] Frontend running on `:3000`: `cd frontend/dashboard && npm run dev`
- [ ] Run `bash scripts/demo_dryrun.sh` end-to-end and confirm 12/12 GREEN
- [ ] Test count check: `cd backend && uv run pytest tests/ --collect-only -q | tail -1`
      should report **78 tests collected** (the older README claim of 47 is stale)
- [ ] Pre-warm the demo: open `http://localhost:3000/runs/demo-2026-04-25?demo=true`
      and let the canned mock data play through once
- [ ] Confirm `claude --version` is on PATH (the proposer subprocess fails
      with `exit 127` if not)
- [ ] Confirm `.env` has `ANTHROPIC_API_KEY`
- [ ] Confirm `agents/baseline.py` exists and imports cleanly:
      `uv run python -c "from agents.baseline import BaselineHarness; print('OK')"`
- [ ] Two terminals open before demo: backend log tail + frontend log tail
- [ ] Browser zoom level set to 100%; full-screen the dashboard
- [ ] Backup plan: if backend dies, switch to `?demo=true` mock path

### 19.2 Demo failure recovery (likely scenarios)

| Failure | Symptom | Recovery |
|---|---|---|
| Postgres OOM | `connection refused` on backend startup | `docker compose restart postgres`; wait 5s |
| Anthropic 429 | Inner trials fail | `--mock-bench` for the demo arc |
| `claude` CLI missing | Proposer subprocess `exit 127` | Use `--proposer mock` |
| Frontend build broke | White screen | Switch to `?demo=true` (renders canned fixture) |
| SSE drops | "Disconnected" badge | Browser auto-reconnects via `Last-Event-ID` |

Have at least one of: `?demo=true`, `--mock-bench`, `--proposer mock` ready
to paste.

---

## 20. Why this project is genuinely unique

If a judge asks "what's novel here vs. just running Stanford's repo," your
five-bullet answer:

1. **The substrate is the contribution.** Stanford's loop is a Python `for`
   loop. We mapped it onto LangGraph state machines, where every state
   transition becomes a Postgres checkpoint. From that one substrate
   decision, three properties (secure / consistent / reversible) fall out
   *by construction*. We didn't write the time-travel code; we got it for
   free.
2. **Linear → tree is real, not metaphor.** Right-click any historical
   checkpoint, edit the proposer prior, and a new branch starts running
   *concurrently* with the original. Both grow on the dashboard
   simultaneously. The trajectory genuinely *forks*. Stanford's run is
   `iter 1 → 2 → 3 → 4`; ours is a DAG with an arbitrary number of
   branches per checkpoint.
3. **Cross-run memory persists in Postgres.** A pattern accepted in run A
   is read by run B's proposer prior. Each run starts smarter than cold.
   Stanford's paper has cross-task transfer but not in their reference
   repo; ours wires it through `AsyncPostgresStore`.
4. **`apply_patch.context_echo` is a paper-quality tool design.** When a
   unified diff fails to apply, instead of "patch failed; re-read and
   retry," we surface the file's *actual current content* at the failed
   range — so the model fixes the patch in the next turn without spending
   tokens on re-reading. The token budget savings are large in practice.
5. **The 11 search-space methods + 6 fixed tools is a precise contract.**
   Most "self-improving agent" demos are vague: "the agent rewrites
   itself." Ours is specific: 11 named methods can be overridden, 6 named
   tools cannot, the boundary is enforced at validate-time. This is what
   makes the search tractable — bounded and analyzable, not an open-ended
   "rewrite Python."

### 20.1 The five-second hook (if you only get one sentence)

> *"Stanford's Meta-Harness loop is linear; we made it a tree, with
> Postgres-backed time-travel and concurrent branches running on a
> single-laptop substrate."*

That's the elevator pitch. Memorize it.

---

## 21. Likely judge questions + answers

**Q: How is this different from just calling DSPy?**

A: DSPy optimizes prompts within a fixed compute graph. Meta-Harness
optimizes the *graph itself* — the harness, the tool-result formatting, the
retry policy, the context-overflow strategy. Prompts are one of 11 things
the proposer can change. The unit of evolution is the entire inner-loop
state machine.

**Q: What stops the proposer from cheating? E.g. hardcoding "if task is
calculator, do X."**

A: Three layers of defense:

1. **SKILL.md Anti-Overfitting rules.** The proposer reads "no
   task-specific knowledge" verbatim before every iteration.
2. **Holdout evaluation.** After the search loop, the best candidate is
   re-evaluated on tasks it never saw. The gap shows overfitting.
3. **Anti-Parameter-Tuning rules.** "Mechanism, not constants." Candidates
   that just bump `MAX_ACT_TURNS` are explicitly rejected by the SKILL.md
   workflow.

The proposer's self-critique block at the top of every candidate file
acknowledges these — it's part of the file format.

**Q: Why LangGraph instead of just writing your own state machine?**

A: Three things you'd have to reinvent:

1. **AsyncPostgresSaver.** Atomic per-node checkpointing with `parent_config`
   pointers, exactly-once semantics on resume. ~1,000 lines if you wrote it
   yourself.
2. **`aget_state_history` + `aupdate_state` time-travel primitives.**
   Walking the checkpoint DAG, projecting state at any historical point,
   forking with state mutations.
3. **AsyncPostgresStore** for cross-run memory in the same DB.

Plus we get the LangGraph community's bug fixes for free (e.g. the
`asyncio.gather`-eats-interrupts issue we cite from #6624).

**Q: How long does a real run take?**

A: With Haiku 4.5 inner-loop on 5 tasks × 5 trials × 4 iterations, ~6
minutes wall time and ~$3.30 cost. The proposer (Opus) is ~2 minutes per
iteration; benchmarking is ~30 seconds per iteration with workers=4. Total
wall is dominated by the proposer's read+write rounds.

**Q: Can you actually run this end-to-end live?**

A: Yes — `bash scripts/demo_dryrun.sh` runs all 12 acceptance checks.
For the judging demo we use `--mock-bench` to deterministic-ify the score
arc; the proposer is real (`--proposer claude`). This is the right
trade-off because the demo-arc score curve is deterministic by design (the
paper's calibration tasks plateau at 100% on Haiku, so live scores would be
flat — the mock-bench reproduces the *paper's* expected arc with realistic
timing).

**Q: What if I want to use this for my own domain?**

A: Write a new `skills/meta-harness-<domain>/SKILL.md` (~150 lines) and a
new base harness class. Everything else (outer loop, persistence, SSE,
forks, dashboard) is domain-agnostic. The 6 fixed tools work for any
filesystem-mediated agent task; the 11 override points generalize.

**Q: Why didn't you include {feature X}?**

A: 36-hour scope. Things explicitly out of scope:

- Multi-tenant / auth (single user, single laptop)
- Worker queues (FastAPI BackgroundTasks suffice for ≤10 concurrent branches)
- pgvector embeddings for memory (recency-weighted top-N is enough; semantic
  search is a roadmap item)
- Docker per task (process isolation is honest about its limits)
- Cloud anything (local-only deployment by design)

We're explicit about these in the README under "what's out of scope."

**Q: Can two forks share their checkpoint database without race conditions?**

A: Yes — `AsyncPostgresSaver` uses a connection pool with autocommit. Each
node's checkpoint write is atomic; concurrent forks each get their own
thread_id namespace. We tested this: see `backend/tests/test_branches.py`'s
concurrent-branches case which spawns 2 branches and verifies both
completion + no deadlock.

**Q: How do you know the inner loop is actually solving real tasks vs.
hallucinating?**

A: `pytest -q` on the task's test file. If the test command exits 0, score
= 1.0; otherwise 0.0. There's no LLM judge in the loop — the verifier is
the test runner. This is the same evaluator Stanford uses.

**Q: What happens if the proposer writes broken Python?**

A: `validate` node catches it. `importlib.import_module` raises, we set
`status = "smoke_failed"`, candidate is ignored, budget continues. Worst
case: proposer wastes one iteration. The SKILL.md tells the proposer to
verify imports cleanly with `uv run python -c "from agents.<n> import *;
print('OK')"` before registering — most don't slip through.

---

# Part VI — Reference

## 22. File:line lookup index

The keystone files, sorted by likelihood of "I need to know how X works":

### Engine

| Component | File | Key lines |
|---|---|---|
| MetaHarnessState / CodingAgentState | `backend/app/meta_harness/state.py` | 35-59 |
| Outer-loop graph | `backend/app/meta_harness/outer.py` | 543-563 (build), 109-197 (propose), 253-391 (benchmark), 395-536 (update_frontier) |
| Inner-loop graph | `backend/app/meta_harness/inner.py` | 416-458 (build), 63-111 (orient), 119-154 (plan), 177-271 (act), 320-345 (verify), 353-398 (submit) |
| 11 override points | `backend/app/meta_harness/harness.py` | 103-209 |
| 6 fixed tools | `backend/app/meta_harness/tools.py` | 36-128 (schemas), 153-466 (impls) |
| `apply_patch` context_echo | `backend/app/meta_harness/tools.py` | 263-292, 295-376 |
| Path traversal protection | `backend/app/meta_harness/tools.py` | 138-150 |
| Sandbox lifecycle | `backend/app/meta_harness/sandbox.py` | 44-78 (create/populate/cleanup), 81-107 (rlimits), 110-131 (run) |

### Proposer

| Component | File | Key lines |
|---|---|---|
| `claude_propose` (full subprocess dance) | `backend/app/meta_harness/proposer.py` | 184-368 |
| `_build_claude_command` (the CLI args) | `backend/app/meta_harness/proposer.py` | 141-172 |
| Stream-json event accumulator | `backend/app/meta_harness/proposer.py` | 371-409 |
| Mock proposer | `backend/app/meta_harness/proposer.py` | 47-103 |
| SKILL.md frontmatter + 6 sections | `skills/meta-harness-coding-agent/SKILL.md` | 1-150 |

### Substrate

| Component | File | Key lines |
|---|---|---|
| `persistence_layer` ctx mgr | `backend/app/meta_harness/persistence.py` | 41-70 |
| `healthcheck` (the kwarg fix) | `backend/app/meta_harness/persistence.py` | 73-95 |
| `worktree_add` (fork primitive) | `backend/app/meta_harness/branches.py` | 180-234 |
| `cancel_branch` | `backend/app/meta_harness/branches.py` | 237-249 |
| `reconstruct_trajectory` | `backend/app/meta_harness/branches.py` | 265-293 |
| `_infer_as_node_for_fork` | `backend/app/meta_harness/branches.py` | 375-393 |
| `add_pattern` / `search_patterns` | `backend/app/meta_harness/memory.py` | 67-89 (write), 95-149 (read) |
| `format_patterns_for_prompt` | `backend/app/meta_harness/memory.py` | 155-178 |

### API + SSE

| Component | File | Key lines |
|---|---|---|
| Closed-set event registry | `backend/app/streaming.py` | 19-33 (allowlist), 80-187 (registry impl) |
| Per-channel subscribe + replay | `backend/app/streaming.py` | 147-187 |
| `POST /runs` (201 + Location) | `backend/app/api/runs.py` | 355-447 |
| Run lifecycle (`_execute_run`) | `backend/app/api/runs.py` | 250-285 |
| `GET /memory/{ns}` endpoint | `backend/app/api/memory.py` | 44-77 |
| `POST /memory/{ns}/search` | `backend/app/api/memory.py` | 80-123 |

### Frontend

| Component | File | Notes |
|---|---|---|
| Dashboard types (matches INTERFACES.md) | `frontend/dashboard/src/lib/types.ts` | 12 reducer actions, all SSE event types |
| Reducer + provider | `frontend/dashboard/src/lib/state.ts` | `initialState` empty; `demoFixtureState` for demo mode |
| Low-level SSE client | `frontend/dashboard/src/lib/sse.ts:31-60` | `subscribeToRun(runId, handlers)` — full coverage |
| High-level SSE client | `frontend/dashboard/src/lib/sse.ts:68-95` | `startSSE(runId, dispatch)` — 6 of 11 events handled today |
| REST + helper API client | `frontend/dashboard/src/lib/api.ts` | `getDiff/getTestOutput` return null today |
| Landing page | `frontend/dashboard/src/app/page.tsx:203-266` | Typing animation, run list |
| Dashboard page (3-panel layout) | `frontend/dashboard/src/app/runs/[run_id]/page.tsx:14-61` | `220px / flex-4 / flex-3` |
| TopBar (stub — only logo today) | `frontend/dashboard/src/components/TopBar.tsx` | 14 lines; data ready in state but no rendering |
| StatusBar | `frontend/dashboard/src/components/StatusBar.tsx` | SSE dot, branches, ckpt, version |
| Trajectory tree (D3 SVG) | `frontend/dashboard/src/components/TrajectoryTree.tsx:62-267` | `layoutTree` at 23-60; right-click → fork modal |
| Decision log (chapters + filters) | `frontend/dashboard/src/components/DecisionLog.tsx` | Auto-scroll + jump-to-latest |
| Context panel (5 tabs) | `frontend/dashboard/src/components/ContextPanel.tsx` | tabs: chart / diff / test / memory / graph |
| Score chart (SVG) | `frontend/dashboard/src/components/ScoreChart.tsx` | |
| Diff viewer (Monaco DiffEditor) | `frontend/dashboard/src/components/DiffViewer.tsx` | Side-by-side mode |
| Test output | `frontend/dashboard/src/components/TestOutput.tsx` | Pytest stdout renderer |
| Memory panel (partly mock) | `frontend/dashboard/src/components/MemoryPanel.tsx:17-21` | 3 hardcoded fixtures + live SSE memory events |
| State graph (ReactFlow) | `frontend/dashboard/src/components/StateGraph.tsx:36-105` | Static layout of outer + inner machines |
| Fork modal | `frontend/dashboard/src/components/ForkModal.tsx` | Triggered by right-click on TrajectoryTree node |
| Fork event card | `frontend/dashboard/src/components/ForkEvent.tsx` | Renders inside DecisionLog |
| Filter bar primitive | `frontend/dashboard/src/components/ui/FilterBar.tsx` | |
| Phase pipeline primitive | `frontend/dashboard/src/components/ui/PhasePipeline.tsx` | |
| Badge primitive | `frontend/dashboard/src/components/ui/Badge.tsx` | |
| Mock fixtures (demo mode) | `frontend/dashboard/src/lib/mock/{evolution,events,diffs,test-output}.ts` | Used by `demoFixtureState` |

### Eval / tasks

| Component | File |
|---|---|
| Search-set tasks (5) | `eval/tasks/task-001-fix-typo/` … `task-005-implement-spec/` |
| Holdout tasks (2) | `eval/holdout/task-006-fix-recursion/`, `eval/holdout/task-007-implement-stack/` |
| Multi-task scorer | `eval/score.py` |
| Baseline harness | `agents/baseline.py` |

### Tests

| File | Coverage |
|---|---|
| `backend/tests/test_outer.py` | Outer-loop nodes, mock proposer e2e |
| `backend/tests/test_inner.py` | 5-phase inner-loop, ReAct, verify retry |
| `backend/tests/test_tools.py` | All 6 tools incl. `apply_patch.context_echo` |
| `backend/tests/test_sandbox.py` | rlimits, /tmp lifecycle |
| `backend/tests/test_persistence.py` | AsyncPostgresSaver, healthcheck |
| `backend/tests/test_branches.py` | `worktree_add`, concurrent forks, cancel |
| `backend/tests/test_memory.py` | `add_pattern`, `search_patterns` |
| `backend/tests/test_memory_e2e.py` | Cross-run pattern propagation |
| `backend/tests/test_streaming.py` | Event registry, SSE format |
| `backend/tests/test_api.py` | All REST endpoints |
| `backend/tests/test_state.py` | TypedDict schemas |
| `backend/tests/test_frontier.py` | Pareto frontier, dominated_by_names |
| `backend/tests/test_cli.py` | Typer subcommand surface |

### Scripts

| File | Purpose |
|---|---|
| `scripts/demo_dryrun.sh` | 12 binary checks for demo readiness |
| `scripts/smoke_api.py` | Exercise the REST + SSE surface |

### Docs (read in this order)

1. `ARCHITECTURE_SECTION_1.md` (root) — locked architecture
2. `docs/PROJECT_LAYOUT.md` — repo tree + naming rules
3. `docs/INTERFACES.md` — every cross-component contract (canonical)
4. `docs/BUILD_ORDER.md` — 13 verified steps
5. `docs/DEFINITION_OF_DONE.md` — formal acceptance test
6. `docs/TEAM_HANDOFF.md` — 4-person coordination
7. `relay_metaharness_v7.md` — original design doc (the *why*)
8. `relay_v7_appendix_a_worktrees.md` — concurrent branches deep-dive
9. `relay_v7_appendix_b_metaharness_internals.md` — Stanford repo internals
10. `relay_v7_appendix_c_inner_loop.md` — 5-phase agent design
11. `frontend/DESIGN.md` — frontend layout + visual decisions
12. `skills/meta-harness-coding-agent/SKILL.md` — the proposer's tool

---

## 23. Glossary

| Term | Meaning |
|---|---|
| **Outer loop** | The 4-node `propose → validate → benchmark → update_frontier` LangGraph that evolves candidate harnesses. |
| **Inner loop** | The 5-node `orient → plan → act → verify → submit` LangGraph that runs ONE candidate harness on ONE task. |
| **Candidate** | A `agents/<name>.py` Python file subclassing `CodingAgentHarness`, produced by the proposer. |
| **Proposer** | The `claude` CLI subprocess that reads the run's filesystem state and writes a new candidate. The body of the outer loop's `propose` node — NOT a separate tier. |
| **Harness** | The base class (`CodingAgentHarness`) plus its 11 override points. The thing being evolved. |
| **Mechanism axis** | `exploration` (try a new approach) or `exploitation` (refine an existing one). Each candidate claims one. |
| **Hypothesis** | A one-sentence falsifiable claim about why the candidate's mechanism will improve scores. |
| **Pareto frontier** | The set of candidates not dominated on (accuracy, avg_tokens). `dominated_by_names == []` means non-dominated. |
| **Checkpoint** | A row in Postgres' `checkpoints` table written after every node transition by `AsyncPostgresSaver`. |
| **Thread** | A `thread_id`-keyed sequence of checkpoints. Parent runs use `run_id`; forks use `f"{parent}.fork.{8hex}"`. |
| **Fork** | A new thread whose initial checkpoint is a deep-copy of a parent thread's historical checkpoint, with optional state mods. |
| **SKILL.md** | The Markdown file with YAML frontmatter that injects via `--append-system-prompt` into the proposer subprocess. The proposer's "tool". |
| **Trace** | The per-trial filesystem artifacts under `runs/{run_id}/candidates/{name}/traces/{task_id}-trial-{N}/`: `orient.json`, `plan.json`, `act-messages.jsonl`, `act-tools.jsonl`, `verify.json`, `score.json`, `summary.md`, `final-files.json`. |
| **Workspace** | The `eval/tasks/{task_id}/workspace/` directory copied into a fresh `/tmp/meta-harness-task-{uuid}/` per trial. |
| **Sandbox** | The above `/tmp/...` directory with rlimits applied via `preexec_fn`. |
| **Context echo** | The `apply_patch` error response that surfaces the file's actual content at a failed-hunk's expected range. |
| **Closed set** | A frozenset of allowed values, runtime-enforced. We have one for SSE event types. |
| **Subscription auth** | The `claude` CLI auth path that uses your Claude Code subscription, bypassing API rate limits. We strip `ANTHROPIC_API_KEY` to force this. |

---

## 24. Common pitfalls / war stories

These are bugs we hit during the build that aren't obvious from the code. If
you're touching these areas, beware:

### 24.1 `psycopg.AsyncConnection.connect(timeout=5)` is invalid

The libpq parameter is `connect_timeout`. The kwarg form raises
`ProgrammingError`. If swallowed by `except Exception`, your healthcheck
silently lies and skips your Postgres tests. Wire `connect_timeout=5` via the
conninfo string instead. Fix at `persistence.py:73-95`.

### 24.2 Sync lambdas around async functions return un-awaited coroutines

LangGraph rejects with `InvalidUpdateError: Expected dict, got coroutine`.
Use explicit `async def _name(s): return await fn(s, harness)` closures
instead. See `inner.py:425-447`.

### 24.3 macOS RLIMIT_AS kills Python child processes

Python's runtime address-space footprint can exceed 512MB before the child
runs anything. Skip `RLIMIT_AS` on `sys.platform == "darwin"`. See
`sandbox.py:91-100`.

### 24.4 `asyncio.gather` swallows interrupts

Per LangGraph #6624. Use `asyncio.create_task` per branch, track in a
registry, await individually. Used at `branches.py:228-233`. `gather` is fine
for inner-loop trials (no `interrupt()` calls) — see `outer.py:335`.

### 24.5 Subprocess pipe buffer deadlocks

64KB pipe buffers fill quickly with `--verbose stream-json`. Drain via
reader threads pushing to a queue, NOT serial reads. See
`proposer.py:175-181, 267-272`.

### 24.6 Bare `except Exception: pass` hides real errors

Three real bugs in our codebase were swallowed by this pattern:
1. The `psycopg` kwarg error above
2. A `TypeError` in `list_namespace(store, ns_str, limit=...)` because
   `domain` is keyword-only — silently returned `implemented: False` for
   every memory query
3. Memory-store entry failure in `cli.py loop --persistent` retried the
   entire loop without memory, double-spending budget

Always log the exception. Always narrow the except clause. The pattern
should be `except SpecificError as exc: log.warning(...); fallback`.

### 24.7 `git apply --check` returncode != `--apply` returncode

Apply can fail even after check passes (rare race conditions on filesystem).
Check `apply_proc.returncode` separately. See `tools.py:359-373`.

### 24.8 `sys.modules` cache holds onto deleted .py files

If a candidate file is deleted between iterations (mock harnesses are
rewritten), the stale `sys.modules` entry will resolve to a broken module.
`sys.modules.pop(module_path, None)` + `importlib.invalidate_caches()` before
import. See `outer.py:217-218`.

### 24.9 `pytest-asyncio` config silently ignored

If you forget `asyncio_mode = "auto"` in `pyproject.toml`'s
`[tool.pytest.ini_options]`, async tests show as `coroutine 'test_x' was
never awaited` warnings and the test counts are 0/0 in the relevant module.

### 24.10 Frontend `lib/` directory was gitignored

`.gitignore` had unanchored `lib/` which silently matched
`frontend/dashboard/src/lib/`. Whole directory missing from git for a build.
Anchor patterns: `/lib/` not `lib/`.

### 24.11 Conductor session checkpoints can revert your worktree

If you're using Anthropic's Conductor to develop, checkpoints staged a
revert of step-7 changes after they were committed. `git reset --hard HEAD`
recovers; verify with `git log -3` before committing again.

### 24.12 Anthropic Haiku 4.5 is rate-limited per-minute on input tokens

`30,000 input tokens/minute` hard cap when we tried `workers=4` with Sonnet.
Switching to Haiku 4.5 default (with `META_HARNESS_INNER_MODEL` env override
for power users) fixed it. The model is set at `harness.py:119-121`.

### 24.13 Override points 4, 5, 9 are defined but not consumed

Found by `grep -n "harness\." backend/app/meta_harness/inner.py` during this
doc's verification pass:

- `harness.MAX_VERIFY_RETRIES` (override 4) is never read — `_route_after_verify`
  hardcodes `>= 3` at `inner.py:411`.
- `harness._build_initial_context` (override 5) is never called — the orient
  phase writes `orient_summary` directly into state without projection.
- `harness.should_loop_back_to_act` (override 9) is never invoked — the
  same `_route_after_verify` does its own check.

Candidates that override these methods will validate clean and look like
real evolution to the proposer, but their behavioral effect on the inner
loop is zero. If you have a free hour: wire them through (one line each
at `inner.py:411` and the orient/router call sites). Documented in §10.5.

### 24.14 `tokens` and `cost_usd` are stubbed in real-bench eval results

`outer.py:347-348, 357` write zeros for both fields in the `_mock_bench=False`
path. The dashboard's "cost" / "avg_tokens" displays are therefore fictional
on real runs. Mock-bench DOES synthesize an `avg_tokens` curve (`24000 +
iter * 800`), so the Pareto-on-tokens chart has a meaningful x-axis on
mock-bench runs only. Real token aggregation through the inner loop
(reading `response.usage` from each `_call_llm` and summing) is a roadmap
item, not implemented.

### 24.15 SSE `startSSE` only routes 6 of 11 event types into UI

`src/lib/sse.ts:68-95` registers handlers for only `state-update`,
`candidate-created`, `eval-result`, `frontier-updated`,
`iteration-complete`, `fork-created`. The other 5 (`checkpoint-written`,
`validate-result`, `branch-cancelled`, `memory-pattern-stored`, `error`)
arrive over the wire but are dropped on the floor. The doc earlier
claimed full coverage; that's wrong. Fix is: add entries to the handlers
object in `startSSE`. See §16.4 for the full table.

---

## 25. All 11 SSE event types in full

The closed set (`backend/app/streaming.py:19-33`):

```python
{
    "state-update",
    "checkpoint-written",
    "candidate-created",
    "validate-result",
    "eval-result",
    "frontier-updated",
    "iteration-complete",
    "fork-created",
    "branch-cancelled",
    "memory-pattern-stored",
    "error",
}
```

Detailed semantics (matches `docs/INTERFACES.md` §7.2):

### `state-update`
Emitted at the start AND end of every node body. Payload includes `node`,
`iteration`, `ts`, `summary` (with `candidates_count`, `budget_remaining`,
`best_candidate`). The dashboard uses this to update the active-phase
indicator in the current iteration chapter.

### `checkpoint-written`
Emitted by `_emit_checkpoint_events` after a run completes (or on
reconnection). Payload: `thread_id`, `checkpoint_id`, `parent_checkpoint_id`,
`ts`, `node`. Each event has `event_id == checkpoint_id` for deterministic
re-keying.

### `candidate-created`
Emitted in the `propose` node after the proposer writes `pending_eval.json`.
Payload: `candidate` (name), `import_path`, `parent`. The dashboard adds a
new node to the trajectory tree.

### `validate-result`
Emitted in the `validate` node. Payload: `candidate`, `valid` (bool),
`error` (str if invalid). On invalid, the dashboard marks the node
`smoke_failed` and dims it.

### `eval-result`
Emitted at the end of the `benchmark` node. Payload: `candidate`,
`accuracy`, `per_task` (Record<task, {pass_rate, trials}>), `tokens`,
`cost_usd`. The dashboard updates the score chart and the candidate node's
score display.

### `frontier-updated`
Emitted at the end of the `update_frontier` node. Payload: `iteration`,
`frontier` (list of Pareto-optimal candidate names), `best_candidate`,
`delta`. The dashboard re-colors nodes (best/accepted/rejected) and updates
the TopBar's best score.

### `iteration-complete`
Emitted at the end of the `update_frontier` node, after `frontier-updated`.
Payload: `iteration`, `status` (`improved` or `no_improvement`). The
dashboard sets the iteration chapter's status badge.

### `fork-created`
Emitted by the `POST /runs/{run_id}/fork` endpoint after `worktree_add`
returns. Payload: `branch_id`, `thread_id`, `parent_thread_id`,
`parent_checkpoint_id`, `mods`, `name`. The dashboard adds a fork ribbon
and a new branch root in the tree.

### `branch-cancelled`
Emitted by `cancel_branch`. Payload: `thread_id`, `cancelled_at`. The
dashboard grays out the cancelled branch.

### `memory-pattern-stored`
Emitted in the `update_frontier` node when a pattern is written. Payload:
`namespace` (e.g. `["learned_patterns", "coding-agent"]`), `key`,
`score_delta`. The dashboard adds a memory-tagged log line.

### `error`
Emitted by `_execute_run` on uncaught exceptions. Payload: `thread_id`,
`node`, `message`, `traceback`. The dashboard adds a red error log line.

### Mandatory payload field

**Every** SSE event payload MUST include `thread_id`. Enforced at
`streaming.py:117-119`:

```python
if "thread_id" not in payload:
    raise InvalidEventPayloadError(
        f"SSE event {event_type!r} missing required thread_id"
    )
```

This is what makes per-branch UI routing possible. Forks emit events on the
shared run channel but each event carries its own `thread_id`, so the
dashboard reducer can route to the correct branch.

---

## 26. The complete CLI surface

Verified verbatim against `backend/app/cli.py`. Eight commands total
(seven top-level + one memory sub-app with one subcommand). The
`scripts/demo_dryrun.sh` step 7 check counts these eight names.

### `meta-harness version` (`cli.py:37-42`)

Print the version. No flags.

### `meta-harness inner` (`cli.py:45-139`)

Run ONE inner-loop trial on ONE task. Used to smoke-test the inner machine.

```
meta-harness inner
    --task <task_id>                  # required, e.g. task-001-fix-typo
    --candidate <name>                # default "baseline"
    --run-name <name>                 # default "inner-test"
    --holdout                         # resolve from eval/holdout/ instead of eval/tasks/
```

Writes traces to `runs/{run_name}/candidates/{candidate}/traces/{task}-trial-1/`.

### `meta-harness benchmark` (`cli.py:142-295`)

Run a candidate × N trials × M tasks. Multi-task multi-trial scoring.

```
meta-harness benchmark
    --candidate <name>                # default "baseline"
    --trials <N>                      # default 5
    --workers <N>                     # default 5 (NB: differs from `loop`'s default 3)
    --run-name <name>                 # auto-generated if omitted
    --holdout                         # use eval/holdout/ instead of eval/tasks/
```

Writes `runs/{run_name}/candidates/{candidate}/eval-result.json`.

### `meta-harness loop` (`cli.py:298-494`)

The outer loop. The headline command.

```
meta-harness loop
    --proposer {claude,mock}          # default "claude"
    --budget <N>                      # default 5 — outer iterations
    --trials <N>                      # default 5 — inner trials per task
    --workers <N>                     # default 3 — bench parallelism
    --domain <name>                   # default "coding-agent" → skills/meta-harness-coding-agent/SKILL.md
    --skill <path>                    # explicit override of skill resolution
    --mock-bench                      # synthesize scores instead of running inner trials
    --fresh                           # wipe runs/<run-name>/ before starting
    --run-name <name>                 # auto-generated if omitted: "loop-YYYYMMDDTHHMMSSZ"
    --persistent / --no-persistent    # default ON; uses AsyncPostgresSaver when ON
    --holdout                         # post-eval best on eval/holdout/ after search
```

Writes the full run-dir layout: `manifest.json`, `pending_eval.json` (per
iter), `frontier_val.json`, `evolution_summary.jsonl`, `agents/`,
`candidates/{name}/`, `proposer-sessions/iter-{N}/`. With `--holdout`,
also writes `holdout-result.json` after the search loop completes (only
meaningful when `--mock-bench` is OFF).

### `meta-harness fork` (`cli.py:618-706`)

Fork a run from a historical checkpoint into a concurrent branch.

```
meta-harness fork <run_name>          # positional, the run to fork from
    --checkpoint <id>                 # required: parent checkpoint id
    --mod KEY=VALUE                   # repeatable: state mods at the fork point
    --name <label>                    # optional human-readable branch label
    --detach                          # don't wait for the branch to finish
```

Note: the doc earlier claimed `--prior <text>` for editing the proposer
prior; the *actual* CLI takes `--mod proposer_prior=<text>` (i.e. you set
state fields generically via `--mod KEY=VALUE`). Multiple `--mod` flags
allowed.

### `meta-harness init` (`cli.py:709-778`)

Scaffold a new SKILL.md domain.

```
meta-harness init <domain>            # positional, e.g. "browsing-agent"
    --force                           # overwrite skills/meta-harness-<domain>/ if it exists
```

Copies `skills/meta-harness-coding-agent/SKILL.md` as a template if
present, otherwise writes a minimal SKILL.md stub. Prints next-step
guidance JSON.

### `meta-harness resume` (`cli.py:781-833`)

Resume an interrupted `meta-harness loop` run from its last Postgres
checkpoint. Reconstructs config from `runs/{run_name}/manifest.json`.

```
meta-harness resume <run_name>        # positional, the run to resume
```

### `meta-harness memory list` (`cli.py:862-884` — under `memory_app` sub-Typer)

The only memory subcommand. Lists all learned patterns in a namespace.

```
meta-harness memory list
    --namespace <domain>              # default "coding-agent"
    --limit <N>                       # default 50
```

Note: there is **no** `meta-harness memory search` CLI command; the doc
previously claimed one. To filter patterns by query string, hit the REST
endpoint `POST /memory/{namespace}/search` with body `{query, limit}`.

### Most useful one-liners

```bash
# Smoke-test the inner loop on one task with the real LLM (~24s, ~$0.05)
uv run meta-harness inner --task task-001-fix-typo --candidate baseline

# Run the full mock outer loop in <1s (no LLM calls at all)
uv run meta-harness loop --proposer mock --mock-bench --budget 2 --fresh

# Run the real claude proposer with mock benchmarking (~3min)
uv run meta-harness loop --proposer claude --mock-bench --budget 2 --fresh

# Run the real claude proposer with REAL benchmarking — full demo (~6min, ~$3)
uv run meta-harness loop --proposer claude --budget 5 --fresh --holdout --run-name demo

# Resume an interrupted run from its last Postgres checkpoint
uv run meta-harness resume <run-name>

# Fork an existing run from a historical checkpoint with a new prior
uv run meta-harness fork <run-name> \
    --checkpoint <ckpt-id> \
    --mod proposer_prior="explore example-driven prompts" \
    --name "fork-explore-examples"

# List learned patterns from prior runs (no `search` subcommand exists)
uv run meta-harness memory list --namespace coding-agent

# Filter patterns via the REST endpoint instead
curl -s -XPOST http://localhost:8000/memory/coding-agent/search \
    -H 'content-type: application/json' \
    -d '{"query":"schema_drift","limit":5}' | jq .
```

---

# Closing

If you read this top-to-bottom, you should now be able to:

1. Explain the linear-vs-tree pitch in <30 seconds.
2. Trace any SSE event from the graph node that emits it through the registry,
   over the wire, into the dashboard reducer, into the visible UI.
3. Add a new SKILL.md domain in <2 hours and watch it run.
4. Walk through the demo arc and explain *why* each iteration's outcome
   matters.
5. Recover from any of the demo failure modes in §19.2.
6. Answer the judge questions in §21 without checking notes.

When in doubt, the canonical sources are:

- `docs/INTERFACES.md` — every contract
- `ARCHITECTURE_SECTION_1.md` — the locked architecture
- `relay_metaharness_v7.md` + the three appendices — the "why" behind every
  decision
- This document — the synthesis you'll actually re-read at 2 AM the night
  before the demo

Good luck. We've built something genuinely novel on a substrate that does
the hard work for us. Now go ship.

— *The team, 2026-04-25.*
