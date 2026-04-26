#!/usr/bin/env bash
# Demo dry-run (BUILD_ORDER step 13).
#
# This script exercises the demo-day acceptance contract from
# docs/DEFINITION_OF_DONE.md as a single command. It does NOT replace
# the live demo — it verifies that every layer (Postgres, backend
# tests, mock outer loop, claude proposer) is healthy enough to run
# the demo end-to-end.
#
# Usage: bash scripts/demo_dryrun.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass=0
fail=0

check() {
  local label="$1"
  shift
  echo -n "  $label... "
  if "$@" >/tmp/demo_dryrun.log 2>&1; then
    echo -e "${GREEN}OK${NC}"
    pass=$((pass + 1))
  else
    echo -e "${RED}FAIL${NC}"
    echo "    log: /tmp/demo_dryrun.log"
    sed -n '1,15p' /tmp/demo_dryrun.log | sed 's/^/      /'
    fail=$((fail + 1))
  fi
}

echo "─── 1. Prerequisites ───────────────────────────────────────"
check "Docker installed" command -v docker
check "uv installed" command -v uv
check "claude CLI installed" command -v claude
check "Postgres healthy" sh -c 'docker compose -f infra/docker-compose.yml ps | grep -q "Up.*healthy"'

echo "─── 2. Backend test suite ─────────────────────────────────"
check "78+ tests green (pytest)" sh -c 'cd backend && uv run pytest tests/ -q --no-header'

echo "─── 3. Mock outer loop end-to-end ─────────────────────────"
RUN_NAME="demo-dryrun-$(date +%s)"
check "mock loop produces all artifacts" sh -c "
  uv run meta-harness loop \
    --proposer mock --mock-bench --budget 2 --fresh \
    --run-name $RUN_NAME --no-persistent
  test -f runs/$RUN_NAME/pending_eval.json
  test -f runs/$RUN_NAME/frontier_val.json
  test -f runs/$RUN_NAME/evolution_summary.jsonl
  test -f runs/$RUN_NAME/manifest.json
"

echo "─── 4. Frontier shape (dominated_by_names) ────────────────"
check "frontier has dominated_by_names per candidate" sh -c "
  uv run python -c \"
import json, sys
fr = json.load(open('runs/$RUN_NAME/frontier_val.json'))
assert 'candidates' in fr
for c in fr['candidates']:
    assert 'dominated_by_names' in c, f'missing dominated_by_names on {c}'
sys.exit(0)
\"
"

check "evolution_summary rows have parent_candidate_name" sh -c "
  uv run python -c \"
import json, sys
rows = [json.loads(l) for l in open('runs/$RUN_NAME/evolution_summary.jsonl').read().splitlines() if l.strip()]
assert all('parent_candidate_name' in r for r in rows), 'missing parent_candidate_name'
sys.exit(0)
\"
"

echo "─── 5. Frontend builds ────────────────────────────────────"
check "frontend npm install + build" sh -c '
  cd frontend/dashboard
  npm install --silent --no-audit --no-fund
  npm run build
'

echo "─── 6. Holdout tasks present and broken-pristine ──────────"
check "holdout/task-006-fix-recursion fails pristine" sh -c '
  uv run python -m eval.score --task task-006-fix-recursion --holdout > /tmp/h6.json
  uv run python -c "import json; d=json.load(open(\"/tmp/h6.json\")); assert d[\"passed\"] is False"
'
check "holdout/task-007-implement-stack fails pristine" sh -c '
  uv run python -m eval.score --task task-007-implement-stack --holdout > /tmp/h7.json
  uv run python -c "import json; d=json.load(open(\"/tmp/h7.json\")); assert d[\"passed\"] is False"
'

echo "─── 7. CLI completeness ───────────────────────────────────"
check "meta-harness --help lists all 8 subcommands" sh -c "
  uv run meta-harness --help 2>&1 | grep -E 'version|inner|benchmark|loop|fork|init|resume|memory' | wc -l | grep -qE '\b8\b|^\s*8\s*$'
"

echo
echo "─── Summary ────────────────────────────────────────────────"
echo -e "  ${GREEN}pass: $pass${NC}    ${RED}fail: $fail${NC}"
if [[ $fail -gt 0 ]]; then
  echo -e "  ${RED}DRY-RUN FAILED${NC} — fix the failing checks before the live demo."
  exit 1
fi
echo -e "  ${GREEN}DRY-RUN GREEN${NC} — system is demo-ready."

# Cleanup the temp run dir
rm -rf "runs/$RUN_NAME" 2>/dev/null || true
