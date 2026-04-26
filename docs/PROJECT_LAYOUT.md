# PROJECT_LAYOUT.md — Meta-Harness Monorepo

The repo is a **uv workspace** with two Python packages (`sdk/`, `backend/`),
a Next.js app (`frontend/`), and supporting directories. Every Python file
below has a one-line purpose annotation. Every locked decision in
`ARCHITECTURE_SECTION_1.md` is reflected in placement.

```
meta-harness/                                              # Repo root (uv workspace)
├── README.md                                              # Setup + 60s pitch + prereq list
├── LICENSE
├── .gitignore
├── pyproject.toml                                         # uv workspace: members = [sdk, backend]
├── ARCHITECTURE_SECTION_1.md                              # Reference: locked architecture
├── relay_metaharness_v7.md                                # Reference: v7 canonical build doc
├── relay_v7_appendix_a_worktrees.md                       # Reference: concurrent branches
├── relay_v7_appendix_b_metaharness_internals.md           # Reference: Stanford repo deep-dive
├── relay_v7_appendix_c_inner_loop.md                      # Reference: 5-phase coding agent
│
├── docs/                                                  # Phase-0 execution artifacts
│   ├── PROJECT_LAYOUT.md                                  # ← this file
│   ├── INTERFACES.md                                      # All cross-component contracts
│   ├── BUILD_ORDER.md                                     # Topological build steps + DoD
│   └── DEFINITION_OF_DONE.md                              # Demo arc as acceptance test
│
├── sdk/                                                   # User library: pip install meta_harness
│   ├── pyproject.toml                                     # name="meta_harness"; library only, no CLI
│   └── meta_harness/                                      # ⚠ snake_case = import name
│       ├── __init__.py                                    # Public API re-exports
│       ├── wrap_graph.py                                  # Instrument an existing LangGraph for Meta-Harness
│       ├── trace.py                                       # @trace_run decorator for generic agent loops
│       └── types.py                                       # Shared dataclasses (TraceEvent, RunInfo)
│
├── backend/                                               # FastAPI + LangGraph implementation
│   ├── pyproject.toml                                     # depends on meta_harness; console_script: meta-harness
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                                        # FastAPI app entry; mounts api routers; lifecycle hooks
│   │   ├── cli.py                                         # `meta-harness` CLI (typer): loop / init / run / fork
│   │   ├── streaming.py                                   # In-process SSE channel registry
│   │   ├── meta_harness/                                  # ⚠ INTERNAL namespace (app.meta_harness ≠ sdk's meta_harness)
│   │   │   ├── __init__.py
│   │   │   ├── outer.py                                   # Outer StateGraph: propose → validate → benchmark → update_frontier
│   │   │   ├── inner.py                                   # Inner StateGraph: orient → plan → act → verify → submit
│   │   │   ├── state.py                                   # MetaHarnessState + CodingAgentState TypedDicts
│   │   │   ├── proposer.py                                # ⚠ claude_wrapper.py-shaped: subprocess + stream-json parsing (body of `propose` node)
│   │   │   ├── harness.py                                 # CodingAgentHarness base + the 11 override points
│   │   │   ├── tools.py                                   # 6 fixed inner-loop tools (read_file/apply_patch/write_file/run_bash/grep_search/task_complete)
│   │   │   ├── sandbox.py                                 # /tmp/meta-harness-task-{uuid}/ process isolation, rlimits
│   │   │   ├── frontier.py                                # Pareto frontier on (accuracy × tokens)
│   │   │   ├── memory.py                                  # PostgresStore wrapper for cross-run patterns
│   │   │   ├── persistence.py                             # AsyncPostgresSaver + psycopg AsyncConnectionPool (max_size=20)
│   │   │   ├── branches.py                                # branch_registry + worktree_add (Appendix A)
│   │   │   └── runs.py                                    # Run filesystem lifecycle (runs/{run-id}/{agents,traces,proposer-sessions,...})
│   │   └── api/                                           # HTTP transport layer
│   │       ├── __init__.py
│   │       ├── runs.py                                    # POST /runs, GET /runs, GET /runs/{id}
│   │       ├── checkpoints.py                             # GET /runs/{id}/checkpoints
│   │       ├── forks.py                                   # POST /runs/{id}/fork ; POST .../branches/{thread_id}/cancel
│   │       ├── memory.py                                  # GET /memory/{namespace}
│   │       └── events.py                                  # GET /runs/{id}/stream (SSE)
│   └── tests/                                             # pytest suite: test_outer/inner/proposer/tools/sandbox/frontier/memory/branches
│
├── frontend/                                              # Next.js 16 dashboard (localhost:3000)
│   ├── package.json
│   ├── next.config.js
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                                       # Landing (run list + "new run" button)
│   │   └── runs/[run_id]/page.tsx                         # Dashboard (run detail) — the demo screen
│   ├── components/
│   │   ├── StateGraph.tsx                                 # ReactFlow outer-graph viz (live nodes lighting up)
│   │   ├── TrajectoryTree.tsx                             # D3 candidate trajectory tree (forks branch)
│   │   ├── DiffViewer.tsx                                 # Monaco unified-diff viewer (agents/<n>.py vs parent)
│   │   ├── ScoreChart.tsx                                 # Score + Pareto frontier
│   │   ├── MemoryPanel.tsx                                # Cross-run memory sidebar
│   │   └── ForkModal.tsx                                  # Right-click checkpoint → fork modal
│   └── lib/
│       ├── api.ts                                         # REST client (typed)
│       └── sse.ts                                         # SSE EventSource wrapper
│
├── skills/                                                # SKILL.md files (--append-system-prompt'd into claude spawn)
│   └── meta-harness-coding-agent/
│       └── SKILL.md                                       # Proposer workflow for the coding-agent domain
│
├── eval/                                                  # Frozen eval set + scorer
│   ├── score.py                                           # Wraps pytest; returns {accuracy, per_task, tokens}
│   ├── tasks/                                             # 5 search-set tasks; each = task.json + workspace/
│   │   ├── task-001-fix-typo/                             # workspace/{calculator.py, tests/test_calculator.py}, task.json
│   │   ├── task-002-add-function/                         # Same shape: task.json + workspace/{stats.py, tests/...}
│   │   ├── task-003-refactor/
│   │   ├── task-004-handle-error/
│   │   └── task-005-implement-spec/                       # geometry/ package per README spec
│   └── holdout/                                           # 2 tasks the proposer never sees (--holdout flag)
│       ├── task-006-…/
│       └── task-007-…/
│
└── infra/
    └── docker-compose.yml                                 # postgres:16 on localhost:5432 + persistent volume
```

---

## Naming & placement notes (READ BEFORE CHANGING ANY PATH)

1. **Two directories named `meta_harness`. They live in different scopes
   and are NOT the same package.**
   - `sdk/meta_harness/` — installable Python package; import path
     `meta_harness`. This is what users get from `pip install meta_harness`.
   - `backend/app/meta_harness/` — backend's internal orchestration
     namespace; import path `app.meta_harness`. This is private to the
     FastAPI app.
   - Both directories **must be snake_case** to match their respective
     import names. Hyphenated `meta-harness/` is a Python import error.

2. **`claude_wrapper.py`-shaped code lives at
   `backend/app/meta_harness/proposer.py`.** Not in `sdk/`. Not as a
   top-level orchestration script. The proposer is the body of the outer
   state machine's `propose` node, so its module sits adjacent to
   `outer.py`. If proposer code drifts to `sdk/` or to a sibling of
   `backend/`, that's the same architectural error from Correction 1
   coming back through file layout.

3. **The `meta-harness` (hyphenated) CLI tool comes from
   `backend/pyproject.toml`'s `[project.scripts]` entry
   `meta-harness = "app.cli:main"`.** The SDK package intentionally has
   no CLI to avoid a circular SDK↔backend dependency. Users who want
   only the library `pip install meta_harness`; users who want the CLI
   `pip install -e ./backend` (or both via the workspace install).

4. **Reference docs (relay_metaharness_v7.md and the three appendices
   plus ARCHITECTURE_SECTION_1.md) live at the repo root**, not in
   `docs/`. Phase-0 execution artifacts (this file, INTERFACES.md,
   BUILD_ORDER.md, DEFINITION_OF_DONE.md) live in `docs/`.

5. **Demo entrypoints (running locally):**
   - `docker compose -f infra/docker-compose.yml up -d postgres`
   - `uvicorn app.main:app --reload --port 8000` (in `backend/`)
   - `npm run dev` (in `frontend/`, serves on `:3000`)
   - `meta-harness loop --domain coding-agent` to start a run from the CLI
