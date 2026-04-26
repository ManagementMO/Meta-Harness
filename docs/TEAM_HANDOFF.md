# TEAM_HANDOFF.md — 4-Person Hackathon Coordination Plan

*Where we are, what's built, what remains, and exactly who builds what
over the next several hours. Read this end-to-end before touching any
code; it's the source of truth for the hand-off.*

---

## 0. TL;DR

- **6 of 13 BUILD_ORDER steps are landed and verified.** Inner-loop
  agent works end-to-end with real LLM (`claude-haiku-4-5`); outer-loop
  state machine works with mock + real proposer; SKILL.md is wired and
  the `claude` CLI subprocess produces real candidate code.
- **7 steps remain** — async refactor + AsyncPostgresSaver, cross-run
  memory, time-travel + concurrent branches, FastAPI REST/SSE, the
  Next.js dashboard, CLI completeness + holdout, and the final demo
  acceptance test.
- **Postgres now unblocked** — Docker 29.4.0 + Compose v5.1.2 are
  installed. `docker compose -f infra/docker-compose.yml up -d postgres`
  is the only setup needed.
- **Team split: 4 lanes**. **Person 1 (Persistence Lead)** unblocks
  everyone by landing step 7 first. **Person 2 (Time-Travel + Memory)**
  picks up steps 8–9 once 7 lands. **Person 3 (API Layer)** builds
  step 10. **Person 4 (Frontend Lead)** owns step 11 — the largest
  single piece — and starts immediately on the API contract. Steps 12
  and 13 are distributed across the team in the final integration hour.
- **Calibration note**: the baseline scored 100% on the partial 13-trial
  benchmark, well above the predicted [0.40, 0.60] band. Eval tasks
  need hardening or `MAX_ACT_TURNS` needs tightening before the demo
  arc 62%→80%→85% has headroom. **Person 4** owns this in parallel
  with frontend work.

**Critical-path order:** Step 7 → Step 9 → Step 10 → Step 11.
**Parallelizable:** Steps 8 (after 7), 11 (always — start with mocked
API contracts), 12 (anytime), eval recalibration (anytime).

---

## 1. Where We Are — Current State of the Codebase

### 1.1 Commit log (most recent first)

```
dadee99 fixup: gitignore agents/*.py except baseline + __init__ (proposer artifacts)
0c788d2 step 6: real proposer (claude CLI subprocess) + SKILL.md
d14e104 step 5: outer state machine with mock proposer + mock benchmark
aefe5f5 change to haiku for rate limits  (== step 4 build / inner-model swap)
349799d md files                          (== eval-task workspaces 2-5)
c3613ed step 3 (verified): inner loop end-to-end on task-001
1e46470 step 3 (build): inner StateGraph + 5-phase coding agent + CLI inner
ff51df6 step 2: sandbox + 6 fixed tools (LLM-free) — 31 unit tests green
d428ade step 1: repo skeleton + Postgres + first eval task
```

### 1.2 What runs today (verified working)

| Command | What it exercises | Cost / time |
|---|---|---|
| `docker compose -f infra/docker-compose.yml up -d postgres` | Postgres 16 on `localhost:5432` (now Docker is installed) | ~10s |
| `uv sync` | Workspace install of `meta_harness` (sdk) + `meta_harness_backend` | ~5s |
| `uv run python -m eval.score --task task-001-fix-typo` | One task scored without LLM (returns `passed=false` on the buggy calc) | <1s |
| `cd backend && uv run pytest tests/ -q` | 42 LLM-free tests + 1 live LLM test (test_inner.py runs ~24s with API key) | ~3s LLM-free; ~30s with live |
| `uv run meta-harness inner --task task-001-fix-typo --candidate baseline` | Single inner-loop trial on task-001 | ~24s, ~$0.05 |
| `uv run meta-harness benchmark --candidate baseline --trials 5 --workers 1` | Full 5×5 benchmark (Haiku) | ~30 min, ~$1.25 — **slow + the baseline saturates at ~100%; needs recalibration** |
| `uv run meta-harness loop --proposer mock --mock-bench --budget 2 --fresh --run-name foo` | Full mock outer loop (no LLM) | ~1s |
| `uv run meta-harness loop --proposer claude --budget 1 --fresh --mock-bench --run-name foo` | Real proposer + mock benchmark | ~2-3 min, ~$1 |

### 1.3 Repo tree (at HEAD)

```
meta-harness/
├── README.md
├── LICENSE
├── .gitignore                                           # agents/*.py excluded except baseline + __init__
├── .env                                                 # ANTHROPIC_API_KEY + POSTGRES_DSN (gitignored)
├── pyproject.toml                                       # uv workspace root: members = [sdk, backend]
├── uv.lock
│
├── ARCHITECTURE_SECTION_1.md                            # Locked architecture (NO touching without ratification)
├── relay_metaharness_v7.md                              # Reference: v7 canonical build doc
├── relay_v7_appendix_a_worktrees.md                     # Reference: Appendix A — concurrent branches
├── relay_v7_appendix_b_metaharness_internals.md         # Reference: Appendix B — Stanford internals
├── relay_v7_appendix_c_inner_loop.md                    # Reference: Appendix C — 5-phase coding agent
│
├── docs/                                                # Phase-0 artifacts (canonical contracts)
│   ├── PROJECT_LAYOUT.md
│   ├── INTERFACES.md                                    # READ THIS — every cross-component contract
│   ├── BUILD_ORDER.md                                   # 13 steps, DoD per step
│   ├── DEFINITION_OF_DONE.md                            # The demo arc as acceptance test
│   └── TEAM_HANDOFF.md                                  # ← this file
│
├── sdk/                                                 # `pip install meta_harness` (currently thin)
│   ├── pyproject.toml
│   └── meta_harness/
│       └── __init__.py                                  # public-API stubs — flesh out at step 11+
│
├── backend/                                             # FastAPI + LangGraph implementation
│   ├── pyproject.toml                                   # console_script: meta-harness = app.cli:main
│   ├── conftest.py                                      # pytest_configure → load_dotenv()
│   └── app/
│       ├── __init__.py
│       ├── main.py                                      # NOT YET WRITTEN (step 10)
│       ├── streaming.py                                 # NOT YET WRITTEN (step 10)
│       ├── cli.py                                       # version / inner / benchmark / loop subcommands
│       ├── meta_harness/                                # internal namespace (app.meta_harness)
│       │   ├── __init__.py
│       │   ├── state.py                                 # MetaHarnessState + CodingAgentState + Candidate
│       │   ├── harness.py                               # CodingAgentHarness base + 11 override points
│       │   ├── inner.py                                 # 5-phase StateGraph (orient → … → submit)
│       │   ├── outer.py                                 # 4-node StateGraph + OuterLoopRunner
│       │   ├── proposer.py                              # mock_propose + claude_propose (real CLI subprocess)
│       │   ├── tools.py                                 # 6 fixed inner-loop tools (read_file, apply_patch, …)
│       │   ├── sandbox.py                               # /tmp/meta-harness-task-{uuid}/ process isolation
│       │   ├── frontier.py                              # Pareto on (accuracy × tokens) + dominated_by_names
│       │   ├── runs.py                                  # filesystem lifecycle (manifest/pending_eval/…)
│       │   ├── persistence.py                           # NOT YET WRITTEN (step 7)
│       │   ├── memory.py                                # NOT YET WRITTEN (step 8)
│       │   └── branches.py                              # NOT YET WRITTEN (step 9)
│       └── api/                                         # NOT YET WRITTEN (step 10)
│           └── (events.py, runs.py, checkpoints.py, forks.py, memory.py)
│
├── frontend/                                            # NOT YET WRITTEN (step 11)
│
├── skills/
│   └── meta-harness-coding-agent/
│       └── SKILL.md                                     # ~150 lines — proposer's workflow contract
│
├── eval/                                                # frozen eval set (5 tasks, calibration WIP)
│   ├── score.py                                         # multi-task pytest scorer
│   ├── tasks/
│   │   ├── task-001-fix-typo/{task.json, workspace/}    # add(a,b) returns a-b — bug fix tier
│   │   ├── task-002-add-function/                       # implement median() — implement-spec tier
│   │   ├── task-003-refactor/                           # 3 dup fns → shared helper (structural test)
│   │   ├── task-004-handle-error/                       # parse_ages crashes on empty/invalid — robustness
│   │   └── task-005-implement-spec/                     # implement Point + Line per README — multi-file
│   └── holdout/                                         # NOT YET WRITTEN (step 12)
│
├── agents/                                              # immutable starting point + proposer outputs
│   ├── __init__.py
│   └── baseline.py                                      # BaselineHarness (zero overrides)
│
├── infra/
│   └── docker-compose.yml                               # Postgres 16 service
│
└── runs/                                                # gitignored — per-run artifacts
```

### 1.4 LangGraph wiring at HEAD

- **Outer state graph** (`app.meta_harness.outer.OuterLoopRunner.build`)
  - Nodes: `propose → validate → benchmark → update_frontier`
  - Edges: linear; `update_frontier` conditional → `propose` while
    `budget_remaining > 0`, else `END`.
  - **Sync** today; uses `graph.invoke()`. **Step 7 will async-ify.**
- **Inner state graph** (`app.meta_harness.inner.build_inner_graph`)
  - Nodes: `orient → plan → act → verify → submit`
  - Edges: `verify` conditional → `act` (loop back) or `submit`
  - Bound by `MAX_VERIFY_RETRIES = 3` (hardcoded in routing for now).
  - **Sync** today; uses `graph.invoke()`. **Step 7 will async-ify.**

---

## 2. The Architecture — Two Loops, One SKILL.md, Streaming Dashboard

This is a refresher. The full version is `ARCHITECTURE_SECTION_1.md`.

```
                                       ┌───────────────────────────────────────────────────────────────┐
                                       │  OUTER STATE MACHINE (LangGraph + AsyncPostgresSaver eventually)│
                                       │                                                                 │
                                       │   ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────┐  │
                                       │   │ propose  │→ │ validate │→ │ benchmark │→ │update_frontier│  │
                                       │   └────┬─────┘  └──────────┘  └─────┬─────┘  └──────────────┘  │
                                       │        │ spawns claude CLI            │ spawns inner subgraph    │
                                       │        │ subprocess (proposer)        │ per (candidate × task)   │
                                       │        ▼                              ▼                          │
                                       │  ┌──────────────────┐         ┌────────────────────────┐         │
                                       │  │ claude_wrapper   │         │ INNER STATE MACHINE    │         │
                                       │  │ + SKILL.md       │         │ orient → plan → act →  │         │
                                       │  │ → agents/<n>.py  │         │ verify → submit        │         │
                                       │  │ + pending_eval   │         │ (5-phase coding agent) │         │
                                       │  └──────────────────┘         └────────────────────────┘         │
                                       │                                                                 │
                                       │   Time-travel: get_state_history + update_state + ainvoke         │
                                       │   Memory:      PostgresStore namespaced by domain                 │
                                       │   Concurrency: asyncio.create_task per branch (Appendix A)        │
                                       └───────────────────────────────────────────────────────────────────┘
                                                                  │
                                                                  ▼ events via FastAPI SSE multiplex
                                       ┌───────────────────────────────────────────────────────────────┐
                                       │  DASHBOARD (Next.js 16)                                         │
                                       │  • Outer state graph viz (ReactFlow) — live nodes lighting up   │
                                       │  • Candidate trajectory tree (D3) — fork branches grow         │
                                       │  • Code diff viewer (Monaco) — agents/<n>.py vs parent         │
                                       │  • Score chart + Pareto frontier                              │
                                       │  • Memory panel (cross-run patterns)                          │
                                       │  • Right-click checkpoint → fork modal → resume                │
                                       └───────────────────────────────────────────────────────────────────┘
```

### 2.1 Runtime flow when the demo runs

`meta-harness loop --proposer claude --budget 5 --fresh --run-name demo`:

1. **CLI bootstraps** — `cli.py` loads `.env`, adds repo root to
   `sys.path`, parses flags, resolves `skill_path` per INTERFACES.md
   §5.3, calls `run_outer_loop(...)`.
2. **`make_run_dir`** creates `runs/demo/` with `agents/`,
   `candidates/`, `proposer-sessions/` subdirs and writes
   `manifest.json`.
3. **Outer graph compiles** with checkpointer (Postgres after step 7;
   in-memory now), starts at `propose` with `iteration=0,
   budget_remaining=5`.
4. **`propose` node** → `claude_propose` spawns
   `claude --dangerously-skip-permissions ... --append-system-prompt
   <SKILL.md content>` with `cwd=repo_root`, **strips
   `ANTHROPIC_API_KEY`** to force subscription auth, parses stream-json
   line-by-line, writes
   `runs/demo/proposer-sessions/iter-1/{session.json, transcript.txt,
   system_prompt.txt, user_prompt.txt, events.jsonl}`. The proposer
   writes a new `agents/<descriptive-name>.py` and
   `runs/demo/pending_eval.json`. Returns the parsed payload.
5. **`validate` node** → adds `repo_root` to `sys.path`, imports the
   candidate via `importlib`, asserts subclass of `CodingAgentHarness`.
   On failure: marks `status=smoke_failed`.
6. **`benchmark` node** → for each `(task × trial)`, instantiates a
   fresh `harness = CandidateClass()`, opens a `sandbox_for(task/workspace)`
   (per-uuid `/tmp/meta-harness-task-*/`), calls `run_inner_loop` which
   runs the inner state graph. Each trial writes per-trial trace
   artifacts (`orient.json`, `plan.json`, `act-messages.jsonl`,
   `act-tools.jsonl`, `verify.json`, `score.json`, `summary.md`,
   `final-files.json`). Aggregates into
   `runs/demo/candidates/<name>/eval-result.json`.
7. **`update_frontier` node** → recomputes Pareto on (accuracy, tokens)
   across all scored candidates, writes `frontier_val.json` (with
   `dominated_by_names` per candidate), appends a row to
   `evolution_summary.jsonl` (with `parent_candidate_name`), writes
   `candidates/<name>/status.json`. Decrements `budget_remaining`.
8. **Conditional edge** → loop back to `propose` if budget remains,
   else END.

After step 7+ the LangGraph checkpointer writes a Postgres row at
every node transition, so kill+resume is one command.

After step 9, time-travel forks become `worktree_add(parent_ckpt,
mods)` → `asyncio.create_task(graph.ainvoke(None, fork_config))`,
streamed live to the dashboard via SSE on `run:{run_id}`.

---

## 3. Reference Documents — What to Read

Read these in order before contributing. Don't redesign anything in
them without explicit ratification.

| Doc | When to read | What it covers |
|---|---|---|
| `ARCHITECTURE_SECTION_1.md` | First | Locked 2-tier architecture + the locked decisions |
| `docs/PROJECT_LAYOUT.md` | First | The directory tree + naming risk callouts |
| `docs/INTERFACES.md` | **Always** | Every cross-component contract (state schemas, JSON, REST, SSE, tool I/O, override points, SKILL.md schema) |
| `docs/BUILD_ORDER.md` | When picking a step | DoD for each step + what each step unblocks |
| `docs/DEFINITION_OF_DONE.md` | Before demo | The demo arc as the formal acceptance test (binary checklist) |
| `relay_metaharness_v7.md` | For the why | The canonical hackathon build doc (3 properties, demo arc, pitch) |
| `relay_v7_appendix_a_worktrees.md` | When working on step 9 | Concurrent branches via `asyncio.create_task` (NOT `gather`) + 3 named gotchas |
| `relay_v7_appendix_b_metaharness_internals.md` | When working on step 6+ | Stanford repo deep-dive; SKILL.md skeleton; outer-loop phase mechanics |
| `relay_v7_appendix_c_inner_loop.md` | When working on inner loop | 5-phase agent + 6 tools + 11 override points |
| `skills/meta-harness-coding-agent/SKILL.md` | When debugging proposer | The literal text the proposer reads on every iteration |

**Phase 1 decisions already resolved (DO NOT relitigate):**

- **Phase 1.1**: Proposer = `claude` CLI subprocess (Stanford pattern,
  Appendix B §B.3). Subscription auth via the CLI; ANTHROPIC_API_KEY
  is stripped before exec.
- **Phase 1.2**: SSE for events + REST for commands (per
  INTERFACES.md §6, §7).
- **Phase 1.3**: `skill_path` resolution = absolute / relative-to-repo
  / default `skills/meta-harness-coding-agent/SKILL.md` (per
  INTERFACES.md §5.3).

---

## 4. Best-Knowledge — Empirical Findings & Gotchas

Things we learned the hard way; absorb before writing code.

### 4.1 Anthropic rate limits

The shared API key (in `.env`) is on a tier with **30,000 input tokens
/ minute** for Sonnet 4.6. A single inner-loop trial accumulates
60–80K input tokens across ~9 turns within ~24s; that breaks the limit
even with `workers=1`. **Default inner-loop model is now
`claude-haiku-4-5-20251001`** (higher rate limit, ~10× cheaper).
Override via `META_HARNESS_INNER_MODEL` env var if a better tier is
available. The proposer (Claude Code CLI subprocess) uses
**subscription auth**, not the API key — `ANTHROPIC_API_KEY` is
stripped before exec.

### 4.2 Calibration mismatch

Appendix C §C.11 predicted baseline = 0.48 mean (band [0.40, 0.60]).
Observed baseline on the partial 13-trial benchmark = **1.0** — the
Haiku-4.5 + 5-phase agent solves all observed tasks. The demo arc
62%→80%→85% currently has **zero headroom**. **Person 4** owns
recalibration:

- Option A: harden tasks 1–5 (more edge cases, longer files, multi-step
  spec changes).
- Option B: tighten `MAX_ACT_TURNS` on the baseline (e.g., `5` instead
  of `25`) so simple tasks fail without the proposer's optimization.
- Option C: drop to a weaker model (e.g., older Haiku with date suffix,
  or `claude-haiku-3-5`).

### 4.3 macOS rlimit quirk

`resource.setrlimit(RLIMIT_AS, 512MB)` in `sandbox.py`'s `preexec_fn`
**reliably crashes Python child processes on macOS** because the
runtime + libraries already exceed the cap before the child runs
anything. We skip `RLIMIT_AS` on Darwin and rely on `subprocess.run`
timeout instead. `RLIMIT_CPU` still applied. **Honest limitation: not
true sandbox isolation; production needs Docker per task; out of
scope.**

### 4.4 Subprocess UTF-8 decoding

Pytest output, ripgrep output, and arbitrary agent commands can emit
bytes that aren't valid UTF-8 (truncated multi-byte sequences, ANSI
escapes from broken terminals). **All `subprocess.run` calls use
`encoding="utf-8", errors="replace"`** to avoid `UnicodeDecodeError`
crashing a trial. Audit anywhere new subprocess code lands.

### 4.5 LangGraph async checkpointer is mandatory for concurrency

`PostgresSaver` (sync) **deadlocks under concurrent use** (per
Appendix A). **Use `AsyncPostgresSaver` exclusively** (langgraph
.checkpoint.postgres.aio). All node bodies must be async or wrap
blocking calls in `asyncio.to_thread`. **Step 7 is the async
refactor.** Once it's done:

- Spawn branches with `asyncio.create_task(graph.ainvoke(None,
  fork_config))`, never `asyncio.gather` (`gather` swallows
  `interrupt()` per LangGraph #6624).
- Track in-flight branches via
  `branch_registry: dict[str, asyncio.Task]`.
- Pool sized `max_size=20` (≈2 connections per concurrent branch).

### 4.6 Claude Code subprocess details

- The `claude` CLI must be on `PATH`. It is at this checkpoint:
  `/Users/mo/.local/bin/claude` v2.1.119.
- The user must be logged in (subscription auth) — `claude /login`
  if not.
- The proposer subprocess takes **~2–3 minutes** for a single
  iteration on simple tasks. Reads ~10–20 files, prototypes at
  `/tmp/`, writes one new candidate.
- Cost shown in `session.json` is an approximation; subscription auth
  doesn't bill by call.

### 4.7 `agents/` directory ownership

`agents/baseline.py` and `agents/__init__.py` are committed to git.
**Everything else** (proposer-generated and mock candidates) is a
run artifact and `.gitignore`'d. The proposer writes new candidates
to `agents/<descriptive-name>.py` from its `cwd=repo_root` subprocess.
The CLI's `--fresh` flag wipes prior `runs/<run_name>/` but does not
clean `agents/` — that's deliberate; the proposer can reference prior
candidates across iterations.

### 4.8 Two `meta_harness` modules — different scopes

- `sdk/meta_harness/` = the public installable package (`pip install
  meta_harness`); imported as `import meta_harness`. Currently thin.
- `backend/app/meta_harness/` = backend's internal namespace; imported
  as `from app.meta_harness.<module> import …`.

These are **not the same package** despite the directory name. Never
import across them — backend may import sdk for shared types, never
the reverse.

---

## 5. Remaining Work — Steps 7–13

The DoD for each step is in `docs/BUILD_ORDER.md`; below is the
step-level summary plus what each step's owner needs to deliver.

### Step 7 — AsyncPostgresSaver + async refactor (CRITICAL PATH, ~2-3 hr)

**Goal.** Every state-graph transition is checkpointed to Postgres;
runs survive `SIGINT`; `meta-harness resume <run-id>` resumes from the
last checkpoint.

**Files to write/modify.**
- `backend/app/meta_harness/persistence.py` (new): `AsyncConnectionPool`
  + `AsyncPostgresSaver` setup, `async with persistence_layer(dsn) as
  saver:` context manager.
- `backend/app/meta_harness/inner.py`: every node body to `async def`;
  `_call_llm` uses `anthropic.AsyncAnthropic`; `run_inner_loop` →
  `async def`; `graph.ainvoke` instead of `graph.invoke`.
- `backend/app/meta_harness/outer.py`: every node body to `async def`;
  `benchmark` uses `asyncio.gather` (carefully — see §4.5) instead of
  `ThreadPoolExecutor`; `run_outer_loop` → `async def`.
- `backend/app/meta_harness/harness.py`: `_call_llm` becomes async;
  `_client = anthropic.AsyncAnthropic(...)`.
- `backend/app/cli.py`: `loop`, `inner`, `benchmark` wrap with
  `asyncio.run(...)`.
- `backend/tests/test_persistence.py` (new): kill+resume integration
  test (requires Postgres up).

**DoD command** (per BUILD_ORDER.md):
```bash
docker compose -f infra/docker-compose.yml up -d postgres
uv run meta-harness loop --proposer mock --budget 3 --fresh --run-name resume-test &
sleep 30 && kill -INT $! && wait $! 2>/dev/null
uv run meta-harness resume resume-test
# resume completes the remaining iterations; final iteration count == 3;
# no duplicate iterations in evolution_summary.jsonl.
```

**Branch:** `step-7/persistence-async`.

### Step 8 — Cross-run memory store (PostgresStore) (~2-3 hr)

**Goal.** End-of-run, the outer machine writes successful patterns to
the `("learned_patterns", "<domain>")` namespace. Start-of-run, the
proposer's `--append-system-prompt` includes a section with the top-N
relevant patterns from prior runs of this domain.

**Files.**
- `backend/app/meta_harness/memory.py` (new): wrapper around
  LangGraph's `PostgresStore` with `add_pattern`,
  `search_patterns(query, namespace, limit=5)`, `list_namespace`.
- `backend/app/meta_harness/outer.py`: in `update_frontier`, after a
  candidate is accepted, call `memory.add_pattern(namespace, key=uuid,
  value={pattern, evidence, score_delta})`.
- `backend/app/meta_harness/proposer.py`: in `claude_propose`, before
  building system_prompt, call `memory.search_patterns(domain)` and
  prepend the results to `system_prompt_parts`.
- `backend/tests/test_memory.py` (new): write→read→cross-run-show test.

**DoD command:**
```bash
uv run meta-harness loop --proposer claude --budget 3 --fresh --run-name run-a
uv run meta-harness loop --proposer claude --budget 3 --fresh --run-name run-b
uv run meta-harness memory list --namespace coding-agent
# returns ≥1 entry written by run-a;
grep -l "<entry-key>" runs/run-b/proposer-sessions/iter-1/system_prompt.txt
```

**Branch:** `step-8/cross-run-memory`. Depends on step 7.

### Step 9 — Time-travel + concurrent branches (~3-4 hr)

**Goal.** Expose `get_state_history`. Implement `worktree_add(parent_ckpt,
mods)` that creates a new thread via `update_state` + spawns
`asyncio.create_task(graph.ainvoke(None, fork_config))`. Track in-flight
branches in `branch_registry: dict[str, asyncio.Task]`. Cancellation
endpoint terminates a live task and writes a "cancelled" status to the
last checkpoint.

**Files.**
- `backend/app/meta_harness/branches.py` (new): `worktree_add`,
  `branch_registry`, `cancel_branch`, `list_branches`, helpers to
  reconstruct the trajectory tree by walking `parent_thread_id`
  pointers.
- `backend/app/meta_harness/outer.py`: hooks for fork-from-history.
- `backend/tests/test_branches.py` (new): asserts `get_state_history`
  returns N checkpoints; `worktree_add` creates a new thread with
  `parent_thread_id`; both branches complete concurrently without
  deadlock; `cancel_branch` terminates a live task.

**DoD command:**
```bash
cd backend && uv run pytest tests/test_branches.py -v
```

**Branch:** `step-9/time-travel-branches`. Depends on step 7.

### Step 10 — FastAPI REST + SSE with closed-set registry (~2-3 hr)

**Goal.** All §6 endpoints. SSE channel registry rejects unregistered
event types with 500-class error (per §7.3). `POST /runs` returns
**201 Created** with `Location` header. Per-run multiplex with
`thread_id` per event (per §7.4).

**Files.**
- `backend/app/main.py` (new): FastAPI app, lifespan handler that
  opens the AsyncPostgresSaver pool.
- `backend/app/streaming.py` (new): `EventRegistry` with the 11 event
  types from §7.2 as a closed allowlist; `emit(channel, event_type,
  payload)` raises on unknown type; per-channel SSE generator.
- `backend/app/api/__init__.py` (new).
- `backend/app/api/runs.py`, `checkpoints.py`, `forks.py`, `memory.py`,
  `events.py` (all new).
- `backend/tests/test_api.py` (new): scripted REST exercise.
- `backend/tests/test_streaming.py` (new): registry rejection test.
- `scripts/smoke_api.py` (new): the literal DoD smoke script.

**DoD command:**
```bash
(cd backend && uv run uvicorn app.main:app --port 8000 --reload &) && sleep 2
uv run python scripts/smoke_api.py
# exercises POST /runs (asserts 201 + Location), checkpoint listing,
# fork creation, SSE stream, and asserts emit() of an unregistered
# event type raises 500.
```

**Branch:** `step-10/api-sse`. Depends on steps 7 + 9.

### Step 11 — Frontend dashboard (~5-7 hr — LARGEST SINGLE PIECE)

**Goal.** Next.js 16 dashboard at `localhost:3000`. The
`/runs/[run_id]` page renders ReactFlow outer-state-graph, D3
trajectory tree, Monaco unified-diff viewer, score+frontier chart,
memory panel, and a right-click → fork modal. All five views update
live via SSE.

**Files.**
- `frontend/package.json`, `next.config.js`, `tsconfig.json`,
  `tailwind.config.ts`.
- `frontend/app/layout.tsx`, `page.tsx`, `runs/[run_id]/page.tsx`.
- `frontend/components/{StateGraph, TrajectoryTree, DiffViewer,
  ScoreChart, MemoryPanel, ForkModal}.tsx`.
- `frontend/lib/api.ts` (typed REST client) + `sse.ts` (EventSource
  wrapper with `Last-Event-ID` reconnect).
- `e2e/dashboard.spec.ts` (Playwright).

**DoD command:**
```bash
(cd frontend && npm install && npm run build && npm run dev &) && sleep 5
npx playwright test e2e/dashboard.spec.ts
```

**Branch:** `step-11/frontend`. Can start immediately on
`api/lib.ts` + components against fixtures from `INTERFACES.md`. Real
integration with the API after step 10.

### Step 12 — CLI completeness + holdout (~1-2 hr)

**Goal.** `meta-harness` exposes `loop`, `inner`, `benchmark`, `fork`,
`resume`, `init`, `memory` subcommands. `--holdout` flag runs the
final-best candidate against `eval/holdout/` and reports separately.

**Files.**
- `backend/app/cli.py`: add `fork`, `resume`, `init`, `memory`
  subcommands.
- `eval/holdout/{task-006-…/, task-007-…/}` (new): 2 holdout tasks
  the proposer never sees.
- `backend/tests/test_cli.py` (new).

**DoD command:**
```bash
uv run meta-harness loop --proposer claude --budget 5 --fresh --holdout --run-name holdout-test
# evolution_summary + frontier present (search set);
# runs/holdout-test/holdout-result.json present (distinct from search)
```

**Branch:** `step-12/cli-holdout`. Distributed across team — each
person owns the CLI flag for their step.

### Step 13 — End-to-end demo dry-run (~1-2 hr)

**Goal.** Pass `DEFINITION_OF_DONE.md` verbatim. Score arc lands
within ±5% of expected; fork branches reach ≥0.83; runtime <8 min;
cost <$5.

**Files.**
- `scripts/demo_dryrun.sh` (new): the formal acceptance runner.
- (Possibly) eval-task hardening if calibration is still off.

**DoD command:**
```bash
bash scripts/demo_dryrun.sh
```

**Branch:** `step-13/demo-acceptance`. Whole team in the final
integration hour.

---

## 6. Team Split — Four Lanes

### Person 1 — Persistence Lead (CRITICAL PATH)

**Mission:** Land step 7 first. You unblock everyone else.

**Owned steps:** 7 (primary). After 7 lands, integrate with whoever
needs help; secondary owner of CLI's `resume` subcommand (step 12).

**Skills required:** `asyncio`, LangGraph internals, Postgres,
Anthropic SDK (especially `AsyncAnthropic`).

**Branches you create:**
- `step-7/persistence-async` (PR target: main)

**First action:**
```bash
git checkout main && git pull
git checkout -b step-7/persistence-async
docker compose -f infra/docker-compose.yml up -d postgres
docker logs meta-harness-postgres   # verify it's up
psql postgresql://meta_harness:meta_harness@localhost:5432/meta_harness -c '\l'
```

**Definition of done:**
- The kill+resume DoD command from §5 step 7 passes.
- All 42 LLM-free tests still pass.
- `test_persistence.py` added with at least one test that requires
  Postgres (skipped via `pytest.mark.skipif` when DSN not set).
- PR opens against `main` with a checklist linking to BUILD_ORDER step 7.

**Coordination notes:**
- Once your PR opens, ping the team in chat. Persons 2 + 3 should
  pull your branch and rebase their own work onto it.
- Document any breaking changes to `inner.py` / `outer.py` signatures
  in the PR description so everyone updates their code.

### Person 2 — Time-Travel + Memory

**Mission:** Land steps 8 and 9 in that order. The fork demo beat is
yours.

**Owned steps:** 8 (cross-run memory), 9 (time-travel + concurrent
branches). Co-owner of the SSE event types `fork-created` and
`memory-pattern-stored` with Person 3.

**Skills required:** `asyncio` (`create_task`, `gather` semantics —
see Appendix A §A.4 gotchas), LangGraph time-travel API
(`get_state_history`, `update_state`, `ainvoke(None, config)`),
Postgres.

**Branches you create:**
- `step-9/time-travel-branches` (PR target: main, after step 7 lands)
- `step-8/cross-run-memory` (PR target: main, after step 9 if you
  prefer; can be parallel)

**While step 7 is in flight:**
- Read Appendix A end-to-end. Internalize the 3 gotchas.
- Sketch `branches.py` with stubs (`worktree_add`, `branch_registry`,
  `cancel_branch`) and the test cases you'll write in
  `test_branches.py`. PR these as a draft.
- Read INTERFACES.md §6.3 (forks endpoint) so step 10 has a contract
  to consume.

**First action after step 7 lands:**
```bash
git checkout main && git pull   # contains step 7's async refactor
git checkout -b step-9/time-travel-branches
# Implement branches.py per Appendix A §A.3 Pieces 1–5.
# Test with the asserts from BUILD_ORDER step 9 DoD.
```

### Person 3 — API Layer (REST + SSE)

**Mission:** Land step 10. The frontend (Person 4) consumes your
contract.

**Owned steps:** 10 (primary). Secondary owner of CLI's `fork`
subcommand (step 12).

**Skills required:** FastAPI, SSE, Pydantic (response models),
asyncio. Familiarity with INTERFACES.md §6 + §7 verbatim.

**Branches you create:**
- `step-10/api-sse` (PR target: main, after steps 7+9 land)

**While step 7+9 are in flight:**
- Build `app/main.py` skeleton + `app/streaming.py` event registry
  with the closed-set rule from §7.3. Both can be written and
  unit-tested without Postgres or LangGraph (use fixture data).
- Stub the API endpoints returning fixture data from the
  `INTERFACES.md` example payloads. Person 4 can wire the frontend
  against this immediately.
- Write `scripts/smoke_api.py` against the stubs.

**First action:**
```bash
git checkout main && git pull
git checkout -b step-10/api-sse
# Build app/main.py + app/streaming.py + app/api/{runs, checkpoints,
# forks, memory, events}.py with fixture data.
# Once step 7 lands, swap fixtures for real Postgres reads.
# Once step 9 lands, wire fork POST → branches.worktree_add.
```

### Person 4 — Frontend Lead + Calibration

**Mission:** Land step 11 (the largest piece). In parallel, fix the
eval calibration so the demo arc has headroom.

**Owned steps:** 11 (primary). Co-owner of step 13 (demo acceptance)
with the rest of the team. Owner of eval recalibration.

**Skills required:** Next.js 16, TypeScript, ReactFlow, D3, Monaco
editor, Tailwind 4, EventSource API, basic Playwright. Plus a willingness
to read INTERFACES.md verbatim — your component contracts come from there.

**Branches you create:**
- `step-11/frontend` (PR target: main; **start immediately**, can
  develop against fixtures)
- `step-12/eval-recalibration` (small branch, can land independently)

**First action — recalibration (do this first; <30 min):**
```bash
git checkout main && git pull
git checkout -b step-12/eval-recalibration
# Pick option A, B, or C from §4.2 above. My recommendation: option B
# (set MAX_ACT_TURNS = 6 in agents/baseline.py).
# Verify with `meta-harness benchmark --candidate baseline --trials 1
# --workers 1` that baseline now lands in [0.40, 0.60] on a single
# pass. Update DEFINITION_OF_DONE.md if option A or C is taken.
```

**Then start the frontend:**
```bash
git checkout main && git pull
git checkout -b step-11/frontend
mkdir -p frontend && cd frontend
npx create-next-app@latest . --typescript --tailwind --app --eslint --no-src-dir
# Component scaffolding: 6 files in components/ + 2 in lib/
# Use INTERFACES.md §6 + §7 as the API contract.
# For the first hour, hardcode fixture data; integrate with Person 3's
# stubs as soon as they're up.
```

**Demo-day priority order if time-pressed:**
1. The candidate trajectory tree (D3) — this is the demo hero
2. The state graph viz (ReactFlow) — second-most-impressive
3. The diff viewer (Monaco) — needed for the "the agent rewrote the
   agent" beat
4. The score chart + Pareto frontier — supporting view
5. The memory panel — short demo beat (10 sec)
6. The fork modal — UX, not visual hero

If any one of 1–3 has a bug 30 min before demo, ship a static
fallback. The other two carry the demo.

---

## 7. Branch + Merge Strategy

### Conventions

- **Trunk-based with short-lived branches.** Every step's branch lives
  no longer than ~3 hours. Merge to `main` as soon as DoD passes.
- **Branch names** follow `step-N/<short-name>` (e.g.
  `step-7/persistence-async`).
- **One PR per step.** PR title = step DoD line from BUILD_ORDER.
- **PR body includes:** the literal DoD command + its captured output,
  any new tests, any breaking changes, links to the BUILD_ORDER row
  it satisfies.
- **`main` is always green.** If your DoD command fails after merging,
  revert immediately.
- **Force-push to your own branch is fine; never force-push to `main`.**

### Merge order constraint

```
step-7 ──┬─→ step-8
         ├─→ step-9 ──→ step-10 ──→ step-11 (real integration)
         │                            │
         │                            └ Person 4 starts step 11 in parallel against fixtures
         └ step-12 (eval recalibration) — independent of steps 7-11

(everything) ──→ step-13 (demo acceptance)
```

### Pre-merge checklist (every PR)

- [ ] DoD command output pasted in PR body, exit 0.
- [ ] All LLM-free tests pass: `cd backend && uv run pytest tests/ -q`
  (after step 7+, also `pytest -m asyncio`).
- [ ] `INTERFACES.md` updated if you changed any cross-component
  contract — same commit. **Never silently change a contract.**
- [ ] Self-review: any `_partial`, `TODO`, or `XXX` comments? Address
  or surface as an issue before merging.

---

## 8. Coordination Cadence

### Sync ritual

- **15-minute standup** every hour on the hour. 1 minute per person:
  what just landed, what blocks you, ETA on next checkpoint.
- **Integration window** at the top of every 2 hours (HH:00). Every
  branch tries to merge to `main`; conflicts get resolved live.
- **Pair on the merge** if anyone's branch touches a file someone
  else just modified — no async conflict resolution.

### Communication norms

- **Surface blockers immediately**, not at the next standup. If you're
  stuck for 20 minutes, ask in chat. The rest of the team has context.
- **No silent rebases on others' branches.** If you rebase Person 2's
  branch onto your work, tell them in the PR thread before pushing.
- **All decisions go in writing.** If a verbal decision changes a
  contract in `INTERFACES.md`, edit the doc in the same PR.

### When something breaks

1. **Revert main** to the last green commit. Don't try to forward-fix
   under time pressure.
2. **Pair on the root cause** for 10 minutes; if it's not obvious,
   surface to the whole team.
3. **Document in the PR thread** so the same trap doesn't catch the
   next person.

---

## 9. Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Step 7's async refactor breaks the test suite | High | High | Person 1 keeps `test_inner.py` green throughout the refactor. PR shows green CI before review. |
| Postgres schema migration fails on first `setup()` call | Medium | Medium | Person 1 wipes the volume (`docker compose down -v`) and re-creates if migrations error. |
| Fork demo doesn't visibly create a new branch in the UI | Medium | High (demo killer) | Pre-prepared fork from a yesterday-equivalent run as a fallback. Person 4 wires this in step 11. |
| Anthropic rate limit hits during the live demo | Medium | High | We're on Haiku 4.5 (higher limits). Pre-warmed cache by running the demo 30 min before. Backup: pre-recorded video. |
| Frontend takes longer than 5–7 hr | High | Medium | Person 4 ships components in priority order (§6 Person 4 list). MVP each, polish later. |
| Eval recalibration still leaves 100% baseline | Low | High | Person 4 has option A (harder tasks), B (lower MAX_ACT_TURNS), C (weaker model) — try in that order. If none lands, the demo arc shifts to "0.85 → 0.92" and the narrative adjusts. |
| Two people conflict-edit the same file | Medium | Low | Branches owned per file (per §6 ownership). Hourly merges minimize conflict surface. |
| Someone changes `INTERFACES.md` without updating the consumer | Medium | High | PR template requires `INTERFACES.md`-change PRs to also touch the consumer or include a TODO link with a reviewer. |
| `claude` CLI subscription auth expires mid-demo | Low | Catastrophic | Verify `claude /login` status 30 min before demo. Have a backup API key ready (with a higher tier if possible). |
| Process isolation isn't enough; an agent command corrupts the host | Low | Catastrophic | Tasks are trusted, hand-written. Honest about not being Docker-isolated. Don't run untrusted candidates. |

---

## 10. Demo Acceptance Walkthrough

The 90-second demo from `docs/DEFINITION_OF_DONE.md`. Read it once
before the dry-run.

```
[0:00–0:08] HOOK
"Stanford published Meta-Harness four weeks ago — Lee, Khattab, Finn.
Their proposer agent reads execution traces and rewrites the harness,
beating ACE by 7.7 points. But their loop is linear. We mapped it onto
LangGraph and made it a tree."

[0:08–0:23] ACT 1 — Local launch
[Browser at localhost:3000. Click "New run" → "Coding agent template"
 → "Start". Run dashboard renders.]
"30 seconds, no cloud. Five-task eval. Baseline: 62%."

[0:23–0:53] ACT 2 — Linear loop
[State graph populates. Iterations stream in via SSE.]
  Iter 1: retry on schema_drift errors        → 0.70 (+0.08) ✓
  Iter 2: stricter tool-description hashing   → 0.66 (−0.04) ✗
  Iter 3: early-exit on auth failures         → 0.74 (+0.04) ✓
  Iter 4: more specific tool descriptions     → 0.80 (+0.06) ✓ NEW BEST
"Stanford's regime — exactly. But here's where it gets interesting."

[0:53–1:20] ACT 3 — Time-travel + memory
[Right-click iter-2 in the trajectory tree → "Fork from here" →
 modal opens → edit proposer_prior → Resume. Tree visibly branches.]
"Rewinding to iteration 2. Forking with a different prior."
[Both branches grow concurrently. Compare view side-by-side.]
  Iter 2′: rewrite tool descriptions w/ examples → 0.78 (+0.16) ✓
  Iter 3′: add few-shot demos to descriptions    → 0.85 (+0.07) ✓ GLOBAL BEST
"Two branches. Original 0.80. Fork 0.85. The meta-harness loop is no
longer a sequence — it's a search tree."
[Click memory panel.]
"And LangGraph's cross-thread memory means the next run starts smarter."

[1:20–1:30] CLOSE
"Time-travel for Meta-Harness. Built on LangGraph state machines.
Secure, consistent, reversible — by construction. Open source.
That's Meta-Harness. One spark."
```

**Acceptance is binary.** See `DEFINITION_OF_DONE.md` for the
checklist. Every box must tick before the run is "done."

---

## 11. Quickstart for Anyone Joining

```bash
# 1. Clone + workspace install
git clone <repo-url> meta-harness && cd meta-harness
cp .env.example .env  # then add ANTHROPIC_API_KEY (we share one in #channel)
uv sync

# 2. Postgres
docker compose -f infra/docker-compose.yml up -d postgres
docker logs meta-harness-postgres  # confirm "database system is ready"

# 3. Smoke-test the inner loop end-to-end
uv run meta-harness inner --task task-001-fix-typo --candidate baseline
# expect: score=1.0 (or 0.0; either is a working trial), 8 trace files written

# 4. Smoke-test the outer loop with mocks
uv run meta-harness loop --proposer mock --mock-bench --budget 2 --fresh --run-name smoke-mock
# expect: pending_eval, frontier_val (with dominated_by_names), evolution_summary, all written

# 5. (Optional, costs ~$1) Smoke-test the real proposer
uv run meta-harness loop --proposer claude --budget 1 --fresh --mock-bench --run-name smoke-claude
# expect: agents/<descriptive-name>.py written by claude;
# proposer-sessions/iter-1/{session.json, transcript.txt, ...} present

# 6. Run the test suite
cd backend && uv run pytest tests/ -q
# expect: 42 passed (1 skipped if ANTHROPIC_API_KEY not exported)

# 7. Pick a step from §6 and start a branch
git checkout -b step-N/your-name
```

### Known-good entry points to read first

- `backend/app/cli.py` — the CLI shape; what each subcommand does.
- `backend/app/meta_harness/outer.py` — `OuterLoopRunner` is the
  outer state machine.
- `backend/app/meta_harness/inner.py` — the 5-phase coding agent.
- `backend/app/meta_harness/proposer.py` — both `mock_propose` and
  `claude_propose` (the latter mirrors Stanford's `claude_wrapper.py`).
- `skills/meta-harness-coding-agent/SKILL.md` — what the proposer
  actually reads on every iteration.

---

## 12. The Single Most Important Rule

**`INTERFACES.md` is the contract.** Every cross-component change
that touches a state schema, JSON file shape, REST endpoint, SSE
event type, tool I/O, override point, or SKILL.md section requires
the **same PR** to update `INTERFACES.md` AND every consumer of the
changed contract.

If you find yourself thinking "I'll update the doc later" — stop.
Update it now or revert your code change. The substrate-as-contribution
story falls apart the moment the contracts and the implementation
disagree.

---

*Built with Meta-Harness, on LangGraph state machines.
Secure, consistent, reversible — by construction. Open source.
One spark.*
