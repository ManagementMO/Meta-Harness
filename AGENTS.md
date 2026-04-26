# Repository Guidelines

## Project Structure & Module Organization
This repository is a `uv` workspace with two Python packages: `sdk/` and `backend/`. The installable SDK lives in `sdk/meta_harness/`; backend orchestration code lives in `backend/app/meta_harness/`. Keep those namespaces distinct: `meta_harness` is the public library, while `app.meta_harness` is backend-internal. CLI entrypoints live in `backend/app/cli.py`. Tests live under `backend/tests/`. Frozen evaluation tasks live in `eval/tasks/<task-id>/` with a `task.json` and `workspace/`. `agents/` contains the committed baseline harness; generated candidates and `runs/` outputs are artifacts and should not be checked in.

## Build, Test, and Development Commands
Use `uv` for all Python workflows.

- `uv sync`: install the workspace packages and dependencies.
- `docker compose -f infra/docker-compose.yml up -d postgres`: start the local Postgres instance used by persistence features.
- `uv run python -m eval.score --task task-001-fix-typo`: run the baseline eval scorer on one task.
- `cd backend && uv run pytest tests -q`: run the backend test suite.
- `uv run meta-harness benchmark --candidate baseline --trials 5`: benchmark a candidate across the eval set.
- `uv run meta-harness loop --proposer mock --mock-bench --budget 2 --fresh`: exercise the outer loop without live LLM calls.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, type hints, `Path`-based filesystem code, and concise module docstrings. Use `snake_case` for modules, functions, and package directories; use `PascalCase` for classes such as `BaselineHarness`. Keep CLI and backend imports explicit. No formatter or linter config is checked in today, so match the surrounding file style closely and avoid introducing new tooling conventions inside a single change.

## Testing Guidelines
Write tests in `backend/tests/` using `test_<feature>.py` and `test_<behavior>()` naming. Prefer deterministic unit tests first; reserve live end-to-end tests for flows that require `ANTHROPIC_API_KEY`. When changing eval, sandbox, or outer-loop behavior, add or update pytest coverage and run the narrowest relevant command before the full suite.

## Commit & Pull Request Guidelines
Recent history follows step-oriented subjects like `step 6: real proposer ...`; use that format for milestone work and `fixup:` only for small follow-ups. PRs should state the affected area, reference the relevant build step or interface contract when applicable, and list the exact verification commands you ran. Include artifact paths or screenshots only when the change produces user-visible output.
