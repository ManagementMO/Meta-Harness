# BUILD_ORDER.md — topological execution sequence

*Thirteen numbered steps. Each one ships a verifiable, runnable slice.
After each step: run the DoD command, commit
`step N: <goal> — <what works now>`, then pause for review.*

Conventions:
- All paths are repo-root-relative.
- "Done when" is one literal command (or a tight `&&`-chain) whose
  exit status proves the slice works.
- "Unblocks" listj s step numbers that depend on this one.
- Terminology in this doc matches `INTERFACES.md` exactly.

---

## (1) Repo skeleton + Postgres + first eval task

**Goal.** uv workspace boots; Postgres healthy; one task scoreable
without any LLM.

**Files.** `pyproject.toml` (workspace root with `[tool.uv.workspace]
members = ["sdk", "backend"]`), `sdk/pyproject.toml`,
`sdk/meta_harness/__init__.py`, `backend/pyproject.toml`,
`backend/app/__init__.py`, `infra/docker-compose.yml`, `eval/score.py`,
`eval/tasks/task-001-fix-typo/{task.json, workspace/calculator.py,
workspace/tests/test_calculator.py}`, `.env.example`, `.gitignore`,
`README.md`.

**Done when.**
```bash
docker compose -f infra/docker-compose.yml up -d postgres \
  && uv sync \
  && uv run python -m eval.score --task task-001-fix-typo
# stdout: {"task": "task-001-fix-typo", "passed": false, "score": 0.0, ...}
# (false because the buggy calculator hasn't been fixed)
```

**Unblocks.** 2, 3.

---

## (2) Sandbox + 6 fixed tools (LLM-free)

**Goal.** `read_file`, `apply_patch`, `write_file`, `run_bash`,
`grep_search`, `task_complete` all implemented; sandbox enforces
process isolation; structured error returns work (esp. `apply_patch`'s
`context_echo`).

**Files.** `backend/app/meta_harness/sandbox.py`,
`backend/app/meta_harness/tools.py`,
`backend/tests/test_tools.py`, `backend/tests/test_sandbox.py`.

**Done when.**
```bash
cd backend && uv run pytest tests/test_tools.py tests/test_sandbox.py -v
# all green; key cases: apply_patch context_mismatch returns context_echo;
# write_file errors with file_exists; run_bash enforces 30s timeout;
# sandbox dir created under /tmp/meta-harness-task-{uuid}/.
```

**Unblocks.** 3.

---

## (3) Inner StateGraph end-to-end on one task (real LLM)

**Goal.** `CodingAgentHarness` baseline + 5-phase inner state machine
runs one trial on task-001 against a real Anthropic API call, writes
all per-trial trace artifacts.

**Files.** `backend/app/meta_harness/state.py` (`CodingAgentState`,
`MetaHarnessState`, `Candidate`), `backend/app/meta_harness/harness.py`
(base class + 11 override points), `backend/app/meta_harness/inner.py`
(StateGraph + node fns), `backend/app/cli.py` (typer skeleton with
`inner` subcommand), `agents/baseline.py` (the starting harness),
`backend/tests/test_inner.py`.

**Done when.**
```bash
ANTHROPIC_API_KEY=... uv run meta-harness inner \
  --task task-001-fix-typo --candidate baseline
# stdout reports a passing pytest run AND
# runs/<run-id>/candidates/baseline/traces/task-001-trial-1/ contains
# orient.json, plan.json, act-messages.jsonl, act-tools.jsonl,
# verify.json, score.json, summary.md, final-files.json.
```

**Unblocks.** 4, 5.

---

## (4) Five eval tasks + multi-trial scoring

**Goal.** All 5 search-set tasks operational; baseline harness scored
across 5 tasks × 5 trials; calibrated baseline accuracy lands in
[0.40, 0.60].

**Files.** `eval/tasks/task-002-add-function/`,
`eval/tasks/task-003-refactor/`, `eval/tasks/task-004-handle-error/`,
`eval/tasks/task-005-implement-spec/` (each: `task.json` + `workspace/`),
`eval/score.py` (multi-task wrapper).

**Done when.**
```bash
uv run meta-harness benchmark --candidate baseline --trials 5
# writes runs/<run-id>/candidates/baseline/eval-result.json with
# n_tasks=5, n_trials_per_task=5, accuracy in [0.40, 0.60].
```

**Unblocks.** 5.

---

## (5) Outer StateGraph with mocked proposer

**Goal.** `propose → validate → benchmark → update_frontier` all real;
proposer mocked (returns hardcoded candidates from `agents/`); writes
`pending_eval.json`, `frontier_val.json` (with `dominated_by_names`),
`evolution_summary.jsonl` (with `parent_candidate_name`).

**Files.** `backend/app/meta_harness/outer.py` (StateGraph + 4 node fns),
`backend/app/meta_harness/frontier.py` (Pareto computation),
`backend/app/meta_harness/runs.py` (filesystem lifecycle),
`backend/app/meta_harness/proposer.py` (mock-mode branch),
`backend/tests/test_outer.py`, `backend/tests/test_frontier.py`.

**Done when.**
```bash
uv run meta-harness loop --proposer mock --budget 2 --fresh
# 2 iterations complete; runs/<run-id>/{pending_eval.json,
# frontier_val.json, evolution_summary.jsonl} all present;
# frontier_val.json has dominated_by_names per candidate;
# evolution_summary.jsonl has parent_candidate_name per row.
```

**Unblocks.** 6.

---

## (6) Real proposer (claude_wrapper.py) + SKILL.md

**Goal.** Spawn `claude` CLI subprocess with all the right flags; parse
stream-json; SKILL.md `--append-system-prompt`'d; writes a real new
`agents/<n>.py` and `pending_eval.json`; logs to
`proposer-sessions/iter-N/`.

**Files.** `backend/app/meta_harness/proposer.py` (real path, mirrors
Stanford's `claude_wrapper.py` shape), `skills/meta-harness-coding-agent/SKILL.md`
(with frontmatter + 6 required body sections), `backend/tests/test_proposer.py`.

**Done when.**
```bash
which claude && uv run meta-harness loop --proposer claude --budget 1 --fresh
# proposer-sessions/iter-1/{session.json, transcript.txt,
# system_prompt.txt, events.jsonl} all present;
# agents/<new-name>.py created by the proposer;
# pending_eval.json names the new candidate with import_path,
# hypothesis, axis, expected_score_delta.
```

**Unblocks.** 7.

---

## (7) AsyncPostgresSaver checkpointing + connection pool

**Goal.** Every node transition writes a checkpoint to Postgres; runs
survive `SIGINT`; resume continues exactly from the last checkpoint.
Pool sized `max_size=20` per Appendix A.

**Files.** `backend/app/meta_harness/persistence.py`, plus rewires of
`outer.py` and `inner.py` `compile()` calls,
`backend/tests/test_persistence.py`.

**Done when.**
```bash
uv run meta-harness loop --proposer mock --budget 3 --fresh \
  --run-name resume-test &
sleep 30 && kill -INT $! && wait $! 2>/dev/null
uv run meta-harness resume resume-test
# resume completes the remaining iterations; final iteration count == 3;
# no duplicate iterations in evolution_summary.jsonl.
```

**Unblocks.** 8, 9, 10.

---

## (8) Cross-run memory (PostgresStore)

**Goal.** End-of-run writes patterns to `("learned_patterns", "<domain>")`
namespace; start-of-run reads relevant patterns and feeds them into the
proposer's `--append-system-prompt`. Works across separate process runs.

**Files.** `backend/app/meta_harness/memory.py`, hooks in
`update_frontier` (write) and `propose` (read),
`backend/tests/test_memory.py`.

**Done when.**
```bash
uv run meta-harness loop --proposer claude --budget 3 --fresh --run-name run-a
uv run meta-harness loop --proposer claude --budget 3 --fresh --run-name run-b
uv run meta-harness memory list --namespace coding-agent
# returns ≥1 entry written by run-a;
# grep -l "<entry-key>" runs/run-b/proposer-sessions/iter-1/system_prompt.txt
# (run-b's proposer received run-a's pattern).
```

**Unblocks.** 11.

---

## (9) Time-travel: history + fork + concurrent branches

**Goal.** `get_state_history` exposed; fork via `update_state` +
`ainvoke(None, fork_config)`; `branch_registry` tracks
`asyncio.Task`s; cancellation works; two branches run concurrently
against shared `AsyncPostgresSaver` without deadlock.

**Files.** `backend/app/meta_harness/branches.py` (`worktree_add`,
`branch_registry`, `cancel_branch`),
`backend/tests/test_branches.py`.

**Done when.**
```bash
cd backend && uv run pytest tests/test_branches.py -v
# Tests cover:
#  - get_state_history returns N checkpoints for N node transitions
#  - worktree_add(parent_ckpt, mods) creates a new thread with
#    parent_thread_id pointer; concurrent task starts running
#  - both branches complete, no deadlock; final state per branch correct
#  - cancel_branch terminates a live task and writes "cancelled" status
```

**Unblocks.** 10, 11.

---

## (10) FastAPI REST + SSE with closed-set registry

**Goal.** All §6 endpoints; SSE channel registry rejects unregistered
event types with 500-class error; `POST /runs` returns **201 Created**
with `Location` header; per-run multiplex with `thread_id` per event.

**Files.** `backend/app/main.py`, `backend/app/streaming.py` (registry
+ allowlist), `backend/app/api/{runs.py, checkpoints.py, forks.py,
memory.py, events.py}`, `backend/tests/test_api.py`,
`backend/tests/test_streaming.py`.

**Done when.**
```bash
(cd backend && uv run uvicorn app.main:app --port 8000 --reload &) \
  && sleep 2 \
  && uv run python scripts/smoke_api.py
# scripts/smoke_api.py exercises: POST /runs (asserts 201 + Location),
# GET /runs/{id}/checkpoints, POST /runs/{id}/fork,
# GET /runs/{id}/stream over a 2-iter mock run, asserts that all 11
# event types from §7.2 fire at least once, asserts that emitting an
# unregistered event type raises a 500.
```

**Unblocks.** 11, 13.

---

## (11) Frontend dashboard + visualizations

**Goal.** Next.js 16 dashboard at `localhost:3000`; the run-detail
page renders ReactFlow outer-state-graph, D3 trajectory tree, Monaco
unified-diff viewer, score+frontier chart, memory panel, and a
right-click → fork modal. All five views update live via SSE.

**Files.** `frontend/{package.json, next.config.js, tsconfig.json,
tailwind.config.ts}`, `frontend/app/{layout.tsx, page.tsx,
runs/[run_id]/page.tsx}`, `frontend/components/{StateGraph.tsx,
TrajectoryTree.tsx, DiffViewer.tsx, ScoreChart.tsx, MemoryPanel.tsx,
ForkModal.tsx}`, `frontend/lib/{api.ts, sse.ts}`.

**Done when.**
```bash
# Backend + Postgres already up. Then:
(cd frontend && npm install && npm run build && npm run dev &) \
  && sleep 5 \
  && npx playwright test e2e/dashboard.spec.ts
# Playwright e2e: starts a mock run via REST, navigates to /runs/{id},
# asserts ReactFlow nodes light up, asserts a candidate appears in
# the trajectory tree, asserts a diff renders in Monaco, asserts a
# score point appears, asserts right-click → fork modal opens.
```

**Unblocks.** 12, 13.

---

## (12) CLI completeness + holdout evaluation

**Goal.** `meta-harness` CLI exposes `loop`, `inner`, `benchmark`,
`fork`, `resume`, `init`, `memory`; `--holdout` flag runs the
final-best candidate against `eval/holdout/` and reports separately.

**Files.** `backend/app/cli.py` (full typer surface),
`eval/holdout/{task-006-…/, task-007-…/}` (held-out tasks the proposer
never sees), `backend/tests/test_cli.py`.

**Done when.**
```bash
uv run meta-harness loop --proposer claude --budget 5 --fresh \
  --holdout --run-name holdout-test
# evolution_summary.jsonl + frontier_val.json present (search set);
# runs/holdout-test/holdout-result.json present, distinct numbers from
# search set; CLI exit 0.
```

**Unblocks.** 13.

---

## (13) End-to-end demo dry-run (acceptance)

**Goal.** Pass DEFINITION_OF_DONE.md verbatim. Score arc lands within
±5% of expected; fork branches reach ≥0.83; total runtime <8 min;
cost <$5.

**Files.** none new; exercises everything above. Optional: tighten
calibration on the 5 eval tasks if the score arc drifts.

**Done when.**
```bash
bash scripts/demo_dryrun.sh
# scripts/demo_dryrun.sh runs the literal demo command from
# DEFINITION_OF_DONE.md and asserts every acceptance bullet listed
# there. Exit 0 = ship.
```

**Unblocks.** SHIP.

---

## Notes on Phase 2 execution protocol

- **One step at a time.** After each step, run the DoD command,
  confirm exit 0, commit
  (`git commit -m "step N: <goal> — <one line>"`), state which step is
  next and what it unblocks, then **pause for the user to acknowledge**
  before continuing.
- **No backfill.** If a step's DoD fails, fix the step before moving
  on. Don't paper over with a TODO that gets resolved "later."
- **Reference docs are frozen.** ARCHITECTURE_SECTION_1.md,
  PROJECT_LAYOUT.md, INTERFACES.md, DEFINITION_OF_DONE.md are the
  canonical contracts. If implementation reveals a contract is wrong,
  edit the doc + restate the change before continuing.
