# Architecture Overview (Section 1) — Meta-Harness

*The locked architecture for the Meta-Harness project: the LangGraph-native
substrate around the Stanford reference framework's Meta-Harness paradigm,
scoped local-only, single-user, with no feature cuts.*

---

## Two state machines + a dashboard

Meta-Harness runs entirely on a local laptop. The system is **two LangGraph
state machines** (outer + inner, both checkpointed) plus a streaming web
dashboard. The proposer is **not a separate tier** — it runs as the body of
the outer machine's `propose` node.

```
┌──────────────────────────────────────────────────────────────────────┐
│   OUTER STATE MACHINE  (LangGraph StateGraph)                        │
│   Nodes: propose → validate → benchmark → update_frontier            │
│                                                                      │
│   The `propose` node spawns a Claude Code subprocess via             │
│   claude_wrapper.py, awaits its exit, and parses the resulting       │
│   filesystem writes (a new agents/<n>.py + pending_eval.json).       │
│   The subprocess receives the SKILL.md via --append-system-prompt    │
│   and reads ~82 files/iter from the run directory using              │
│   Read/Glob/Grep/Bash. The subprocess is invoked from inside the     │
│   graph, not alongside it — this is what makes checkpointing,        │
│   time-travel, and concurrent branches compose cleanly.              │
│                                                                      │
│   Checkpointer: AsyncPostgresSaver. Every transition = checkpoint.   │
│   Memory: cross-thread PostgresStore (patterns persist across runs). │
│   Time-travel: get_state_history + update_state + invoke(None,cfg).  │
│   Concurrency: asyncio.create_task per branch (Appendix A).          │
└──────────────────────────────────────────────────────────────────────┘
                          │ benchmark spawns subgraph per candidate
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│   INNER STATE MACHINE  (LangGraph StateGraph, sandboxed subgraph)    │
│   5-phase coding agent — orient → plan → act → verify → submit       │
│   (Appendix C). 5 fixed tools (read_file, apply_patch, run_bash,     │
│   grep_search, task_complete), 11 override points.                   │
│   Each candidate compiles into the same shape; only the              │
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

## What each component produces

- **`propose` node** — spawns a Claude Code subprocess (`claude_wrapper.py`)
  with `--append-system-prompt $(cat skills/<domain>/SKILL.md)`,
  `--dangerously-skip-permissions`, `--disable-slash-commands`, an empty
  `--plugin-dir`, and `--output-format stream-json`. The subprocess writes
  `agents/<name>.py` + `pending_eval.json` and returns rich session metadata
  (token usage, files read/written, cost, exit code). Per-iteration logs go
  to `runs/{run-id}/proposer-sessions/iter-{N}/{session.json,
  transcript.txt, system_prompt.txt}`.
- **Outer machine** — writes `frontier_val.json`, appends to
  `evolution_summary.jsonl`, and writes a Postgres checkpoint per node
  transition.
- **Inner machine** — writes per-trial trace artifacts (`orient.json`,
  `plan.json`, `act-messages.jsonl`, `act-tools.jsonl`, `verify.json`,
  `summary.md`) under `runs/{run-id}/candidates/{N}/traces/`.
- **Dashboard** — consumes the Postgres checkpoint stream + filesystem
  traces via the FastAPI backend.

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
  `meta_harness` (snake_case), CLI = `meta-harness` (hyphenated). Stanford's
  framework is referred to as "Stanford's reference framework" — never
  conflate.
- **Proposer implementation: `claude` CLI subprocess** (Phase 1.1
  resolved). Matches Stanford's `claude_wrapper.py` pattern verbatim. Each
  spawn uses `--dangerously-skip-permissions` (unrestricted filesystem
  access on the run directory), `--disable-slash-commands` and an empty
  `--plugin-dir` (hermeticity), `--append-system-prompt` (SKILL.md
  injection), `--output-format stream-json` (structured logging). Tool
  bundle: `Read, Glob, Grep, Edit, Write, Bash` (TOOLS_BASH per Appendix B
  §B.3) — `Bash` is required for the SKILL.md workflow's "Prototype" step.
  The proposer-session log schema is therefore drop-in compatible with
  Stanford's `session.json`. **Demo-machine prerequisite:** Claude Code
  (the `claude` CLI) installed locally; not a runtime concern, but a setup
  step in the README and BUILD_ORDER's prereq item. Direct Anthropic API
  proposer is explicitly out of scope.
- **The inner loop is the Appendix C 5-phase coding agent. There is no
  alternative inner-loop implementation in scope.**
- **Two LangGraph state machines, both checkpointed.** The inner machine
  is itself a subgraph compiled per candidate (sandboxed; "secure"
  property).
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
- Alternative inner-loop implementations (no Stanford text-classification
  backup; coding agent only).
- Direct Anthropic API proposer (we use the `claude` CLI subprocess
  exclusively).
