# IMPLEMENTATION_CLARITY.md

Purpose: provide one fast, accurate map of what is implemented now, where
contracts live, and what behavior is intentionally placeholder.

## Canonical contract order

When there is disagreement, use this precedence:

1. `docs/INTERFACES.md` (cross-component contracts)
2. `ARCHITECTURE_SECTION_1.md` (locked architecture decisions)
3. `docs/PROJECT_LAYOUT.md` (placement and naming constraints)
4. `docs/DEFINITION_OF_DONE.md` (acceptance criteria)
5. `docs/BUILD_ORDER.md` (step DoD sequencing)
6. live code in `backend/app/**` and `frontend/dashboard/src/**`

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

- Diff and test-output fetch helpers in frontend return `null` when no backend
  endpoint is available.
- Some UI panels can show empty-state placeholders during real-run warmup.
- Real token/cost aggregation for benchmark summaries remains limited in parts
  of the backend path (see corresponding notes in project docs).

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
