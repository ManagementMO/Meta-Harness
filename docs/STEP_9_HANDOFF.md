# Step 9 Handoff: Time-Travel Branches

This note captures what was implemented for Step 9 and what future developers should know before building on it. It is intentionally scoped to backend branch orchestration. It does not change the public interface contract in `docs/INTERFACES.md`.

## What changed

Step 9 added backend support for time-travel forks and concurrent branch execution.

Primary implementation:

- `backend/app/meta_harness/branches.py`

Supporting changes:

- `backend/tests/test_branches.py`
- `backend/app/meta_harness/persistence.py`

No frontend work, API routes, SSE routes, memory layer, or eval task changes were added as part of this step.

## Branch module

`backend/app/meta_harness/branches.py` exposes backend Python functions that Step 10 can call later.

Important public functions:

- `get_state_history(graph, thread_id, limit=None)`
- `get_checkpoint_state(graph, thread_id, checkpoint_id)`
- `worktree_add(graph, run_id, parent_thread_id, parent_checkpoint_id, mods=None, name=None, recursion_limit=200)`
- `cancel_branch(thread_id)`
- `list_branches(run_id=None)`
- `get_branch(thread_id)`
- `reconstruct_trajectory(run_id)`
- `cancel_all_branches()`
- `clear_branch_state()`

The in-process branch registry is:

```python
branch_registry: dict[str, asyncio.Task]
```

It is keyed by branch `thread_id`, not `branch_id`.

## Branch metadata

Branch metadata is represented by `BranchMetadata` and includes:

- `branch_id`
- `run_id`
- `thread_id`
- `parent_thread_id`
- `parent_checkpoint_id`
- `status`
- `created_at`
- `started_at`
- `finished_at`
- `cancelled_at`
- `error`
- `mods`
- optional `name`
- optional `result`

Supported statuses are:

- `created`
- `running`
- `completed`
- `failed`
- `cancelled`

Metadata is currently in-process only. If the backend process restarts, active `asyncio.Task` objects and branch metadata are not restored. LangGraph checkpoints remain durable through the configured saver, but live task registry state does not.

## Time-travel behavior

`worktree_add` creates a new LangGraph thread for each fork.

The fork flow is:

1. Load the parent checkpoint from LangGraph state history.
2. Copy the parent checkpoint values.
3. Apply user-supplied `mods` to the copied values.
4. Create a new branch thread id.
5. Seed the new thread with `graph.aupdate_state(...)`.
6. Resume the new branch with `graph.ainvoke(None, fork_config)`.
7. Track execution through `asyncio.create_task`.

Branch execution intentionally uses `asyncio.create_task`, not `asyncio.gather`, so each branch can be tracked and cancelled independently.

## Checkpoint history

Checkpoint history is exposed through LangGraph's async state history API.

`get_state_history` returns projected `CheckpointRecord` values for dashboard/API use. It includes checkpoint id, thread id, timestamp, current node, iteration if present, a small values summary, parent checkpoint id when available, next nodes, and raw metadata.

This is a projection layer only. It does not change LangGraph checkpoint persistence.

## Cancellation

`cancel_branch(thread_id)` cancels the running task from `branch_registry` and marks the matching `BranchMetadata` as `cancelled`.

Cancellation status is currently stored in branch metadata only. It is not written back into `MetaHarnessState`. Persisting cancellation inside graph state would be a public contract/schema change and should be done with an explicit `INTERFACES.md` update.

## Trajectory reconstruction

`reconstruct_trajectory(run_id)` returns a branch tree shape suitable for future dashboard/API use.

It is built from the in-process `branch_metadata` map and links child branches through:

- `parent_thread_id`
- `parent_checkpoint_id`
- branch `thread_id`

Because metadata is in-process, the trajectory tree currently represents branches created during the current backend process lifetime.

## Persistence note

`backend/app/meta_harness/persistence.py` was adjusted so async Postgres usage works more reliably on Windows and so the healthcheck opens a real async connection.

This was needed for Step 9 verification around shared `AsyncPostgresSaver` behavior. It does not introduce a new persistence abstraction.

## Tests added

`backend/tests/test_branches.py` covers:

- checkpoint history projection
- fork creation from an earlier checkpoint
- applying state modifications before resume
- concurrent branch execution
- cancellation
- optional shared `AsyncPostgresSaver` branch execution when local Postgres is reachable

The optional Postgres test skips when Postgres is not running.

The current local virtual environment does not appear to have `pytest-asyncio`, so the tests use a small synchronous wrapper around `asyncio.run`.

Verification run:

```powershell
cd backend
..\.venv\Scripts\python -m py_compile app\meta_harness\branches.py app\meta_harness\persistence.py
..\.venv\Scripts\python -m pytest tests\test_branches.py -q -p no:cacheprovider
```

Result for the branch test file was `4 passed, 1 skipped` when Postgres was unavailable.

## What was intentionally not done

Step 9 did not implement:

- Step 8 memory
- Step 10 API endpoints
- SSE events
- frontend branch UI
- durable branch metadata storage
- eval task changes
- changes to `docs/INTERFACES.md`

Do not mix these into branch orchestration unless the relevant future step explicitly requires it.

## Future work

Step 10 should call `backend/app/meta_harness/branches.py` instead of reimplementing branch logic.

Likely API/SSE integration points:

- list checkpoints for a run/thread using `get_state_history`
- fork a branch using `worktree_add`
- list branches using `list_branches`
- cancel a branch using `cancel_branch`
- render branch trees using `reconstruct_trajectory`
- emit future SSE events such as fork created, branch completed, branch failed, and branch cancelled

Future durable branch tracking may be needed if branch metadata must survive process restarts. If that is added, keep the current Python functions as the backend boundary and add storage behind them.

If future developers need cancellation status or branch lineage inside `MetaHarnessState`, treat that as a public contract change. Update `docs/INTERFACES.md` in the same change and explain why.

## Local cleanup note

During verification, a wider pytest run hit Windows permission errors while creating or removing pytest temp/cache directories. Some generated temp artifacts may exist under:

- `backend/pytest-cache-files-*`
- `C:\Users\danda\.codex\memories\pytest-tmp`

Those artifacts are not part of Step 9 and should not be checked in.
