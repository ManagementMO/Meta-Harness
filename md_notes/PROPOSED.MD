# RELAY — Meta-Harness on LangGraph

## The Three Layers

```
┌─────────────────────────────────────────────┐
│  OUTER LOOP (LangGraph StateGraph)          │
│  Job: orchestrate evolution + checkpoints   │
│  Runs: ~20 iterations                       │
│  Enables: rewind, fork, concurrent branches │
│                                             │
│  Each iteration calls ↓                     │
├─────────────────────────────────────────────┤
│  PROPOSER AGENT (Claude Code / LLM)        │
│  Job: read traces + scores, write new code  │
│  Reads: prior candidates' source + traces   │
│  Writes: a new coding agent harness file    │
│                                             │
│  Produces a candidate that runs ↓           │
├─────────────────────────────────────────────┤
│  CODING AGENT (the harness being optimized) │
│  Job: solve actual coding tasks             │
│  Runs: once per (candidate × task × trial)  │
│  Scored: does the code pass tests?          │
└─────────────────────────────────────────────┘
```

The paper calls the bottom one "the harness" and the top one "the meta-harness."
Wrapping the top layer in LangGraph makes it a checkpointed state machine
instead of a flat `for` loop — which gives time-travel for free.

---

## LangGraph Integration — Full Design

### State Schema

Everything the outer loop needs to know lives in one TypedDict.
LangGraph checkpoints this entire object at every node boundary.

```python
from typing import TypedDict, Annotated
from langgraph.graph import add_messages  # for append-only lists

class MetaHarnessState(TypedDict):
    # ── Evolution tracking ──
    iteration: int                          # current iteration (1-indexed)
    max_iterations: int                     # when to stop

    # ── Frontier ──
    frontier: dict                          # best score per task
    # e.g. {"task_1": {"agent": "v3_error_recovery", "score": 0.85}}
    best_agent: str                         # name of overall best
    best_score: float                       # overall best pass rate

    # ── Current iteration state ──
    candidates: list[dict]                  # proposed candidates this iteration
    # each: {name, code_path, hypothesis, changes}
    valid_candidates: list[dict]            # candidates that passed validation
    benchmark_results: dict                 # {agent_name: {per_task_scores, avg}}

    # ── Experience buffer (the key insight from the paper) ──
    evolution_history: Annotated[list[dict], add_messages]
    # append-only log of every candidate ever tried:
    # {iteration, agent, score, delta, hypothesis, outcome}

    traces: dict
    # raw execution traces from coding agent runs:
    # {agent_name: {task_name: {stdout, stderr, code_produced,
    #               tests_passed, tests_failed, error_messages}}}
    # This is what the proposer reads. Paper shows this is the
    # single most important input (~50% → 34.6% without it).

    # ── Proposer context ──
    proposer_output: str                    # raw proposer response
    proposer_cost: float                    # tokens/cost tracking
```

**Why `add_messages` on `evolution_history`**: LangGraph's reducer annotation
means each node *appends* to history rather than overwriting it. When you fork
from a checkpoint, the fork inherits all history up to that point and diverges
from there — exactly the semantics you want.

### The State Graph

```
         ┌──────────┐
         │  START    │
         └────┬─────┘
              │
              ▼
     ┌────────────────┐
     │    propose      │  ← Proposer agent reads traces + frontier,
     │                 │    writes new candidate harness code
     └───────┬────────┘
             │
             ▼
     ┌────────────────┐
     │   validate      │  ← Import-check + smoke-test each candidate
     │                 │    Filters down to valid_candidates
     └───────┬────────┘
             │
             ▼
     ┌────────────────┐
     │   benchmark     │  ← Run each valid candidate on coding tasks
     │                 │    Collect traces + scores
     └───────┬────────┘
             │
             ▼
     ┌────────────────┐
     │ update_frontier │  ← Compare to frontier, update best,
     │                 │    append to evolution_history
     └───────┬────────┘
             │
             ▼
        ┌─────────┐     ─── iteration < max? ──→ back to propose
        │ continue?│
        └────┬────┘     ─── done ──→ END
             │
             ▼
         ┌──────┐
         │  END  │
         └──────┘
```

Every arrow is a checkpoint boundary. At each `─→`, LangGraph writes
the full state to Postgres. That means you can rewind to any of:
- Right before the proposer ran (see what it was given)
- Right after proposal (see what it proposed before validation)
- Right after validation (see what survived)
- Right after benchmark (see raw scores + traces)
- Right after frontier update (see the decision)

### Graph Construction

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

workflow = StateGraph(MetaHarnessState)

# Add nodes
workflow.add_node("propose", propose_node)
workflow.add_node("validate", validate_node)
workflow.add_node("benchmark", benchmark_node)
workflow.add_node("update_frontier", update_frontier_node)

# Add edges
workflow.set_entry_point("propose")
workflow.add_edge("propose", "validate")
workflow.add_edge("validate", "benchmark")
workflow.add_edge("benchmark", "update_frontier")

# Conditional: loop or end
workflow.add_conditional_edges(
    "update_frontier",
    should_continue,           # returns "propose" or END
    {"propose": "propose", END: END},
)

# Compile with Postgres checkpointing
async with AsyncPostgresSaver.from_conn_string(POSTGRES_URL) as saver:
    await saver.setup()
    graph = workflow.compile(checkpointer=saver)
```

### Node Implementations

Each node is an async function: `State → partial State update`.

#### Node 1: `propose`

The proposer reads the experience buffer and writes new harness code.
This maps directly to the paper's `propose_claude()` function.

```python
async def propose_node(state: MetaHarnessState) -> dict:
    """Call the proposer agent to generate new candidate harness code."""

    # Build the proposer's context — everything it needs to see
    context = build_proposer_context(
        frontier=state["frontier"],
        evolution_history=state["evolution_history"],
        traces=state["traces"],          # ← THE KEY INPUT
        iteration=state["iteration"],
    )

    # Option A: Call Claude Code via subprocess (like the paper)
    result = await asyncio.to_thread(
        claude_wrapper.run,
        prompt=context,
        model="opus",
        allowed_tools=["Read", "Write", "Edit", "Bash", "Grep"],
        skills=["meta-harness-coding-agent"],
        effort="max",
    )

    # Option B: Call an LLM directly via LangGraph's tool-calling
    # (simpler for hackathon, less powerful)
    # result = await llm.ainvoke(context)

    # Parse proposed candidates from the output
    candidates = parse_candidates(result)

    return {
        "candidates": candidates,
        "proposer_output": result.text,
        "proposer_cost": result.cost_usd,
    }
```

**What `build_proposer_context` includes** (matching the paper's finding
that raw traces are the #1 input):

```python
def build_proposer_context(frontier, evolution_history, traces, iteration):
    sections = []

    # 1. Current frontier (best agent per task)
    sections.append(f"## Frontier (iteration {iteration})")
    sections.append(json.dumps(frontier, indent=2))

    # 2. Evolution history (what's been tried, what worked)
    sections.append("## Evolution History")
    for entry in evolution_history[-10:]:  # last 10 candidates
        sections.append(
            f"- {entry['agent']}: {entry['score']:.1%} "
            f"(delta={entry['delta']:+.1%}) — {entry['hypothesis']}"
        )

    # 3. RAW TRACES — the paper's key finding
    # Not summaries. Not scores. The actual stdout/stderr/errors.
    sections.append("## Execution Traces (most recent candidates)")
    for agent_name, task_traces in traces.items():
        sections.append(f"### Agent: {agent_name}")
        for task_name, trace in task_traces.items():
            sections.append(f"#### Task: {task_name}")
            if not trace["tests_passed"]:
                # Failed tasks are most informative
                sections.append(f"Error: {trace['error_messages']}")
                sections.append(f"Code produced:\n```\n{trace['code_produced']}\n```")
                sections.append(f"Test output:\n{trace['stderr'][:2000]}")

    # 4. The coding agent's current source code
    sections.append("## Current Best Agent Source")
    sections.append(f"```python\n{read_agent_source(frontier['best_agent'])}\n```")

    return "\n\n".join(sections)
```

#### Node 2: `validate`

```python
async def validate_node(state: MetaHarnessState) -> dict:
    """Import-check and smoke-test each candidate."""
    valid = []
    for candidate in state["candidates"]:
        # 1. Can it import?
        proc = await asyncio.create_subprocess_exec(
            "python", "-c",
            f"from agents.{candidate['name']} import CodingAgent; print('OK')",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            continue

        # 2. Smoke test on one trivial task
        smoke_result = await run_coding_task(
            agent_name=candidate["name"],
            task=SMOKE_TASK,  # e.g. "write a function that adds two numbers"
            timeout=60,
        )
        if smoke_result["passed"]:
            valid.append(candidate)

    return {"valid_candidates": valid}
```

#### Node 3: `benchmark`

```python
async def benchmark_node(state: MetaHarnessState) -> dict:
    """Run each valid candidate on the full task suite. Collect traces."""
    results = {}
    all_traces = {}

    for candidate in state["valid_candidates"]:
        agent_results = {}
        agent_traces = {}

        # Run all tasks concurrently (I/O bound — waiting on LLM)
        tasks = [
            run_coding_task(candidate["name"], task)
            for task in TASK_SUITE
        ]
        task_results = await asyncio.gather(*tasks)

        for task, result in zip(TASK_SUITE, task_results):
            agent_results[task["name"]] = result["score"]
            agent_traces[task["name"]] = {
                "code_produced": result["code"],
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "tests_passed": result["tests_passed"],
                "tests_failed": result["tests_failed"],
                "error_messages": result["errors"],
                "latency_s": result["latency"],
            }

        avg_score = sum(agent_results.values()) / len(agent_results)
        results[candidate["name"]] = {
            "per_task": agent_results,
            "avg": avg_score,
        }
        all_traces[candidate["name"]] = agent_traces

    return {
        "benchmark_results": results,
        "traces": all_traces,  # stored in state → proposer reads next iteration
    }
```

#### Node 4: `update_frontier`

```python
async def update_frontier_node(state: MetaHarnessState) -> dict:
    """Update frontier with best results. Append to evolution history."""
    frontier = dict(state["frontier"])
    new_history_entries = []

    for agent_name, result in state["benchmark_results"].items():
        avg = result["avg"]
        delta = avg - state["best_score"]

        # Update per-task frontier
        for task_name, score in result["per_task"].items():
            current_best = frontier.get(task_name, {}).get("score", 0)
            if score > current_best:
                frontier[task_name] = {"agent": agent_name, "score": score}

        # Find the candidate's hypothesis
        hypothesis = ""
        for c in state["valid_candidates"]:
            if c["name"] == agent_name:
                hypothesis = c.get("hypothesis", "")
                break

        new_history_entries.append({
            "iteration": state["iteration"],
            "agent": agent_name,
            "score": round(avg, 3),
            "delta": round(delta, 3),
            "hypothesis": hypothesis,
            "outcome": f"{avg:.1%} ({delta:+.1%})" if avg > 0 else "failed",
        })

    # Determine new best
    best_agent = state["best_agent"]
    best_score = state["best_score"]
    for agent_name, result in state["benchmark_results"].items():
        if result["avg"] > best_score:
            best_score = result["avg"]
            best_agent = agent_name

    return {
        "frontier": frontier,
        "best_agent": best_agent,
        "best_score": best_score,
        "evolution_history": new_history_entries,  # appended via add_messages
        "iteration": state["iteration"] + 1,
    }
```

#### Conditional Edge: `should_continue`

```python
def should_continue(state: MetaHarnessState) -> str:
    if state["iteration"] >= state["max_iterations"]:
        return END
    return "propose"
```

### Time-Travel Operations

Because every node boundary is a Postgres checkpoint, you get these for free:

#### Rewind (inspect any past state)

```python
# List all checkpoints for a run
config = {"configurable": {"thread_id": run_id}}
checkpoints = [cp async for cp in graph.aget_state_history(config)]

# Each checkpoint has:
# - checkpoint_id
# - the full MetaHarnessState at that moment
# - which node just ran
# - timestamp

# Inspect state at iteration 3, right after benchmark:
for cp in checkpoints:
    if (cp.values["iteration"] == 3
        and cp.metadata.get("source") == "loop"
        and cp.metadata.get("step_name") == "benchmark"):
        print(cp.values["benchmark_results"])
        print(cp.values["traces"])  # full execution traces
```

#### Fork (branch from a checkpoint with modified state)

This is the killer feature. "What if the proposer had different
constraints at iteration 3?"

```python
async def fork_from_checkpoint(
    graph,
    parent_thread_id: str,
    checkpoint_id: str,
    state_mods: dict,
) -> str:
    """Fork a new branch from any checkpoint with modified state."""

    new_thread_id = f"{parent_thread_id}.fork.{uuid.uuid4().hex[:8]}"

    # Write the modified state as a new checkpoint on the new thread
    fork_config = {
        "configurable": {
            "thread_id": new_thread_id,
            "checkpoint_id": checkpoint_id,
        }
    }
    fork_config = await graph.aupdate_state(fork_config, state_mods)

    # Resume execution from the forked state
    task = asyncio.create_task(
        graph.ainvoke(None, config=fork_config),
        name=f"branch:{new_thread_id}",
    )

    return new_thread_id, task
```

**Example fork operations:**

```python
# Fork 1: "What if we forced the proposer to focus on error recovery?"
await fork_from_checkpoint(graph, run_id, checkpoint_at_iter_3, {
    "proposer_constraints": "Focus only on error recovery and retry logic",
})

# Fork 2: "What if we reset the frontier and let it re-explore?"
await fork_from_checkpoint(graph, run_id, checkpoint_at_iter_5, {
    "frontier": {},  # wipe frontier, force re-exploration
    "best_score": 0.0,
})

# Fork 3: "What if we gave the proposer different traces?"
await fork_from_checkpoint(graph, run_id, checkpoint_at_iter_2, {
    "traces": curated_traces,  # hand-picked failure cases
})
```

#### Concurrent Branches

Two forks running simultaneously, both streaming to the dashboard:

```python
# Fork from iteration 3 with two different strategies
thread_a, task_a = await fork_from_checkpoint(
    graph, run_id, iter3_checkpoint,
    {"proposer_constraints": "Focus on prompt engineering"},
)
thread_b, task_b = await fork_from_checkpoint(
    graph, run_id, iter3_checkpoint,
    {"proposer_constraints": "Focus on tool selection"},
)

# Both run concurrently — asyncio handles the I/O interleaving
# Dashboard shows two branches growing from the same fork point
await asyncio.gather(task_a, task_b)
```

### The Dashboard View

What the user sees:

```
Iteration:  1 ──── 2 ──── 3 ──── 4 ──── 5
Score:     .42    .51    .58    .55    .62   ← main branch
                          │
                          └──── 3' ──── 4'
                               .61    .68   ← fork (prompt focus)

[Rewind] [Fork] [Compare] [Cancel Branch]

─────────────────────────────────────────
Selected: Iteration 3 → 3' (fork)

Proposer hypothesis: "Adding explicit error message parsing
to the retry loop will catch 3 currently-failing tasks"

Traces (failed tasks):
  task_07: TypeError at line 23 — agent didn't handle None return
  task_12: Timeout — agent stuck in infinite retry loop
  task_15: Wrong output format — tests expected JSON, got plain text

[View full trace] [View agent code] [View diff from parent]
```

### What This Adds Over the Paper

| Paper (flat loop)                  | RELAY (LangGraph)                              |
|------------------------------------|-------------------------------------------------|
| Re-run from scratch to try new approach | Fork from any iteration, keep both branches   |
| Can't inspect intermediate state   | Every node boundary is inspectable              |
| Sequential only                    | Concurrent branches via asyncio                 |
| Filesystem is the experience buffer | Checkpoint state IS the experience buffer       |
| CLI output only                    | Live dashboard with SSE streaming               |
| No undo                           | Rewind to any checkpoint                        |

### Coding Agent Interface

The bottom layer — the thing being optimized. Each candidate is a Python
file implementing this interface:

```python
class CodingAgent:
    """Interface that every candidate harness must implement."""

    async def solve(self, task: dict) -> dict:
        """
        Given a coding task, produce a solution.

        Args:
            task: {
                "name": str,
                "description": str,      # natural language problem statement
                "test_code": str,         # test cases to pass
                "language": str,          # "python", "javascript", etc.
                "starter_code": str,      # optional template
            }

        Returns: {
            "code": str,                  # the solution code
            "reasoning": str,             # agent's thought process
            "tools_used": list[str],      # which tools it called
            "iterations": int,            # how many attempts
        }
        """
        ...
```

The proposer evolves HOW this agent works internally:
- What system prompt it uses
- What tools it has access to (file read, web search, test runner, etc.)
- How it handles errors (retry strategy, error parsing)
- How it plans (upfront plan vs. iterative)
- How it manages context (what to keep, what to drop)

### Task Suite for Evaluation

For the hackathon demo, keep this small and fast:

```python
TASK_SUITE = [
    {"name": "two_sum", "difficulty": "easy", ...},
    {"name": "parse_csv", "difficulty": "medium", ...},
    {"name": "async_rate_limiter", "difficulty": "hard", ...},
    {"name": "binary_tree_serialize", "difficulty": "medium", ...},
    {"name": "regex_engine", "difficulty": "hard", ...},
]

SMOKE_TASK = TASK_SUITE[0]  # two_sum — fast, reliable
```

5 tasks × 2 trials = 10 coding agent runs per candidate.
With ~30s per run, one full benchmark takes ~5 minutes.
3 iterations = 15 minutes of evolution for the live demo.