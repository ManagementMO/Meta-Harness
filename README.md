# Meta-Harness

> *Stanford's Meta-Harness paper had a linear loop. We mapped it onto LangGraph and made it a tree.*

LangGraph-native substrate for **self-improving agent harnesses**. Applies
the Stanford Meta-Harness paradigm
([arXiv:2603.28052](https://arxiv.org/abs/2603.28052),
[yoonholee.com/meta-harness](https://yoonholee.com/meta-harness/)) to a
coding-agent domain — expressed as **two LangGraph state machines** with
Postgres-backed checkpointing, time-travel forking, and cross-run memory.

A creative reinterpretation of the work at
[yoonholee.com/meta-harness](https://yoonholee.com/meta-harness/).

---

## The insight

The Stanford paper showed that an outer-loop agent reading raw execution
traces and rewriting an inner-loop harness beats every prior text optimizer
— **+7.7 points over ACE with 4× fewer context tokens, top-2 on
TerminalBench-2**.

But their loop is **linear**: `iter 1 → 2 → 3 → 4`. Real harness optimization
needs branching: rewind to iter 2, try a different proposer prior, fork,
compare. By mapping the loop onto LangGraph state machines, three properties
fall out **by construction**:

| Property | Mechanism |
|---|---|
| **Secure** | Each candidate is a sandboxed subgraph — a buggy candidate cannot corrupt the run |
| **Consistent** | Every state transition is checkpointed via `AsyncPostgresSaver`; replays are deterministic |
| **Reversible** | Time-travel via `get_state_history` + `update_state` + `ainvoke(None, ckpt_id)` |

The substrate IS the contribution.

---

## Architecture

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
      │
      │  ▸ 6 fixed tools (read_file, apply_patch, write_file,
      │       run_bash, grep_search, task_complete) — the contract
      │  ▸ 11 override points (system prompt, plan template, turn
      │       budget, retry policy, tool-result formatting, ...)
      │       — the search space
                                  │
                                  ▼  traces, scores, file diffs streamed via SSE
   DASHBOARD  (Next.js 15)
   ───────────────────────
   ▸ outer state graph (ReactFlow) — live nodes lighting up per iteration
   ▸ candidate trajectory tree (D3) — branches when you fork a checkpoint
   ▸ code diff viewer (Monaco) — agents/<n>.py vs parent, live
   ▸ score chart + Pareto frontier — accuracy × context tokens
   ▸ cross-run memory panel — patterns learned by prior runs
   ▸ right-click any checkpoint → fork modal → resume on a new branch
```

---

## The demo arc

```text
Baseline harness, 5 coding-agent tasks × 5 trials each, on Haiku 4.5:

Iter 1:   retry on schema_drift errors          →  0.70  (+0.08)  ✓
Iter 2:   stricter tool-description hashing     →  0.66  (-0.04)  ✗
Iter 3:   early-exit on auth failures           →  0.74  (+0.04)  ✓
Iter 4:   more specific tool descriptions       →  0.80  (+0.06)  ✓ NEW BEST

      ┌─ right-click iter 2  →  "Fork from here"  →  edit proposer prior  ┐
      │                                                                   │
      ▼                                                                   ▼
Iter 2':  rewrite tool descriptions w/ examples  →  0.78  (+0.16)  ✓
Iter 3':  add few-shot demos to descriptions     →  0.85  (+0.07)  ✓ GLOBAL BEST

Two branches. Both Pareto-optimal at different (accuracy, tokens) tradeoffs.
The meta-harness loop is no longer a sequence — it's a search tree.
```

---

## Quickstart

**Prerequisites**

- Python 3.11+ and [uv](https://github.com/astral-sh/uv)
- Docker (for local Postgres)
- Node.js 20+ + npm (for the dashboard, optional until step 11)
- The [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code/overview) (`claude`) for the real proposer
- An Anthropic API key (`ANTHROPIC_API_KEY`)

**Get running**

```bash
git clone https://github.com/ManagementMO/Meta-Harness.git
cd Meta-Harness
cp .env.example .env                                          # add ANTHROPIC_API_KEY
uv sync
docker compose -f infra/docker-compose.yml up -d postgres

# Run the test suite (47 passes: 42 LLM-free + 4 Postgres-backed + 1 live LLM)
cd backend && uv run pytest tests/ -q

# Smoke-test the inner loop end-to-end on one task (~24 s, ~$0.05)
uv run meta-harness inner --task task-001-fix-typo --candidate baseline

# Run the meta-harness with the mock proposer (no LLM, completes in <1 s)
uv run meta-harness loop --proposer mock --mock-bench --budget 2 --fresh

# Run with the real claude CLI proposer (~3 min on subscription auth)
uv run meta-harness loop --proposer claude --budget 1 --fresh --mock-bench

# Resume an interrupted run from its last Postgres checkpoint
uv run meta-harness resume <run-name>
```

---

## Build status

The implementation is tracked as a topological sequence of 13 verified
steps in `docs/BUILD_ORDER.md`, each with a literal **definition-of-done**
command that proves it works. **7 of 13 complete; 47 tests green.**

| Step | Goal | Status |
|---|---|---|
| 1 | Repo skeleton + Postgres + first eval task | ✓ |
| 2 | Sandbox + 6 fixed inner-loop tools | ✓ |
| 3 | Inner StateGraph end-to-end on one task (live LLM) | ✓ |
| 4 | 5 eval tasks + multi-trial benchmark | ✓ |
| 5 | Outer StateGraph + mock proposer + Pareto frontier | ✓ |
| 6 | Real proposer (`claude` CLI subprocess) + SKILL.md | ✓ |
| 7 | AsyncPostgresSaver + full async refactor | ✓ |
| 8 | Cross-run memory (PostgresStore) | next |
| 9 | Time-travel + concurrent branches | next |
| 10 | FastAPI REST + SSE with closed-set event registry | next |
| 11 | Frontend dashboard (Next.js + ReactFlow + D3 + Monaco) | next |
| 12 | CLI completeness + holdout evaluation | next |
| 13 | End-to-end demo dry-run (formal acceptance) | final |

Run `cd backend && uv run pytest tests/ -q` at any commit to confirm the
test floor.

---

## What's distinctive about this implementation

1. **Two LangGraph state machines, not one.** The outer machine evolves
   the inner machine's source code. Both are checkpointed; both will
   support time-travel.
2. **The "meta-harness tool" is a SKILL.md, not a framework feature.**
   ~150 lines of Markdown injected via `--append-system-prompt` when
   the proposer's `claude` subprocess is spawned. Anti-overfitting and
   anti-parameter-tuning rules live there; they're load-bearing per the
   paper's Section 5 ablations.
3. **The inner loop has a fixed contract and an evolvable shape.**
   Six tools (`read_file`, `apply_patch`, `write_file`, `run_bash`,
   `grep_search`, `task_complete`) are the contract with the evaluator
   and **cannot be modified** by candidates. Eleven override points
   define the search space.
4. **`apply_patch` returns `context_echo` on mismatch.** When a unified
   diff fails to apply, the tool surfaces the file's actual current
   content at the failed range so the model fixes the patch without
   re-reading the file.
5. **Forks are concurrent, not sequential.** Per Appendix A,
   `asyncio.create_task` over `graph.ainvoke` calls share a single
   `AsyncPostgresSaver`; both branches grow on the dashboard at once.
6. **Cross-run memory persists across runs.** A pattern learned in
   run A flows into run B's proposer system prompt, so each new run
   starts smarter than cold.

---

## Repository layout

```
meta-harness/
├── backend/                                   # FastAPI + LangGraph
│   ├── app/
│   │   ├── cli.py                             # `meta-harness` CLI (typer)
│   │   ├── main.py                            # FastAPI app entry (step 10)
│   │   └── meta_harness/                      # internal namespace
│   │       ├── outer.py                       # outer 4-node StateGraph
│   │       ├── inner.py                       # inner 5-phase StateGraph
│   │       ├── state.py                       # MetaHarnessState + CodingAgentState
│   │       ├── harness.py                     # CodingAgentHarness (11 override points)
│   │       ├── proposer.py                    # claude_propose + mock_propose
│   │       ├── tools.py                       # 6 fixed inner-loop tools
│   │       ├── sandbox.py                     # /tmp/meta-harness-task-{uuid}/
│   │       ├── frontier.py                    # Pareto on (accuracy × tokens)
│   │       ├── persistence.py                 # AsyncPostgresSaver
│   │       ├── runs.py                        # filesystem lifecycle
│   │       ├── memory.py                      # cross-run patterns      (step 8)
│   │       └── branches.py                    # time-travel forks       (step 9)
│   └── tests/                                 # 47 tests passing
├── frontend/                                  # Next.js 15 dashboard    (step 11)
├── sdk/meta_harness/                          # public Python library
├── skills/meta-harness-coding-agent/SKILL.md  # the proposer's workflow
├── eval/
│   ├── tasks/                                 # 5 frozen calibration tasks
│   ├── holdout/                               # 2 unseen test tasks     (step 12)
│   └── score.py                               # multi-task pytest scorer
├── agents/
│   ├── baseline.py                            # immutable starting harness
│   └── (...)                                  # proposer-generated candidates (gitignored)
├── infra/docker-compose.yml                   # postgres:16 service
└── docs/                                      # phase-0 contracts (read these first)
```

---

## Documentation

The reference docs are layered so a new contributor can read in order
and end up oriented:

| Doc | When to read |
|---|---|
| [`ARCHITECTURE_SECTION_1.md`](ARCHITECTURE_SECTION_1.md) | First — the locked architecture |
| [`docs/PROJECT_LAYOUT.md`](docs/PROJECT_LAYOUT.md) | First — repo tree + naming rules |
| [`docs/INTERFACES.md`](docs/INTERFACES.md) | **Always** — every cross-component contract |
| [`docs/BUILD_ORDER.md`](docs/BUILD_ORDER.md) | When picking a step — DoD per step |
| [`docs/DEFINITION_OF_DONE.md`](docs/DEFINITION_OF_DONE.md) | Before demo — the formal acceptance test |
| [`docs/TEAM_HANDOFF.md`](docs/TEAM_HANDOFF.md) | When joining the build — 4-person coordination |
| [`relay_metaharness_v7.md`](relay_metaharness_v7.md) | For the *why* — canonical design doc |
| [`relay_v7_appendix_a_worktrees.md`](relay_v7_appendix_a_worktrees.md) | For step 9 — concurrent branches via asyncio |
| [`relay_v7_appendix_b_metaharness_internals.md`](relay_v7_appendix_b_metaharness_internals.md) | For step 6+ — Stanford repo deep-dive |
| [`relay_v7_appendix_c_inner_loop.md`](relay_v7_appendix_c_inner_loop.md) | For inner-loop work — 5-phase agent design |
| [`skills/meta-harness-coding-agent/SKILL.md`](skills/meta-harness-coding-agent/SKILL.md) | When debugging the proposer — what it actually reads |

The single most important rule: **`docs/INTERFACES.md` is the contract.**
Every change touching a state schema, JSON shape, REST endpoint, SSE
event, tool I/O, override point, or SKILL.md section updates that doc
in the same commit.

---

## Tech stack

| Component | Choice |
|---|---|
| State machines | LangGraph 0.2+ |
| Checkpointer | `AsyncPostgresSaver` (langgraph-checkpoint-postgres) |
| Database | Postgres 16 (Docker; `infra/docker-compose.yml`) |
| Backend API | FastAPI 0.115+ + Uvicorn |
| Inner-loop LLM | Claude Haiku 4.5 (default; rate-limit-friendly + ~10× cheaper than Sonnet) |
| Proposer LLM | Claude Code CLI subprocess (subscription auth) |
| CLI | Typer + python-dotenv |
| Frontend | Next.js 15, Tailwind 4, ReactFlow, D3, Monaco |
| Workspace tooling | uv (workspace mode: `sdk/` + `backend/`) |
| Testing | pytest, pytest-asyncio (`asyncio_mode = "auto"`), 47 passing |

`META_HARNESS_INNER_MODEL` env var overrides the inner-loop model if a
higher API tier is available (e.g. `claude-sonnet-4-6`).

---

## Acknowledgments

Built on, and grateful for, the work of:

- Yoonho Lee, Roshen Nair, Qizheng Zhang, Kangwook Lee, Omar Khattab,
  and Chelsea Finn — *Meta-Harness: End-to-End Optimization of Model
  Harnesses*, [arXiv:2603.28052](https://arxiv.org/abs/2603.28052),
  [project page](https://yoonholee.com/meta-harness/), and the
  reference framework at
  [stanford-iris-lab/meta-harness](https://github.com/stanford-iris-lab/meta-harness).
- The LangChain team for LangGraph's time-travel primitives, which
  make the linear-to-tree mapping possible without a bespoke
  orchestration layer.
- Anthropic for the Claude Code CLI's `--append-system-prompt` and
  stream-json output format, which let us reproduce the paper's
  filesystem-mediated proposer pattern verbatim.

---

## License

MIT — see [LICENSE](LICENSE).

---

> *Time-travel for Meta-Harness. Built on LangGraph state machines.
> Secure, consistent, reversible — by construction. Open source. One spark.*
