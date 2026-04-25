# Meta-Harness

LangGraph-native substrate for self-improving agent harnesses. Applies
the Stanford reference framework's Meta-Harness paradigm
([arXiv:2603.28052](https://arxiv.org/abs/2603.28052)) to a coding-agent
domain, expressed as two LangGraph state machines with a Postgres-backed
checkpointer, time-travel forking, and cross-run memory.

## Status

Pre-implementation. The architecture, layout, contracts, build order,
and acceptance test live in:

- `ARCHITECTURE_SECTION_1.md` — locked architecture
- `docs/PROJECT_LAYOUT.md` — monorepo layout
- `docs/INTERFACES.md` — every cross-component contract
- `docs/BUILD_ORDER.md` — topological build steps with DoD commands
- `docs/DEFINITION_OF_DONE.md` — demo arc as the formal acceptance test
- `relay_metaharness_v7.md` and three appendices — design rationale

## Prerequisites

- Python ≥ 3.11
- [uv](https://github.com/astral-sh/uv) (workspace tooling)
- Docker (Postgres via `infra/docker-compose.yml`)
- Node.js ≥ 20 + npm (frontend, lands at BUILD_ORDER step 11)
- The `claude` CLI on `PATH` (proposer; lands at step 6)
- An Anthropic API key (`ANTHROPIC_API_KEY`); subscription auth via `claude` is also supported

## Quickstart (current step: BUILD_ORDER (1))

```bash
cp .env.example .env  # fill in ANTHROPIC_API_KEY when needed
docker compose -f infra/docker-compose.yml up -d postgres
uv sync
uv run python -m eval.score --task task-001-fix-typo
# Expected: JSON with passed=false (the buggy calculator hasn't been fixed)
```

## License

MIT — see LICENSE.
