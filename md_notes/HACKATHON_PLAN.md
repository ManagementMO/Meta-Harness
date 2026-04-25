# RELAY — 20-Hour Hackathon Build Plan

**Start**: Now (Fri noon)
**Deadline**: Sat 8am (~20 hours)
**Team**: Split work by layer. Layers are independent until integration.

---

## What We're Building

A Meta-Harness for coding agents on LangGraph with time-travel.
The outer loop evolves a coding agent's scaffold (prompt, tools, error handling).
The user can rewind to any iteration, fork with different constraints, and
watch concurrent branches evolve in real time.

## What We're NOT Building

- Full Claude Code subprocess proposer (too slow for demo, use direct LLM call)
- Complex coding agent with tools (just LLM → code → run tests)
- Production-grade anything (SQLite checkpointer is fine, skip Postgres)
- Auth, deployment, multi-tenant

---

## The Stack

```
Frontend:    React + Tailwind (Vite)
Backend:     FastAPI + SSE
Orchestrator: LangGraph StateGraph + MemorySaver (or SQLite)
Proposer:    Claude API (direct call, not subprocess)
Coding Agent: Claude API → produces code → subprocess runs pytest
Tasks:       5 hand-written Python problems with test suites
```

---

## Phase 1: Skeleton (4 hours) — Fri noon → 4pm

**Goal**: The outer loop runs end-to-end in the terminal. No UI. No time-travel.
Just: propose → validate → benchmark → update → loop.

### 1A: Task Suite + Evaluator (1 hour)

Create 5 coding tasks with pytest test files. Keep them fast (<10s each).

```
tasks/
├── two_sum/
│   ├── prompt.md          # "Write a function that..."
│   └── test_solution.py   # pytest tests
├── flatten_list/
│   ├── prompt.md
│   └── test_solution.py
├── parse_csv/
│   ├── prompt.md
│   └── test_solution.py
├── lru_cache/
│   ├── prompt.md
│   └── test_solution.py
└── rate_limiter/
    ├── prompt.md
    └── test_solution.py
```

The evaluator:
```python
async def run_coding_task(agent_code: str, task: dict) -> dict:
    """Write agent's code to temp file, run pytest, return results."""
    # 1. Write solution.py to a temp dir
    # 2. Copy test_solution.py alongside it
    # 3. Run: pytest test_solution.py --tb=short -q
    # 4. Parse pass/fail count from output
    # 5. Return {score, stdout, stderr, code, tests_passed, tests_failed}
```

**Deliverable**: `python -m pytest tasks/two_sum/test_solution.py` works
with a hand-written solution.

### 1B: Coding Agent (1 hour)

The simplest possible coding agent. One LLM call.

```python
# relay/coding_agent.py

async def solve(task: dict, system_prompt: str, config: dict) -> dict:
    """The harness being optimized. system_prompt + config are what evolve."""
    response = await anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": task["prompt"]}],
        temperature=config.get("temperature", 0.0),
    )
    code = extract_code_block(response.content[0].text)
    return {"code": code, "reasoning": response.content[0].text}
```

The default harness is just a system prompt:
```python
DEFAULT_SYSTEM_PROMPT = """You are a Python coding assistant.
Write a solution to the given problem.
Return ONLY the code in a ```python``` code block.
No explanation needed."""
```

The proposer will evolve this system prompt + add things like:
- "Always write test cases first"
- "Parse the error message and fix the specific line"
- "Break the problem into steps before coding"
- retry logic, error parsing, multi-attempt strategies

**Deliverable**: `coding_agent.solve(task)` returns code that can be
evaluated by the task runner.

### 1C: Proposer Agent (1 hour)

Direct Claude API call. Reads traces + scores, outputs new harness config.

```python
# relay/proposer.py

PROPOSER_PROMPT = """You are evolving a coding agent's scaffold.

## Current Frontier
{frontier}

## Evolution History
{history}

## Execution Traces (CRITICAL — read these carefully)
{traces}

## Current Best Agent Config
```python
{current_config}
```

## Your Job
Analyze WHY the agent failed on specific tasks. Look at the actual error
messages and code produced. Then propose a NEW agent configuration that
addresses the failure modes.

Return JSON:
{{
  "name": "descriptive_snake_case_name",
  "hypothesis": "one sentence, falsifiable",
  "system_prompt": "the new system prompt for the coding agent",
  "config": {{
    "temperature": 0.0,
    "max_retries": 1,
    "parse_errors": true/false,
    ...
  }},
  "changes": "what you changed and why"
}}
"""

async def propose(state: MetaHarnessState) -> dict:
    response = await anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{"role": "user", "content": PROPOSER_PROMPT.format(...)}],
    )
    return parse_candidate(response)
```

**Deliverable**: Given fake traces/scores, proposer outputs a valid candidate JSON.

### 1D: Wire the Loop (1 hour)

Plain Python first. No LangGraph yet.

```python
# relay/loop.py

async def run_evolution(num_iterations=5):
    frontier = {}
    history = []
    traces = {}
    best_config = DEFAULT_CONFIG

    for i in range(num_iterations):
        # Propose
        candidate = await propose(frontier, history, traces, best_config)

        # Validate (can it produce code at all?)
        smoke = await run_coding_task(
            await solve(TASKS[0], candidate["system_prompt"], candidate["config"]),
            TASKS[0],
        )
        if smoke["score"] == 0:
            print(f"  Candidate {candidate['name']} failed smoke test, skip")
            continue

        # Benchmark
        results = {}
        all_traces = {}
        for task in TASKS:
            solution = await solve(task, candidate["system_prompt"], candidate["config"])
            result = await run_coding_task(solution["code"], task)
            results[task["name"]] = result["score"]
            all_traces[task["name"]] = result  # FULL traces

        avg = sum(results.values()) / len(results)
        traces = {candidate["name"]: all_traces}

        # Update frontier
        if avg > best_score:
            best_config = candidate
            best_score = avg

        history.append({...})
        print(f"  Iter {i}: {candidate['name']} = {avg:.0%}")
```

**Deliverable**: `python -m relay.loop` runs 3 iterations, scores improve
(or at least change). This proves the concept end-to-end.

---

## Phase 2: LangGraph + Time-Travel (4 hours) — Fri 4pm → 8pm

**Goal**: Refactor the loop into a LangGraph StateGraph with checkpointing.
Add rewind and fork operations.

### 2A: State Graph (2 hours)

Convert the flat loop from Phase 1 into the 4-node graph from PROPOSED.MD.

```python
# relay/graph.py

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver  # good enough for demo

workflow = StateGraph(MetaHarnessState)
workflow.add_node("propose", propose_node)
workflow.add_node("validate", validate_node)
workflow.add_node("benchmark", benchmark_node)
workflow.add_node("update_frontier", update_frontier_node)

workflow.set_entry_point("propose")
workflow.add_edge("propose", "validate")
workflow.add_edge("validate", "benchmark")
workflow.add_edge("benchmark", "update_frontier")
workflow.add_conditional_edges("update_frontier", should_continue)

checkpointer = MemorySaver()
graph = workflow.compile(checkpointer=checkpointer)
```

Test: `graph.invoke(initial_state, config={"configurable": {"thread_id": "run-1"}})`
runs through all iterations.

### 2B: Time-Travel API (2 hours)

FastAPI endpoints that wrap LangGraph's checkpoint operations.

```python
# relay/api.py

@app.get("/runs/{run_id}/history")
async def get_history(run_id: str):
    """List all checkpoints (iterations) for a run."""
    config = {"configurable": {"thread_id": run_id}}
    checkpoints = []
    async for cp in graph.aget_state_history(config):
        checkpoints.append({
            "checkpoint_id": cp.config["configurable"]["checkpoint_id"],
            "iteration": cp.values.get("iteration"),
            "best_score": cp.values.get("best_score"),
            "node": cp.metadata.get("source"),
            "timestamp": cp.metadata.get("created_at"),
        })
    return checkpoints

@app.get("/runs/{run_id}/state/{checkpoint_id}")
async def get_state(run_id: str, checkpoint_id: str):
    """Inspect full state at any checkpoint."""
    config = {"configurable": {"thread_id": run_id, "checkpoint_id": checkpoint_id}}
    state = await graph.aget_state(config)
    return state.values

@app.post("/runs/{run_id}/fork")
async def fork(run_id: str, body: ForkRequest):
    """Fork from a checkpoint with modified state."""
    new_thread = f"{run_id}.fork.{uuid.uuid4().hex[:8]}"
    fork_config = {"configurable": {"thread_id": new_thread, "checkpoint_id": body.checkpoint_id}}
    await graph.aupdate_state(fork_config, body.state_mods)
    task = asyncio.create_task(graph.ainvoke(None, config=fork_config))
    branch_registry[new_thread] = task
    return {"thread_id": new_thread, "status": "running"}

@app.post("/runs")
async def start_run(body: RunRequest):
    """Start a new evolution run."""
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": run_id}}
    task = asyncio.create_task(graph.ainvoke(initial_state(body), config=config))
    branch_registry[run_id] = task
    return {"run_id": run_id}
```

**Deliverable**: Can curl the API to start a run, list checkpoints,
inspect state at iteration 2, fork from iteration 2 with different
proposer constraints.

---

## Phase 3: Dashboard (5 hours) — Fri 8pm → 1am

**Goal**: Visual dashboard showing the trajectory tree, scores, traces, and fork controls.

### 3A: SSE Streaming (1 hour)

Stream state updates to the frontend as the graph runs.

```python
@app.get("/runs/{run_id}/stream")
async def stream_run(run_id: str):
    async def event_generator():
        config = {"configurable": {"thread_id": run_id}}
        async for event in graph.astream_events(None, config=config, version="v2"):
            if event["event"] == "on_chain_end":
                yield f"data: {json.dumps(event['data'])}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### 3B: Trajectory Tree View (2 hours)

The main visual. Shows iterations as nodes, forks as branches.

```
Component: TrajectoryTree
- Horizontal timeline of iterations
- Each node shows: iteration #, agent name, score, delta
- Color: green if improved, red if regressed
- Click node → show details panel (traces, hypothesis, code diff)
- Fork lines branch off at fork points
- Active branches pulse/animate

Component: DetailsPanel
- Selected iteration's full state
- Tabs: [Hypothesis] [Traces] [Agent Code] [Diff from Parent]
- Traces tab shows per-task: pass/fail, error messages, code produced
```

Use a simple canvas or SVG for the tree. Don't overthink it — a horizontal
node graph with lines is enough.

### 3C: Controls (2 hours)

```
Component: ControlBar
- [New Run] button → starts evolution
- [Rewind] slider → scrub through iterations
- [Fork] button → opens modal:
    - "Fork from iteration: [dropdown]"
    - "Proposer constraint: [text input]"
    - e.g. "Focus on error handling" or "Try a multi-attempt strategy"
    - [Fork & Run] → calls POST /runs/{id}/fork
- [Compare] button → side-by-side two branches

Component: ScoreChart
- Line chart of score over iterations
- Multiple lines for multiple branches
- Updates live via SSE
```

**Deliverable**: Can watch a run evolve in real-time, click any iteration
to see traces, fork from iteration 2, watch the fork run alongside.

---

## Phase 4: Polish + Demo Prep (4 hours) — Sat 1am → 5am

### 4A: Make the Demo Reliable (2 hours)

- Run the full loop 3-5 times end-to-end. Fix any crashes.
- Tune the proposer prompt so it actually improves (not just random walks).
- Pre-seed a good run so the demo has a guaranteed fallback.
- Make sure fork actually produces different results.
- Add error boundaries everywhere (LLM timeout, pytest hang, etc.)

### 4B: Demo Script (1 hour)

The 90-second pitch:

```
Act 1 (20s): "This is a coding agent. It solves 2/5 tasks."
  → Show the baseline score

Act 2 (30s): "Meta-Harness evolves it automatically."
  → Start run, watch 3 iterations, score goes 40% → 70%
  → Click iteration 2, show the traces: "Here's WHY it failed task 3 —
    it didn't parse the error message. The proposer noticed and added
    error parsing in iteration 3."

Act 3 (30s): "But what if we tried a different approach?"
  → Rewind to iteration 2
  → Fork with constraint: "Try a plan-first strategy instead"
  → Watch both branches grow simultaneously
  → "Original branch: 70%. Fork: 80%. The fork found a better path."

Act 4 (10s): "This is time-travel for agent optimization.
  The Meta-Harness loop is no longer a sequence — it's a search tree."
```

### 4C: Visual Polish (1 hour)

- Dark theme (matches Cognition aesthetic)
- Smooth animations on the trajectory tree
- Score numbers animate up/down
- Loading states while LLM calls run
- Clean typography

---

## Phase 5: Buffer (3 hours) — Sat 5am → 8am

Murphy's law buffer. Use for:
- Fixing whatever broke overnight
- Re-recording demo if needed
- Writing the submission description
- Sleep (if everything works)

---

## Hour-by-Hour Summary

```
Fri 12:00  Phase 1A  Task suite + evaluator
    1:00   Phase 1B  Coding agent (single LLM call)
    2:00   Phase 1C  Proposer agent (direct API)
    3:00   Phase 1D  Wire the loop (plain Python)
    ─────  CHECKPOINT: loop runs in terminal  ──────
    4:00   Phase 2A  LangGraph state graph
    5:00   Phase 2A  (continued)
    6:00   Phase 2B  Time-travel API (FastAPI)
    7:00   Phase 2B  (continued)
    ─────  CHECKPOINT: API works, can fork via curl  ──────
    8:00   Phase 3A  SSE streaming
    9:00   Phase 3B  Trajectory tree view
   10:00   Phase 3B  (continued)
   11:00   Phase 3C  Controls (fork, rewind, compare)
   12:00   Phase 3C  (continued)
    ─────  CHECKPOINT: dashboard shows live evolution  ──────
Sat 1:00   Phase 4A  Make demo reliable
    2:00   Phase 4A  (continued)
    3:00   Phase 4B  Demo script + dry run
    4:00   Phase 4C  Visual polish
    ─────  CHECKPOINT: demo ready  ──────
    5:00   Phase 5   Buffer / fix / sleep
    6:00   Phase 5   Buffer / fix / sleep
    7:00   Phase 5   Buffer / fix / sleep
    8:00   SUBMIT
```

## Critical Path

If you're behind schedule, cut in this order:

1. **Cut concurrent branches** — sequential fork is fine for demo
2. **Cut the compare view** — just show one branch at a time
3. **Cut the score chart** — trajectory tree is enough
4. **Cut pytest evaluation** — fake the scores, focus on the UI + fork UX
5. **NEVER cut**: the fork operation. That's the whole demo.

## File Structure

```
relay/
├── backend/
│   ├── relay/
│   │   ├── __init__.py
│   │   ├── graph.py           # LangGraph state graph
│   │   ├── state.py           # MetaHarnessState TypedDict
│   │   ├── nodes.py           # propose, validate, benchmark, update
│   │   ├── proposer.py        # Claude API call for proposals
│   │   ├── coding_agent.py    # Claude API call for code generation
│   │   ├── evaluator.py       # run pytest, parse results
│   │   └── api.py             # FastAPI + SSE
│   ├── tasks/
│   │   ├── two_sum/
│   │   ├── flatten_list/
│   │   ├── parse_csv/
│   │   ├── lru_cache/
│   │   └── rate_limiter/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── TrajectoryTree.tsx
│   │   │   ├── DetailsPanel.tsx
│   │   │   ├── ControlBar.tsx
│   │   │   └── ScoreChart.tsx
│   │   └── hooks/
│   │       └── useSSE.ts
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

## Key Simplifications vs. the Paper

| Paper                          | Hackathon                          |
|--------------------------------|------------------------------------|
| Claude Code subprocess         | Direct Claude API call             |
| Filesystem experience buffer   | LangGraph state (in-memory)        |
| Full agent with tools          | Single LLM call → code → pytest   |
| 89 tasks, 2 trials each        | 5 tasks, 1 trial each             |
| 40-minute iterations           | 2-minute iterations               |
| Arbitrary Python code search   | System prompt + config evolution   |
| Postgres checkpointer          | MemorySaver (in-memory)           |
| Production error handling      | Crash = skip candidate            |

The simplifications make it demoable. The architecture is the same.
