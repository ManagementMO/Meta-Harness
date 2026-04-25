# Architecture Overview (Section 1) — Meta-Harness

*The locked architecture for the Meta-Harness project: the LangGraph-native
substrate around the Stanford Meta-Harness paradigm, scoped local-only,
single-user, with no feature cuts.*

---

## Three tiers + dashboard

Meta-Harness runs entirely on a local laptop. Each tier maps to a distinct
LangGraph primitive (or filesystem contract).

```
┌──────────────────────────────────────────────────────────────────────┐
│   PROPOSER TIER                                                      │
│   Claude Code subprocess (claude_wrapper.py) reads filesystem,       │
│   writes a new candidate file + pending_eval.json.                   │
│   Guidance: SKILL.md (--append-system-prompt'd into the spawn).      │
└──────────────────────────────────────────────────────────────────────┘
                          ▲ reads filesystem    │ writes candidate
                          │ (~82 files/iter)    ▼
┌──────────────────────────────────────────────────────────────────────┐
│   OUTER STATE MACHINE  (LangGraph StateGraph)                        │
│   Nodes: propose → validate → benchmark → update_frontier            │
│   Checkpointer: AsyncPostgresSaver. Every transition = checkpoint.   │
│   Memory: cross-thread PostgresStore (patterns persist across runs). │
│   Time-travel: get_state_history + update_state + invoke(None,cfg).  │
│   Concurrency: asyncio.create_task per branch (Appendix A).          │
└──────────────────────────────────────────────────────────────────────┘
                          │ benchmark spawns subgraph per candidate
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│   INNER STATE MACHINE  (LangGraph StateGraph, sandboxed subgraph)    │
│   PRIMARY: 5-phase coding agent — orient → plan → act → verify       │
│            → submit (Appendix C). 5 tools, 11 override points.       │
│   BACKUP : Stanford text-classification MemorySystem loop            │
│            (predict → learn → predict, wrapped as LangGraph nodes).  │
│   Each candidate harness compiles into the same shape; only the      │
│   prompts/methods/values change.                                     │
└──────────────────────────────────────────────────────────────────────┘
                          │ traces, scores, file diffs streamed
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│   DASHBOARD  (Next.js 15)                                            │
│   • Outer state graph viz (ReactFlow): live nodes lighting up        │
│   • Candidate trajectory tree (D3): branching for forks              │
│   • Code diff viewer (Monaco / unified-diff): live agents/<n>.py     │
│     diffs vs parent                                                  │
│   • Score chart + Pareto frontier (accuracy × tokens)                │
│   • Memory panel (cross-run patterns)                                │
│   • Right-click checkpoint → fork modal → resume                     │
└──────────────────────────────────────────────────────────────────────┘
```

## What each tier produces

- **Proposer** — writes `agents/<name>.py` (the candidate harness) +
  `pending_eval.json` (handoff schema).
- **Outer machine** — writes `frontier_val.json`, appends to
  `evolution_summary.jsonl`, and writes a Postgres checkpoint per transition.
- **Inner machine** — writes per-trial trace artifacts (`orient.json`,
  `plan.json`, `act-messages.jsonl`, `act-tools.jsonl`, `verify.json`,
  `summary.md`) under `runs/{run-id}/candidates/{N}/traces/`.
- **Dashboard** — consumes the Postgres checkpoint stream + filesystem
  traces via SSE from the FastAPI backend.

## Locked decisions at the architecture level

- **Monorepo** with top-level dirs `backend/` (FastAPI + LangGraph),
  `frontend/` (Next.js 15), `sdk/` (the `meta_harness` Python package +
  `wrap_graph()` / `@trace_run`), `skills/` (SKILL.md files), `eval/`
  (5 coding tasks + holdout), `docs/`, `infra/` (docker-compose).
- **Postgres** via local `docker compose up -d postgres`. LangGraph's
  `AsyncPostgresSaver` + `PostgresStore` are first-class.
- **AsyncPostgresSaver only** (sync version deadlocks under concurrent
  branches per Appendix A).
- **Project name = "Meta-Harness"** (project), Python package =
  `meta_harness` (snake_case), CLI = `meta-harness` (hyphenated).
  Stanford's framework = "Stanford's reference framework" — never conflate.
- **The Appendix C coding agent is the primary demo template.**
  Stanford's text-classification piggyback is the backup template,
  available alongside but not the demo hero.
- **Two LangGraph state machines, both checkpointed.** The inner machine
  is itself a subgraph compiled per candidate (sandboxed; "secure" property).
- **Local-only deployment.** No Clerk, Vercel, Vultr, `relay.dev`. Dashboard
  on `localhost:3000`; backend on `localhost:8000`; Postgres on
  `localhost:5432`.

## Explicitly out of scope at this level

- Multi-tenant: single-user, single Postgres instance.
- Auth: none.
- Worker queue: FastAPI BackgroundTasks + `asyncio.create_task` per branch
  (per Appendix A); no Celery, no Redis broker.
- Docker per task: process isolation only (Appendix C §C.6.3); honest about
  the limit in user-facing docs.
- Cloud anything.
