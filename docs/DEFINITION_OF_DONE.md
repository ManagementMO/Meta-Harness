# DEFINITION_OF_DONE.md — the demo arc as the formal acceptance test

*A run that satisfies every binary check below is what "done" means.
This is the authoritative acceptance contract; if the implementation
disagrees, the implementation is wrong.*

---

## The literal demo command

```bash
# One-time setup
docker compose -f infra/docker-compose.yml up -d postgres
uv sync
(cd frontend && npm install && npm run build)

# Three terminals at demo time
# Terminal 1 — backend
cd backend && uv run uvicorn app.main:app --port 8000 --reload

# Terminal 2 — frontend
cd frontend && npm run dev

# Terminal 3 — kick off the run
uv run meta-harness loop \
  --domain coding-agent \
  --proposer claude \
  --budget 5 \
  --fresh \
  --holdout \
  --run-name demo

# Browser: http://localhost:3000/runs/demo
```

ANTHROPIC_API_KEY is loaded from `.env`. Claude Code (`claude` CLI)
must be on `PATH` per Phase-1.1 resolution.

---

## Expected output structure

### Linear branch (~6 minutes, baseline ≈ 0.62)

| Iter | Hypothesis | Score | Δ | Outcome |
|---|---|---|---|---|
| 1 | retry on schema_drift errors | 0.70 | +0.08 | keep ✓ |
| 2 | stricter tool-description hashing | 0.66 | −0.04 | reject ✗ |
| 3 | early-exit on auth failures | 0.74 | +0.04 | keep ✓ |
| 4 | more specific tool descriptions | 0.80 | +0.06 | keep, new best ✓ |

Linear best: **0.80** at iter 4, ≈24,800 avg context tokens.

### Forked branch (live during demo Act 3)

Right-click iter-2 checkpoint → **Fork from here** → edit
`proposer_prior` → click **Resume**. Branch grows concurrently with
linear branch (Appendix A `asyncio.create_task`).

| Iter | Hypothesis | Score | Δ | Outcome |
|---|---|---|---|---|
| 2′ | rewrite tool descriptions w/ examples | 0.78 | +0.16 from iter 1 | keep ✓ |
| 3′ | add few-shot demos to descriptions | 0.85 | +0.07 | keep, new global best ✓ |

Fork best: **0.85** at iter 3′, ≈26,200 avg context tokens.

### Pareto frontier at end of run

Both `more-specific-descriptions` (0.80, 24800) and
`few-shot-demos-on-descriptions` (0.85, 26200) Pareto-optimal —
different (accuracy, tokens) tradeoffs. `dominated_by_names == []`
on both; rejected `tighter-tool-hashing` has both as dominators.

### Holdout (run automatically after the search loop)

Iter-4 (linear best) and iter-3′ (fork best) re-evaluated against
2 unseen tasks in `eval/holdout/`. Holdout score reported separately
from search-set score; the gap tells us whether the proposer
overfit. Reported on the Devpost writeup.

### Cost & runtime

- Total wall time: **< 8 minutes** (target 6).
- Total cost: **≈ $3.30** (Appendix C §C.12), hard cap **< $5**.

---

## The three things a judge sees on screen

1. **Outer state graph (ReactFlow).** Top-left panel. Nodes
   `propose → validate → benchmark → update_frontier` light up in
   sequence per outer-loop iteration. The proposer node displays the
   live `claude` subprocess transcript while it runs.

2. **Candidate trajectory tree (D3).** Top-right panel. One node per
   candidate. Edges follow `parent_candidate_name`. **On fork, the
   tree visibly branches**, with both branches growing in real time
   (Appendix A — concurrent `asyncio.Task`s, not sequential rewind).

3. **Code diff viewer (Monaco unified-diff).** Right side. Shows the
   live `agents/<n>.py` diff vs parent for the currently-selected
   candidate. Selecting a different node in the tree swaps the diff
   instantly.

Plus three supporting views: a score chart with Pareto frontier
(lower-left), a memory panel sidebar showing cross-run patterns
(persisted via `PostgresStore`), and a fork modal triggered by
right-click → "Fork from here" on any checkpoint.

---

## The 90-second demo script (validation walkthrough)

```
[0:00–0:08] HOOK
"Stanford published Meta-Harness four weeks ago — Lee, Khattab, Finn.
Their proposer agent reads execution traces and rewrites the harness,
beating ACE by 7.7 points. But their loop is linear. We mapped it
onto LangGraph and made it a tree."

[0:08–0:23] ACT 1 — Local launch (no install needed beyond `claude` CLI)
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
"Two branches. Original 0.80. Fork 0.85. The meta-harness loop is
no longer a sequence — it's a search tree."
[Click memory panel.]
"And LangGraph's cross-thread memory means the next run starts smarter."

[1:20–1:30] CLOSE
"Time-travel for Meta-Harness. Built on LangGraph state machines.
Secure, consistent, reversible — by construction. Open source.
That's Meta-Harness. One spark."
```

---

## Acceptance criteria (binary checklist)

The run is "done" iff every box ticks:

- [ ] Every BUILD_ORDER.md DoD command (steps 1–13) exits 0.
- [ ] Linear score arc lands within ±5% of expected at every iteration:
      0.62 → 0.70 → 0.66 (rejected) → 0.74 → 0.80.
- [ ] Forked branch reaches **≥ 0.83** by iter 3′ (target 0.85).
- [ ] All **11** SSE event types from `INTERFACES.md` §7.2 fire at
      least once during the run.
- [ ] The candidate trajectory tree visibly branches when the fork is
      created; both branches grow concurrently (not serially).
- [ ] The Monaco diff viewer renders `agents/<n>.py` diffs vs parent
      live during runs; switching tree nodes updates the diff.
- [ ] The memory panel shows ≥ 1 entry from a prior run before
      iteration 1's proposer fires.
- [ ] `pending_eval.json`, `frontier_val.json` (with
      `dominated_by_names`), and `evolution_summary.jsonl` (with
      `parent_candidate_name`) are well-formed at end of run.
- [ ] `proposer-sessions/iter-N/` exists for every N ∈ {1..budget}
      with `session.json` schema-compatible with Stanford's reference.
- [ ] Total wall time < 8 minutes; total cost < $5 USD.
- [ ] Holdout result file `runs/demo/holdout-result.json` exists and
      reports a distinct (search vs holdout) score pair.
- [ ] Process restart resilience: kill mid-iteration, then
      `meta-harness resume demo` completes the run without duplicating
      iterations.
- [ ] Two concurrent branches share `AsyncPostgresSaver` without
      deadlock (verified by step (9) test still green at demo time).
- [ ] `POST /runs` returns **201 Created** with `Location` header
      (verified by step (10)'s `scripts/smoke_api.py`).
- [ ] SSE channel registry rejects unregistered event types with a
      500-class error (verified by step (10) test).

If any box is unticked, the run is not "done" — fix it and re-run the
acceptance test before claiming completion.
