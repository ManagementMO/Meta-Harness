# IMPLEMENTATION_CLARITY.md

Purpose: provide one fast, accurate map of what is implemented now, where
contracts live, and what behavior is intentionally placeholder.

## Canonical contract order

When there is disagreement, use this precedence:

1. Current source behavior and current tests.
2. Immutable run manifests, candidate manifests, evaluation results, and evidence events.
3. Current repository configuration and command output.
4. `docs/META_HARNESS_DEEP_RESEARCH_BRIEF.md` for research invariants and roadmap.
5. `docs/INTERFACES.md` and `ARCHITECTURE_SECTION_1.md` where they match current source.
6. Historical build-order, demo, status, and handoff documents.

`docs/PROJECT_KNOWLEDGE_BASE.md` is comprehensive context and rationale; if it
disagrees with (1)-(5) or current code, treat it as needing an update.

## Current architecture (implemented)

- Backend: FastAPI + LangGraph state machines with `AsyncPostgresSaver`.
- Outer loop: `propose -> validate -> benchmark -> update_frontier`.
- Inner loop: `orient -> plan -> act -> verify -> submit`.
- SSE: 11-event closed set with required `thread_id` on every payload.
- Frontend: Next.js dashboard consuming run detail + SSE stream + fork API.

## Time-travel fork behavior (implemented now)

The dashboard now forks using LangGraph time-travel semantics, not a local
annotation:

- Fork requests include:
  - `parent_checkpoint_id`
  - `parent_thread_id` (when available from selected node)
  - optional `mods` and `name`
- Checkpoint resolution for selected nodes prefers:
  1. exact `thread_id + iteration`
  2. latest checkpoint in that `thread_id`
  3. fallback by summary candidate
  4. fallback by summary iteration
- If a checkpoint cannot be resolved, UI logs a clear "not persisted yet"
  message and does not send a fake fork request.
- After fork creation, branch events are tracked by thread lineage and new
  branch nodes auto-select when streamed.

Key files:

- `frontend/dashboard/src/components/TrajectoryTree.tsx`
- `frontend/dashboard/src/components/ForkModal.tsx`
- `frontend/dashboard/src/lib/api.ts`
- `frontend/dashboard/src/lib/sse.ts`
- `backend/app/api/forks.py`
- `backend/app/meta_harness/branches.py`

## Intentional placeholders still present

- Some UI panels can show empty-state placeholders during real-run warmup.
- Provider token usage is measured when exposed; cost remains explicitly
  `unknown` until a versioned pricing or billed-cost source is configured.
- Lint remains explicitly `unknown`; file-scope changes are measured.
- Recursive/RLM execution is an interface boundary only; no recursive backend
  is registered.
- Active worker tasks remain process-owned even though evidence and branch
  lifecycle projections are durable.

## Quick verification checklist

- Fork a node in `/runs/{run_id}` and confirm a `POST /runs/{run_id}/fork` call
  is made with real checkpoint/thread context.
- Confirm fork-created events include `thread_id` and are visible in decision
  log/tree updates.
- Confirm run page remains connected to SSE and receives non-fork event types.

## Maintenance rule

When changing any of these surfaces in one PR, update all three together:

- `docs/INTERFACES.md` (if contract changed)
- relevant frontend/backend implementation files
- this clarity file if operator behavior changed
