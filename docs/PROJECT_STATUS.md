# Project Status — Meta-Harness

> Last updated: 2026-04-26

Meta-Harness is a LangGraph-native substrate for self-improving coding agent harnesses, implementing the Stanford Meta-Harness paradigm. This document tracks what has been accomplished and what remains.

---

## Current Workspace Snapshot

As of 2026-04-26, the codebase has the intended frontend/backend integration
points in place, but the current local workspace should not be treated as fully
green.

- The dashboard is wired to the backend through `NEXT_PUBLIC_API_BASE_URL`,
  defaulting to `http://localhost:8000`.
- The frontend calls the FastAPI REST API for health, run listing, run detail,
  checkpoints, forks, and memory.
- Live updates are wired through SSE via `GET /runs/{run_id}/stream`.
- The backend exposes the matching FastAPI routers and has CORS enabled for the
  local Next.js dev origin (`http://localhost:3000`).
- The dashboard still has mock/demo fallback behavior for the demo run when the
  backend is unavailable.
- Candidate diff and test-output panels are not yet backed by real API
  endpoints; the frontend helpers currently return `null` for those views.

Latest local verification attempt:

```powershell
cd backend
uv run pytest tests -q
```

`uv` was not available on PATH in this shell, so verification was retried with
the existing virtual environment:

```powershell
cd backend
..\.venv\Scripts\python -m pytest tests -q
```

Result: **31 passed, 21 skipped, 3 failed, 31 errors** in the current Windows
workspace. The failures/errors are mostly environment and platform related:
pytest could not read/create some temp and cache directories, some tests assume
Unix-style `/tmp` paths, and `pytest-asyncio` was not detected by the active
environment. Frontend build/lint/type checks were not rerun during this
snapshot.

---

## Build Progress

| Step | Name | Status | Tests |
|------|------|--------|-------|
| 1 | Repo skeleton + Postgres + first eval task | ✅ Complete | — |
| 2 | Sandbox + 6 fixed tools | ✅ Complete | 20 tests |
| 3 | Inner StateGraph end-to-end (real LLM) | ✅ Complete | 1 test (requires API key) |
| 4 | Five eval tasks + multi-trial scoring | ✅ Complete | — |
| 5 | Outer loop: propose → validate → benchmark → update_frontier | ✅ Complete | 1 test |
| 6 | Claude CLI proposer + SKILL.md | ✅ Complete | — |
| 7 | AsyncPostgresSaver checkpointing | ✅ Complete | 4 tests |
| 8 | Cross-run memory (PostgresStore) | ✅ Complete | 15 tests |
| 9 | Time-travel: history + fork + concurrent branches | ✅ Complete | 5 tests |
| 10 | FastAPI REST + SSE with closed-set registry | ✅ Complete | 4 tests |
| 11 | Frontend dashboard + visualizations | ✅ Complete | 7 Playwright tests |
| 12 | CLI completeness + holdout evaluation | ✅ Complete | CLI tests + 2 holdout tasks |
| 13 | End-to-end demo dry-run (acceptance) | ❌ Not started | — |

**Overall: 12 of 13 steps complete.**

---

## What's Been Built

### Core Engine (Steps 1–8)

- **`backend/app/meta_harness/`** — the full backend orchestration layer:
  - `state.py` — `MetaHarnessState`, `CodingAgentState`, `Candidate` TypedDicts
  - `harness.py` — `CodingAgentHarness` base class with 11 override points
  - `inner.py` — 5-phase inner state machine (orient → plan → act → verify → submit)
  - `outer.py` — 4-node outer loop (propose → validate → benchmark → update_frontier) with SSE emit hooks and memory integration
  - `tools.py` — 6 fixed tools: `read_file`, `write_file`, `apply_patch`, `run_bash`, `grep_search`, `task_complete`
  - `sandbox.py` — process-isolated sandboxes under `/tmp/meta-harness-task-{uuid}/`
  - `proposer.py` — Claude CLI subprocess proposer + mock proposer for testing
  - `frontier.py` — Pareto frontier computation with `dominated_by_names`
  - `persistence.py` — `AsyncPostgresSaver` with connection pooling (`max_size=20`)
  - `memory.py` — `AsyncPostgresStore` wrapper for cross-run learned patterns
  - `branches.py` — branch registry, `worktree_add`, `cancel_branch`, checkpoint history
  - `runs.py` — run directory management, manifest/artifact writing

### REST API (Step 10)

- **`backend/app/api/`** — FastAPI routers:
  - `runs.py` — `POST /runs` (201 + Location), `GET /runs`, `GET /runs/{id}`
  - `checkpoints.py` — `GET /runs/{id}/checkpoints`, `GET /runs/{id}/checkpoints/{ckpt_id}`
  - `forks.py` — `POST /runs/{id}/fork`, branch listing, cancellation, trajectory
  - `memory.py` — `GET /memory/{namespace}`, `POST /memory/{namespace}/search`
  - `events.py` — `GET /runs/{id}/stream` (SSE)
- **`backend/app/streaming.py`** — closed-set SSE event registry with 11 registered event types
- **`backend/app/main.py`** — FastAPI app factory

### CLI

- **`backend/app/cli.py`** — Typer CLI with subcommands:
  - `meta-harness version`
  - `meta-harness inner --task <id> --candidate <name>`
  - `meta-harness benchmark --candidate <name> --trials N`
  - `meta-harness loop --proposer {claude|mock} --budget N [--mock-bench] [--fresh]`
  - `meta-harness resume <run-name>`
  - `meta-harness memory list [--namespace <domain>]`

### Eval Tasks

- 5 search-set tasks in `eval/tasks/`:
  - `task-001-fix-typo` — bug-fix (typo in calculator)
  - `task-002-add-function` — implement a spec
  - `task-003-refactor` — restructure code
  - `task-004-handle-error` — robustness (error handling)
  - `task-005-implement-spec` — multi-file implementation

### Infrastructure

- **Postgres 16** via `infra/docker-compose.yml`
- **`.env` / `.env.example`** — `POSTGRES_DSN`, `ANTHROPIC_API_KEY`
- **`agents/baseline.py`** — the starting harness that all candidates derive from
- **`skills/meta-harness-coding-agent/SKILL.md`** — proposer system prompt with 11 override points

### Test Suite

Historical project status listed the backend suite as **82 passed, 1 skipped**
via `cd backend && uv run pytest tests -q`, with frontend e2e coverage passing
through **7 Playwright tests**.

Current workspace verification on 2026-04-26 did **not** reproduce that green
state. `uv` was not available on PATH, and the fallback command
`cd backend && ..\.venv\Scripts\python -m pytest tests -q` reported **31 passed,
21 skipped, 3 failed, 31 errors**. Treat the suite as currently blocked by
local environment/platform issues until the Windows temp/cache permissions,
`pytest-asyncio` availability, and `/tmp` path assumptions are resolved.

---

## What Remains

### Step 11 — Frontend Dashboard + Visualizations

> **Priority: HIGH** — this is the visual payoff of the entire system.

**Status:** Complete. The dashboard lives in `frontend/dashboard/`.

**Delivered:**
- Next.js 16 app at `localhost:3000`
- Run-detail page with 5 live-updating views:
  1. **ReactFlow** outer-state-graph (propose/validate/benchmark/update_frontier nodes light up)
  2. **D3 trajectory tree** showing branch lineage from `reconstruct_trajectory`
  3. **Monaco unified-diff viewer** for candidate code changes
  4. **Score + frontier chart** (accuracy over iterations, Pareto frontier)
  5. **Memory panel** showing cross-run learned patterns
- Right-click → fork modal (calls `POST /runs/{id}/fork`)
- SSE-driven live updates via `GET /runs/{id}/stream`

**Backend integration points ready:**
- All REST endpoints exist (step 10)
- SSE streaming with 11 event types works
- Branch orchestration and trajectory reconstruction available
- Memory search and listing available

---

### Step 12 — CLI Completeness + Holdout Evaluation

> **Priority: MEDIUM** — the CLI is complete enough for the current build
> order and covered by deterministic smoke tests.

**Status:** Complete. `loop`, `inner`, `benchmark`, `fork`, `init`, `resume`,
and `memory` subcommands are implemented; `--holdout` support writes
`holdout-result.json` for real-bench loops; two holdout tasks are present
under `eval/holdout/`; CLI coverage lives in `backend/tests/test_cli.py`.

---

### Step 13 — End-to-End Demo Dry-Run (Acceptance)

> **Priority: HIGH** — this is the final acceptance gate.

**What's missing:**
- [ ] `scripts/demo_dryrun.sh` — exercises the full demo command from `DEFINITION_OF_DONE.md`
- [ ] Score arc calibration: accuracy should land within ±5% of expected
- [ ] Fork branches should reach ≥0.83 accuracy
- [ ] Total runtime < 8 min, cost < $5
- [ ] Requires `ANTHROPIC_API_KEY` for real Claude proposer runs

---

## Known Issues

| Issue | Severity | Notes |
|-------|----------|-------|
| Postgres healthcheck changed in s9 (uses `AsyncConnection.connect` directly) | Low | Works but causes some test processes to skip Postgres-dependent tests when the event loop policy differs |
| Mock module caching across tests | Fixed | `test_api.py` now cleans `sys.path` and `sys.modules`; `outer.py` invalidates caches before importing |
| SSE `_emit` was not best-effort | Fixed | Wrapped in `try/except` to prevent streaming errors from crashing graph nodes |
| `tokens` / `cost_usd` are zero in real-bench results | Medium | Token aggregation from Anthropic responses is not implemented yet |
| Memory panel still includes demo fixtures | Low | Live memory SSE entries are visible, but historical memory list is partly mocked |
| Backend suite not green in current Windows workspace | High | Latest fallback run: 31 passed, 21 skipped, 3 failed, 31 errors; primary causes are temp/cache permissions, missing pytest-asyncio detection, and Unix `/tmp` assumptions |
| Frontend candidate diff/test output are placeholders | Medium | `getDiff()` and `getTestOutput()` currently return `null`; real candidate diff/test-output endpoints are not wired yet |

---

## Architecture Reference

```
MetaHarness/
├── agents/              # Candidate harness modules (baseline + generated)
├── backend/
│   ├── app/
│   │   ├── api/         # FastAPI REST routers (step 10)
│   │   ├── meta_harness/ # Core engine (steps 1-9)
│   │   ├── cli.py       # Typer CLI
│   │   ├── main.py      # FastAPI app factory
│   │   └── streaming.py # SSE event registry
│   └── tests/           # pytest suite
├── eval/
│   ├── tasks/           # 5 search-set tasks
│   ├── holdout/         # 2 held-out tasks
│   └── score.py         # pytest-based scoring
├── frontend/            # Next.js dashboard
├── infra/               # docker-compose.yml (Postgres 16)
├── sdk/                 # Public SDK package
├── skills/              # SKILL.md (proposer system prompt)
└── docs/                # Architecture, interfaces, build order
```

---

## Key Documents

- [BUILD_ORDER.md](BUILD_ORDER.md) — 13-step topological build plan
- [INTERFACES.md](INTERFACES.md) — state schemas, API contracts, SSE event types
- [STEP_9_HANDOFF.md](STEP_9_HANDOFF.md) — branch orchestration specifics
- [PROJECT_LAYOUT.md](PROJECT_LAYOUT.md) — directory structure and naming
- [TEAM_HANDOFF.md](TEAM_HANDOFF.md) — onboarding and context for new developers
