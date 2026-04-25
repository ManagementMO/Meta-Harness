# Appendix A — Worktrees for Agents

*A small extension to the v7 plan: how to make linear and forked branches actually run in parallel, not just serially.*

---

## Why this exists

In v7 as written, a fork is sequential: rewind → run the fork → compare. The candidate trajectory tree grows in two directions on disk, but only one direction at a time on screen. That works, but it leaves a real demo beat on the table.

This appendix specifies the optimal way to add **true concurrent branches** — the agent-optimization equivalent of git worktrees, where multiple branches are simultaneously checked out and running. It's the difference between *"the loop is a tree"* and *"the loop is **demonstrably** a tree because both branches are growing on screen right now."*

Adopting this is **optional**. v7 still wins without it. But for the ~3 hours of incremental engineering, the demo beat upgrades meaningfully.

---

## A.1 The mental model

Git worktrees let multiple branches of the same repo be checked out at once into separate working directories, sharing one git database underneath. For RELAY, the equivalent is:

| Git | Meta-Harness |
|---|---|
| Repo | The optimization run (one parent thread) |
| Branches | Forked threads from a checkpoint |
| Worktrees | Concurrent in-flight branches, each running its own meta-harness loop |
| `.git/objects` | The shared `AsyncPostgresSaver` checkpoint store |
| `git worktree add` | `update_state(parent_ckpt, mods)` + spawn an async task |

The user thinks in branches. The system stores threads. Postgres handles transaction isolation. LangGraph handles state schemas. That's the whole stack.

---

## A.2 Why the obvious "use a worker pool" answer is wrong here

The first instinct is Celery + Redis: workers pick up branches off a queue, each worker runs one branch, results write back to Postgres. This works, but for a 36-hour build it's overkill for three reasons:

1. **A whole new infrastructure layer.** Redis broker, Celery workers, dead-letter queue, worker supervision. Each is a new failure mode.
2. **Cross-process state coordination.** Workers don't share Python process memory; cancellation, progress reporting, and SSE streaming to the dashboard all become harder.
3. **No actual parallelism win for our workload.** The bottleneck inside each branch is *waiting on LLM API calls* — that's I/O-bound, not CPU-bound. Async coroutines saturate the same wait time without the worker-pool overhead.

The right primitive for I/O-bound concurrent agent runs is **`asyncio.gather` over multiple `graph.ainvoke()` calls**, sharing one `AsyncPostgresSaver`. No new processes, no broker, just two async tasks awaiting LLM responses concurrently. Postgres handles the concurrent writes correctly because that's what Postgres does.

LangChain's own team has explicitly confirmed this pattern is safe: *"It is entirely safe to share a graph between executions, whether they happen concurrently or not, whether in same thread or not. No state is ever stored on the graph instance, and the graph instance isn't ever mutated in any way during any execution."* The only requirement is using the async-native checkpointer.

---

## A.3 The implementation

Five concrete pieces. Each one fits in one screen of code.

### Piece 1 — Use the async-native Postgres checkpointer

Swap `PostgresSaver` for `AsyncPostgresSaver`:

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async with AsyncPostgresSaver.from_conn_string(POSTGRES_URL) as saver:
    await saver.setup()  # create tables on first run
    graph = workflow.compile(checkpointer=saver)
    # graph.ainvoke / graph.astream now work concurrently
```

This is non-negotiable: the sync `PostgresSaver` will deadlock under concurrent use because it holds connections synchronously across `await` points in user nodes.

### Piece 2 — Connection pool sized for branches

The default Postgres connection limit will bite if you spawn many branches. Size the pool deliberately:

```python
from psycopg_pool import AsyncConnectionPool

pool = AsyncConnectionPool(
    POSTGRES_URL,
    min_size=4,
    max_size=20,           # cap concurrent branches × ~2
    timeout=30,
    kwargs={"row_factory": dict_row, "autocommit": True},
)
saver = AsyncPostgresSaver(pool)
```

Two connections per concurrent branch is a safe rule (one for state reads, one for writes during a step). For the demo's 2 branches, `max_size=20` is generous; for a real multi-tenant deployment, scale by expected concurrent runs × 2.

### Piece 3 — The `worktree_add` operation

This is the one piece of orchestration code you actually write. About 40 lines:

```python
import asyncio
import uuid
from langchain_core.runnables import RunnableConfig

async def worktree_add(
    graph,
    parent_thread_id: str,
    parent_checkpoint_id: str,
    mods: dict,             # what to change in the forked state
) -> tuple[str, asyncio.Task]:
    """
    Fork from a checkpoint into a new concurrent branch.
    Returns (new_thread_id, task) — task runs the branch to completion.
    """
    # 1. Build the parent config to read the checkpoint
    parent_config: RunnableConfig = {
        "configurable": {
            "thread_id": parent_thread_id,
            "checkpoint_id": parent_checkpoint_id,
        }
    }

    # 2. Apply mods, which writes a new checkpoint with a new thread_id.
    #    LangGraph automatically gives this its own thread when you
    #    pass a fresh thread_id in the config.
    new_thread_id = f"{parent_thread_id}.fork.{uuid.uuid4().hex[:8]}"
    fork_config: RunnableConfig = {
        "configurable": {
            "thread_id": new_thread_id,
            "checkpoint_id": parent_checkpoint_id,
        }
    }
    fork_config = await graph.aupdate_state(fork_config, mods)

    # 3. Spawn a concurrent task that resumes from the new checkpoint
    task = asyncio.create_task(
        graph.ainvoke(None, config=fork_config),
        name=f"worktree:{new_thread_id}",
    )
    return new_thread_id, task
```

That's the whole worktree primitive. The `asyncio.create_task` is the magic line — the branch runs concurrently with whatever else is happening, including the original linear branch.

### Piece 4 — The orchestrator endpoint

The FastAPI endpoint that powers the demo's fork moment:

```python
@app.post("/runs/{run_id}/fork")
async def fork_branch(run_id: str, body: ForkRequest):
    """
    User clicked 'Fork from here' in the UI.
    body = { parent_checkpoint_id, proposer_prior_override }
    """
    new_thread_id, task = await worktree_add(
        graph=meta_harness_graph,
        parent_thread_id=run_id,
        parent_checkpoint_id=body.parent_checkpoint_id,
        mods={"proposer_prior": body.proposer_prior_override},
    )

    # Track the task so the UI can show liveness + cancel later
    branch_registry[new_thread_id] = task

    # Stream state updates to the dashboard via SSE
    asyncio.create_task(stream_branch_to_dashboard(new_thread_id))

    return {"thread_id": new_thread_id, "status": "running"}
```

`branch_registry` is a `dict[str, asyncio.Task]` you keep in process memory — no Redis, no broker. The user can have ~10 concurrent branches before the LLM API rate limits matter more than the orchestration.

### Piece 5 — Streaming both branches to the dashboard

The dashboard needs to see both branches grow in real time. SSE per branch:

```python
async def stream_branch_to_dashboard(thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    async for state in meta_harness_graph.astream(
        None,
        config=config,
        stream_mode="updates",
    ):
        # push to whatever SSE channel the frontend is subscribed to
        await sse_publish(channel=f"run:{thread_id}", event="state", data=state)
```

The frontend opens one EventSource per branch and renders them on the same trajectory tree. Visually, both branches grow in real time — *that's the demo beat.*

---

## A.4 Three sharp edges, named explicitly

The async-concurrent pattern is the right call, but it has three known gotchas that will bite if you don't address them upfront.

### Gotcha 1 — Don't put sync I/O inside an async node

Async coroutines saturate I/O wait time, but only if every blocking call is awaitable. If a node calls a sync HTTP library or a sync DB driver, it blocks the entire event loop — both branches stall together.

The fix is mechanical: every node uses `await` for I/O, or wraps blocking calls in `asyncio.to_thread`:

```python
# BAD — blocks the event loop, both branches freeze together
def proposer_node(state):
    response = requests.post(...)  # sync, blocks everything

# GOOD — yields to the loop, other branches keep running
async def proposer_node(state):
    response = await aiohttp_session.post(...)

# ALSO GOOD — for libraries with no async equivalent
async def proposer_node(state):
    response = await asyncio.to_thread(some_sync_function, args)
```

Audit every node for this before the demo. It's the single most common reason async LangGraph "doesn't feel parallel" in practice.

### Gotcha 2 — `asyncio.gather` swallows interrupts

There's a known LangGraph issue (#6624, December 2025) where `asyncio.gather` over multiple branches that each fire an `interrupt()` only collects the first interrupt — others are dropped. This matters for RELAY's optional human-in-the-loop interrupt feature.

Two safe paths:

1. **Don't gather branches that use interrupts.** Fire them as independent `asyncio.create_task`s tracked in `branch_registry`. The pattern in Piece 4 above already does this — the demo isn't gathering, it's spawning. So this gotcha doesn't bite the v7 demo flow.
2. **If you do gather, use `return_exceptions=True`** and inspect each result for `GraphInterrupt`. This is heavier code but lets gather work safely.

For demo-day: stick with `create_task` per branch. Don't gather.

### Gotcha 3 — Cancellation must be deliberate

A demo-day common failure: user spawns 5 branches, gets bored, hits "cancel," half the branches finish anyway because nothing's listening. Track cancellation explicitly:

```python
@app.post("/runs/{run_id}/branches/{thread_id}/cancel")
async def cancel_branch(run_id: str, thread_id: str):
    task = branch_registry.get(thread_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    # Also write a "cancelled" status to the branch's last checkpoint
    await mark_branch_cancelled(thread_id)
    return {"status": "cancelled"}
```

For the 90-second demo this never fires, but having it removes a class of "the UI says 'running' but it isn't" demo failures.

---

## A.5 What this changes in the v7 demo

Act 3 ("Time-travel + memory") gets sharper. The script changes from:

> *[I rewind to iter 2, click Fork, configure prior, click Resume, watch the fork run, compare]*

To:

> *[I rewind to iter 2, click Fork, configure prior, click Resume — and the original linear branch keeps growing on the top while the fork grows on the bottom, both in real time. Compare view shows live progress on both.]*

The pitch line changes from:

> *"Two branches. Original: 0.80. Fork: 0.85."*

To:

> *"Two branches. Both running concurrently. Original is on iter 4 — 0.80. Fork is on iter 3-prime — 0.85. Both growing in real time. The meta-harness loop is no longer a sequence — it's a search tree, and we're walking multiple paths at once."*

The visual is what sells this. Engineers in the audience watch the trajectory tree fork *and grow simultaneously in two directions* and immediately understand they're seeing something the Stanford paper can't express.

---

## A.6 Build cost (honest)

| Task | Estimated time |
|---|---|
| Switch to `AsyncPostgresSaver` + connection pool | 30 min |
| Write the `worktree_add` primitive (~40 lines) | 60 min |
| Wire the FastAPI fork endpoint with `branch_registry` | 30 min |
| Add cancellation endpoint + UI button | 30 min |
| Audit nodes for sync-blocking calls; convert to async | 30 min |
| Update SSE streaming to support multiple concurrent channels | 30 min |
| Test with 2 concurrent branches end-to-end | 30 min |
| Demo dry-run with new visual | 30 min |
| **Total** | **~4 hours** |

This slots into the **Saturday 2-5pm "Backend B" block** in the v7 plan, replacing some of the subgraph isolation work (which can shrink — sandboxing is less critical for the demo than concurrent branches).

---

## A.7 What ships in v7+A vs v7 alone

| Capability | v7 alone | v7 + Appendix A |
|---|---|---|
| Time-travel rewind | ✅ | ✅ |
| Fork from any checkpoint | ✅ | ✅ |
| Edit-and-resume | ✅ | ✅ |
| Forks run on separate threads in Postgres | ✅ | ✅ |
| Forks run **concurrently with the parent branch** | ❌ (sequential) | ✅ |
| Demo shows two branches growing simultaneously | ❌ | ✅ |
| `branch_registry` for live branch management | ❌ | ✅ |
| Cancellation mid-branch | ❌ | ✅ |
| Production-realistic scaling story | Partial | Stronger |

---

## A.8 Decision

Adopt this if:
- You finish v7 core (proxy, time-travel API, fork UI) by Saturday noon
- The dashboard's SSE pipeline is solid by Saturday 2pm
- You have at least one team member comfortable with `asyncio` patterns

Skip this if:
- v7 core is still shaky at Saturday noon
- Anyone on the team is unsure about `asyncio.create_task` vs `gather` semantics
- The SSE pipeline is fragile (concurrent branches will surface every SSE bug at once)

The v7 demo wins without this. The v7+A demo wins more decisively.

**One spark, two branches.**
