# INTERFACES.md — Meta-Harness cross-component contracts

*Every contract that crosses a process, file, or HTTP boundary, in one
document. Pulled verbatim from Appendices B and C wherever the appendices
specify a shape; **derivations** are flagged inline. The scope is contracts,
not implementation.*

Phase 1.2 (FE/BE protocol) is resolved: **SSE for events + REST for
commands.** Phase 1.3 (skill loading mechanism) is still open and is
called out where it intersects this document.

---

## 1. State schemas (LangGraph TypedDicts)

### 1.1 `MetaHarnessState` — outer state machine

*Verbatim from Appendix B §B.6.1.*

```python
from typing import TypedDict
from app.meta_harness.state import Candidate  # see §1.3 below

class MetaHarnessState(TypedDict):
    run_id: str                      # the tree identifier (= parent thread_id)
    iteration: int                   # 1-indexed; current outer-loop iteration
    budget_remaining: int            # iterations left before END
    candidates: list[Candidate]      # all candidates ever, append-only
    frontier: list[str]              # candidate names on the Pareto frontier
    best_candidate: str | None       # name of the highest-scoring accepted candidate
    proposer_prior: str              # editable via update_state at fork-time
```

### 1.2 `CodingAgentState` — inner state machine

*Verbatim from Appendix C §C.8.*

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class CodingAgentState(TypedDict):
    task: dict                                  # see §2.6 task.json schema
    workspace_path: str                         # /tmp/meta-harness-task-{uuid}/
    orient_summary: dict | None                 # see §2.7 orient.json
    plan: dict | None                           # see §2.8 plan.json
    messages: Annotated[list, add_messages]     # LangGraph reducer-merged
    turn_count: int                             # incremented per act-loop iteration
    verify_attempts: int                        # bounded by harness.MAX_VERIFY_RETRIES
    verify_result: dict | None                  # see §2.10 verify.json
    final_files: dict[str, str] | None          # see §2.11 final-files.json
    score: float | None                         # 0.0 or 1.0 (per-trial pytest pass)
```

### 1.3 `Candidate` — element of `MetaHarnessState.candidates`

*Locked. Synthesized from the union of fields used in pending_eval.json
(proposer-written), the validate/benchmark/update_frontier nodes
(graph-enriched), and the trace structure (Appendix C §C.10).*

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

@dataclass
class Candidate:
    name: str                       # e.g. "few_shot_tool_results"
    import_path: str                # e.g. "agents.few_shot_tool_results:CodingAgentHarness"
    parent: str | None              # parent candidate name; None for baseline
    hypothesis: str                 # falsifiable claim from the proposer
    axis: Literal["exploration", "exploitation"]
    expected_score_delta: float | None
    iteration: int                  # outer-loop iteration that produced it
    traces_dir: Path                # runs/{run_id}/candidates/{name}/traces/ — created at propose-time, populated at benchmark-time, never None
    status: Literal["pending", "smoke_failed", "evaluated", "rejected", "accepted"]
    scores: dict | None             # eval-result.json content; None until benchmark
    delta: float | None             # score - parent.score; None until update_frontier
    cost_usd: float | None
```

---

## 2. Filesystem JSON / JSONL contracts

All files live under `runs/{run_id}/`. The directory layout follows
Appendix C §C.10 (per-candidate trace structure) plus Stanford's
filesystem-first convention (Appendix B §B.2).

### 2.1 `pending_eval.json` — proposer→outer-graph handoff

*Verbatim from Appendix B §B.5.1.*

```json
{
  "iteration": 3,
  "candidates": [
    {
      "name": "few-shot-tool-results",
      "import_path": "agents.few_shot_tool_results:CodingAgentHarness",
      "parent": "more-specific-descriptions",
      "hypothesis": "Inlining 1 example tool result reduces patch-context misses",
      "axis": "exploitation",
      "expected_score_delta": 0.04
    }
  ]
}
```

The proposer writes ONE candidate per iteration (TB2 convention; we are
single-domain coding-agent). Class name is always `CodingAgentHarness`.

### 2.2 `frontier_val.json` — current Pareto frontier

*Locked. Pareto on (accuracy × tokens) per Appendix C §C.11. Each
candidate carries `dominated_by_names`: empty list for Pareto-optimal,
otherwise the names of candidates that dominate it. The dashboard's
frontier rendering filters on `dominated_by_names == []`.*

```json
{
  "iteration": 4,
  "candidates": [
    {"name": "more-specific-descriptions", "accuracy": 0.80, "avg_tokens": 24800, "dominated_by_names": []},
    {"name": "early-exit-on-auth",         "accuracy": 0.74, "avg_tokens": 18200, "dominated_by_names": []},
    {"name": "tighter-tool-hashing",       "accuracy": 0.66, "avg_tokens": 21000, "dominated_by_names": ["more-specific-descriptions", "early-exit-on-auth"]}
  ],
  "_pareto_names": ["more-specific-descriptions", "early-exit-on-auth"],
  "_best": {"name": "more-specific-descriptions", "accuracy": 0.80, "avg_tokens": 24800},
  "per_task": {
    "task-001-fix-typo":     {"best_candidate": "more-specific-descriptions", "pass_rate": 0.95},
    "task-002-add-function": {"best_candidate": "more-specific-descriptions", "pass_rate": 0.85}
  }
}
```

`_pareto_names` is a convenience derived from `dominated_by_names == []`;
both forms are present so the dashboard can choose by render path.

### 2.3 `evolution_summary.jsonl` — append-only candidate log

*Locked. One JSON per line, one line per evaluated candidate.
`parent_candidate_name` lets the dashboard reconstruct the trajectory
tree without scanning every status.json.*

```jsonl
{"iteration": 1, "candidate": "retry-on-test-fail", "import_path": "agents.retry_on_test_fail:CodingAgentHarness", "parent_candidate_name": null, "axis": "exploration", "hypothesis": "...", "scores": {"accuracy": 0.70, "per_task": {...}}, "delta": 0.08, "outcome": "70.0% (+8.0%)", "tokens": 23400, "cost_usd": 0.42, "timing_s": {"propose": 38.2, "bench": 184.6, "wall": 226.0}}
{"iteration": 4, "candidate": "more-specific-descriptions", "import_path": "agents.more_specific_descriptions:CodingAgentHarness", "parent_candidate_name": "early-exit-on-auth", "axis": "exploitation", "hypothesis": "...", "scores": {"accuracy": 0.80, "per_task": {...}}, "delta": 0.06, "outcome": "80.0% (+6.0%)", "tokens": 24800, "cost_usd": 0.45, "timing_s": {"propose": 41.0, "bench": 191.2, "wall": 235.4}}
```

`parent_candidate_name` is `null` for the baseline; the parent
candidate's name otherwise. This is the same field as
`Candidate.parent` (§1.3) at serialization time, renamed for clarity in
the persisted log.

### 2.4 `proposer-sessions/iter-{N}/session.json`

*DERIVED — schema-compatible with Stanford's `claude_wrapper.py`'s
`SessionResult` dataclass + `log_session()` output.*

```json
{
  "timestamp": "2026-04-25T14:32:11.421Z",
  "prompt": "Run iteration 3 of the evolution loop...",
  "model": "opus",
  "session_id": "<claude-session-id>",
  "exit_code": 0,
  "duration_seconds": 38.21,
  "cost_usd": 0.15,
  "token_usage": {"input_tokens": 187432, "output_tokens": 4128, "cache_read_input_tokens": 89000},
  "command": ["claude", "--dangerously-skip-permissions", "-p", "...", "--model", "opus", "..."],
  "cwd": "runs/run-2026-04-25-1430/",
  "skill": [{"path": "skills/meta-harness-coding-agent/SKILL.md", "name": "meta-harness-coding-agent"}],
  "files_read":   {"agents/baseline.py": {"reads": 1, "lines": 152}, "evolution_summary.jsonl": {"reads": 2, "lines": 12}},
  "files_written": {"agents/few_shot_tool_results.py": {"lines_written": 168}, "pending_eval.json": {"lines_written": 12}},
  "tool_summary": ["Read(agents/baseline.py)", "Read(traces/...)", "Bash(python -c '...')", "Write(agents/few_shot_tool_results.py)", "Write(pending_eval.json)"]
}
```

Companion files in the same directory:

- `transcript.txt` — concatenated text events from the stream-json log.
- `system_prompt.txt` — the exact `--append-system-prompt` payload (SKILL.md + domain_spec.md + proposer_prior.md).
- `events.jsonl` — raw stream-json events, one per line.
- `tools/{NNN}_{ToolName}.txt` — one file per tool call, human-readable.

### 2.5 `runs/{run_id}/candidates/{N}/eval-result.json`

*DERIVED — referenced as "aggregate score across all 25 trials" in
Appendix C §C.10 but not given a verbatim shape.*

```json
{
  "candidate": "few-shot-tool-results",
  "n_tasks": 5,
  "n_trials_per_task": 5,
  "accuracy": 0.78,
  "per_task": {
    "task-001-fix-typo":     {"pass_rate": 0.95, "trials": [true, true, true, true, false]},
    "task-002-add-function": {"pass_rate": 0.80, "trials": [true, true, true, false, true]}
  },
  "tokens": {"input_tokens": 124200, "output_tokens": 19800, "total_tokens": 144000},
  "cost_usd": 0.42,
  "wall_time_s": 184.6,
  "timestamp": "2026-04-25T14:35:49.218Z"
}
```

### 2.6 `eval/tasks/<task-id>/task.json` — task specification

*DERIVED from Appendix C §C.11 task descriptions.*

```json
{
  "id": "task-002-add-function",
  "tier": "implement-spec",
  "instruction": "Add a `median()` function to stats.py. It must handle empty lists, single elements, and even-length lists.",
  "test_command": "pytest tests/test_stats.py -q",
  "expected_files_changed": ["stats.py"],
  "baseline_pass_rate": 0.50,
  "best_known_pass_rate": 0.85
}
```

### 2.7 `runs/{run_id}/candidates/{N}/traces/{task-id}-trial-{T}/orient.json`

*DERIVED from Appendix C §C.3.*

```json
{
  "tree": "<output of `tree --gitignore -L 3` or equivalent>",
  "project": {
    "lang": "python",
    "test_runner": "pytest",
    "entry_points": ["src/calc.py"],
    "test_files": ["tests/test_calc.py"]
  },
  "configs": {"README.md": "...", "pyproject.toml": "...", ".relay/AGENTS.md": null},
  "tests": {"tests/test_calc.py": "<file content>"}
}
```

### 2.8 `traces/{task-id}-trial-{T}/plan.json`

*Verbatim from Appendix C §C.4.*

```json
{
  "summary": "Add median() function to stats.py",
  "steps": [
    {"action": "read",      "target": "stats.py",            "why": "see existing patterns"},
    {"action": "read",      "target": "tests/test_stats.py", "why": "see test contract"},
    {"action": "implement", "target": "stats.py",            "why": "add median fn"},
    {"action": "verify",    "target": "pytest tests/test_stats.py", "why": "confirm green"}
  ],
  "expected_files_changed": ["stats.py"],
  "tests_to_run": ["tests/test_stats.py"],
  "risk_factors": ["edge case: empty list"]
}
```

### 2.9 `traces/{task-id}-trial-{T}/act-messages.jsonl` and `act-tools.jsonl`

`act-messages.jsonl` — full Anthropic message history; one JSON per line:

```jsonl
{"role": "user",      "content": "<task instruction + plan>"}
{"role": "assistant", "content": [{"type": "text", "text": "..."}, {"type": "tool_use", "id": "tu_01", "name": "read_file", "input": {"path": "stats.py"}}]}
{"role": "tool",      "tool_use_id": "tu_01", "content": "1→def mean(...)\n..."}
```

`act-tools.jsonl` — *verbatim from Appendix C §C.10*:

```jsonl
{"turn": 7, "tool": "apply_patch", "input": {"path": "stats.py", "patch": "..."}, "output_summary": "applied 14 lines", "duration_ms": 142, "is_error": false}
```

### 2.10 `traces/{task-id}-trial-{T}/verify.json`

*Verbatim from Appendix C §C.7.*

```json
{
  "tests_pass": false,
  "tests_failed": ["test_median_with_empty_list"],
  "test_output": "<truncated to 2000 chars>",
  "lint_pass": true,
  "lint_errors": [],
  "out_of_plan_changes": []
}
```

### 2.11 `traces/{task-id}-trial-{T}/{score.json, summary.md, final-files.json}`

`score.json` — per-trial outcome:

```json
{"passed": true, "score": 1.0, "why": "all tests green; no out-of-plan changes; lint clean"}
```

`summary.md` — *Appendix C §C.10*: 5-line auto-generated summary
("Agent read calc.py, planned to add median(), implemented correctly, but
missed empty-list edge case → test_median_empty failed.")

`final-files.json` — workspace state at end of trial:

```json
{"stats.py": "<full file content>", "tests/test_stats.py": "<unchanged>"}
```

### 2.12 `runs/{run_id}/candidates/{N}/status.json`

*DERIVED from Appendix C §C.10.*

```json
{
  "candidate": "few-shot-tool-results",
  "accepted": true,
  "parent": "more-specific-descriptions",
  "delta": 0.05,
  "reason": "accepted"
}
```

`reason` ∈ {`accepted`, `smoke_failed`, `regression`, `failed_holdout`}.

---

## 3. Inner-loop tool I/O schemas (the FIXED contract)

These six tools are the contract with the evaluator. The proposer cannot
modify them. Tool schemas for read_file, apply_patch, run_bash,
grep_search, and task_complete are *verbatim from Appendix C §C.6*;
write_file (§3.6) expands the §C.6.2 fallback into the formal tool list.

### 3.1 `read_file`

```json
{
  "name": "read_file",
  "description": "Read a file from the workspace, with optional line range.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path":       {"type": "string"},
      "start_line": {"type": "integer", "default": 1},
      "end_line":   {"type": "integer", "description": "Inclusive; -1 = EOF"}
    },
    "required": ["path"]
  }
}
```
Returns: line-numbered content. Files >2000 lines must specify a range or get an error directing them to use `grep_search`.

### 3.2 `apply_patch`

```json
{
  "name": "apply_patch",
  "description": "Apply a unified-diff patch to a file. Patches are surgical and preserve unchanged lines exactly. Use this to make targeted edits rather than rewriting whole files. The patch must apply cleanly; fuzz matching is disabled.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path":  {"type": "string"},
      "patch": {"type": "string", "description": "Unified diff format (the same format as `git diff`)."}
    },
    "required": ["path", "patch"]
  }
}
```
**Failure response** (structured error):

```json
{
  "status": "error",
  "error_type": "context_mismatch",
  "error_message": "Patch context did not match at lines 42-46. The file currently reads:\n<content>\nEdit the patch to match this and retry.",
  "context_echo": {
    "path": "stats.py",
    "start_line": 42,
    "end_line": 46,
    "content": "<actual current content of those lines>"
  }
}
```

`error_type` ∈ {`context_mismatch`, `file_not_found`, `invalid_patch`}.
On `context_mismatch`, `context_echo` is populated with the current file
content at the failed range so the model can fix the patch without
re-reading the file (per Appendix C §C.6.2's "this tells the model
exactly what to fix" rule). On `file_not_found` or `invalid_patch`,
`context_echo` is `null`.

### 3.3 `run_bash`

```json
{
  "name": "run_bash",
  "description": "Run a bash command in the sandboxed workspace. Returns stdout, stderr, exit_code, and duration_ms. Commands run with a 30s default timeout (max 120s). The workspace is reset between tasks.",
  "input_schema": {
    "type": "object",
    "properties": {
      "command":     {"type": "string"},
      "timeout_sec": {"type": "integer", "default": 30, "maximum": 120}
    },
    "required": ["command"]
  }
}
```
Sandbox: `/tmp/meta-harness-task-{uuid}/`, no network, rlimit 512MB RAM /
60s CPU. Allowed binaries: `python3, pip, pytest, git, bash, ls, cat, grep,
sed, head, tail, find, diff, make`. **No** `curl, wget, ssh`.

### 3.4 `grep_search`

```json
{
  "name": "grep_search",
  "description": "Search files in the workspace using ripgrep. Returns file paths and matching lines with line numbers. Prefer this over reading many files individually.",
  "input_schema": {
    "type": "object",
    "properties": {
      "pattern":       {"type": "string", "description": "Regex pattern."},
      "path":          {"type": "string", "default": "."},
      "file_glob":     {"type": "string", "description": "e.g. '*.py'"},
      "context_lines": {"type": "integer", "default": 2, "maximum": 10}
    },
    "required": ["pattern"]
  }
}
```

### 3.5 `task_complete`

```json
{
  "name": "task_complete",
  "description": "Signal that the task is done. Call this when you believe the task is solved AND tests pass. The harness will run final verification.",
  "input_schema": {"type": "object", "properties": {}}
}
```

### 3.6 `write_file`

```json
{
  "name": "write_file",
  "description": "Create a new file. Errors if the file already exists — use apply_patch to modify existing files. Use this only for files that do not yet exist in the workspace.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path":    {"type": "string"},
      "content": {"type": "string"}
    },
    "required": ["path", "content"]
  }
}
```

**Return shape** (mirrors apply_patch's structured pattern):

```json
{
  "status": "ok",
  "path": "geometry/point.py",
  "bytes_written": 412
}
```

```json
{
  "status": "error",
  "error_type": "file_exists",
  "error_message": "File 'geometry/point.py' already exists. Use apply_patch to modify it."
}
```

`status` ∈ {`ok`, `error`}. On `ok`, `bytes_written` is set. On `error`,
`error_type` ∈ {`file_exists`, `invalid_path`, `write_failed`} and
`error_message` is set.

This expands Appendix C §C.6.2's `write_file` fallback into the formal
tool list; both `INTERFACES.md` and `ARCHITECTURE_SECTION_1.md` are now
the canonical source for the tool count (six). `write_file`, like the
other five tools, is part of the FIXED contract — not overridable by
candidates.

---

## 4. The 11 inner-loop override points (the SEARCH SPACE)

*Verbatim from Appendix C §C.9.* Candidates may override any of these on
their `CodingAgentHarness` subclass. Tools (§3) and phase boundaries are
NOT overridable.

```python
class CodingAgentHarness:
    SYSTEM_PROMPT: str                   # 1. tone, framing, few-shot examples
    PLAN_PROMPT_TEMPLATE: str            # 2. plan structure, signals to highlight
    MAX_ACT_TURNS: int = 25              # 3. tighter (10) or looser (40)
    MAX_VERIFY_RETRIES: int = 3          # 4. retry budget on verify failure

    def _build_initial_context(self, orient_summary: dict) -> dict: ...   # 5
    def _format_tool_result(self, name: str, result: ToolResult) -> str: ... # 6
    def _compose_act_prompt(self, plan: dict) -> str: ...                 # 7
    async def _call_llm(self, messages: list, tools: list) -> Response: ...  # 8
    def should_loop_back_to_act(self, verify_result: dict) -> bool: ...   # 9
    def _summarize_for_overflow(self, messages: list) -> list: ...        # 10
    # 11. (Structural) Reordering phases: skip plan for simple tasks, add
    #     a re-plan phase after first verify failure, etc. Implemented by
    #     overriding the graph-build hook `build_inner_graph(self) -> StateGraph`.
```

`ToolResult` and `Response` are SDK type stubs (`sdk/meta_harness/types.py`).

---

## 5. SKILL.md — frontmatter + body convention

Per Appendix B §B.3.1 and the two Stanford reference SKILL.md files
inspected during research.

### 5.1 Frontmatter (YAML)

```yaml
---
name: meta-harness-coding-agent       # max 64 chars; lowercase / digits / hyphens
description: Evolve the coding agent harness. Use when running meta_harness.py iterations to propose new candidate harnesses based on prior execution traces and scores.
---
```

Constraints (per Claude Code skill spec): `name` ≤64 chars, `description`
≤1024 chars, no XML tags in either, no reserved words.

### 5.2 Body sections (required, in order)

1. **What you are doing** — one paragraph framing the task.
2. **Hard rules (Anti-Overfitting)** — explicit forbidden behaviors
   (no task-specific hints, no hardcoded fixes, generalize-only).
3. **Hard rules (Anti-Parameter-Tuning)** — mechanism-first design,
   self-critique step before write, no combinatorial sweeps.
4. **Workflow** — numbered steps: Analyze → (Pick hypothesis) →
   Prototype → Implement → Register.
5. **Interface contract** — Python class signature the candidate must
   implement; here `CodingAgentHarness`.
6. **The pending_eval.json schema** — exact JSON shape (per §2.1).

Body length: 100–200 lines. Total file: ~5 KB Markdown.

### 5.3 Skill loading mechanism (PHASE 1.3 — RESOLVED)

`meta-harness loop` resolves `skill_path` in this precedence order:

1. **Absolute path** (starts with `/`) — used directly.
2. **Relative path** — resolved against repo root (the directory holding
   the workspace `pyproject.toml`).
3. **Omitted** — defaults to `skills/meta-harness-coding-agent/SKILL.md`
   (relative to repo root).

**Validation at run-start** (before the propose node executes):

- File exists and is readable.
- Parses as YAML frontmatter + Markdown body.
- Frontmatter has required `name` (≤64 chars) and `description`
  (≤1024 chars) fields.
- Body has all 6 required sections (per §5.2).
- On any failure: refuse to start the run with a clear error; do not
  partial-init.

**CLI surface:**

- `meta-harness loop` (no flag) → uses default `skill_path`.
- `meta-harness loop --skill <path>` → explicit override.
- `meta-harness loop --skill-dir <dir>` → resolves to `<dir>/SKILL.md`
  (convenience for users with multiple domain skills).

The HTTP `POST /runs` body's `domain` field continues to map a known
domain name to its default `skill_path` via these same rules; explicit
`skill_path` may also be passed in the request body to override the
domain-default lookup.

---

## 6. REST endpoints (FastAPI / `backend/app/api/`)

All paths relative to `http://localhost:8000`. Bodies are JSON unless
noted. Status codes are conventional (200 OK, 201 Created, 202 Accepted,
404 Not Found, 409 Conflict).

### 6.1 Runs (`api/runs.py`)

| Method | Path | Request | Response | Status |
|---|---|---|---|---|
| `POST` | `/runs` | `{"domain": "coding-agent", "skill_path": "<optional>", "budget": 5, "model": "opus", "fresh": true, "run_name": "demo-2026-04-25", "proposer": "claude", "mock_bench": false, "trials": 5, "workers": 3}` | **201 Created** with header `Location: /runs/{run_id}`. Body: full Run object: `{"run_id", "thread_id", "status", "started_at", "domain", "skill_path", "budget", "model", "current_iteration": 0}` | **201** |
| `GET`  | `/runs` | — | `{"runs": [{"run_id", "thread_id", "status", "started_at", "current_iteration", "best_score"}]}` | 200 |
| `GET`  | `/runs/{run_id}` | — | full `RunInfo` (run dir manifest + frontier_val + last few summary rows) | 200 |
| `DELETE` | `/runs/{run_id}` | — | `{"status": "cancelled"}` (cascades to all branches via `branch_registry`) | 200 |

`proposer`, `mock_bench`, `trials`, and `workers` are backend run-control
fields used by the CLI-equivalent API path and smoke tests. Omitted
values preserve the real proposer path: `proposer="claude"`,
`mock_bench=false`, `trials=5`, `workers=3`.

### 6.2 Checkpoints (`api/checkpoints.py`)

| Method | Path | Request | Response | Status |
|---|---|---|---|---|
| `GET` | `/runs/{run_id}/checkpoints` | — | `{"checkpoints": [{"checkpoint_id", "thread_id", "ts", "node", "iteration", "values_summary", "parent_checkpoint_id"}]}` (output of `graph.aget_state_history` projected) | 200 |
| `GET` | `/runs/{run_id}/checkpoints/{checkpoint_id}` | — | `{"checkpoint_id", "thread_id", "state": <full MetaHarnessState>, "ts", "node"}` | 200 |

### 6.3 Forks (`api/forks.py`)

| Method | Path | Request | Response | Status |
|---|---|---|---|---|
| `POST` | `/runs/{run_id}/fork` | `{"parent_checkpoint_id": "<id>", "mods": {"proposer_prior": "<new prior>"}, "parent_thread_id": "<optional>", "name": "<optional>"}` | `{"thread_id": "<run-id>.fork.<8hex>", "status": "running", "parent_checkpoint_id": "<id>", "branch_id": "<8hex>"}` | 202 |

`parent_thread_id` defaults to `run_id`, which preserves the original
fork-from-root behavior. Supplying it allows a future dashboard to fork
from an existing branch thread without changing the route shape.

### 6.4 Branches (`api/branches.py`)

| Method | Path | Request | Response | Status |
|---|---|---|---|---|
| `GET` | `/runs/{run_id}/branches` | — | `{"branches": [<BranchMetadata>]}` | 200 |
| `GET` | `/runs/{run_id}/trajectory` | — | `{"trajectory": {"run_id", "threads", "edges"}}` | 200 |
| `POST` | `/runs/{run_id}/branches/{thread_id}/cancel` | — | `{"status": "cancelled"}` (calls `task.cancel()` through Step 9 branch metadata) | 200 |

### 6.5 Memory (`api/memory.py`)

| Method | Path | Request | Response | Status |
|---|---|---|---|---|
| `GET` | `/memory/{namespace}` | — (query: `?limit=50`) | `{"namespace": ["learned_patterns","coding"], "entries": [{"key", "value", "score_delta", "evidence_run_ids"}], "implemented": false}` | 200 |
| `POST` | `/memory/{namespace}/search` | `{"query": "schema drift retry", "limit": 5}` | `{"results": [...], "implemented": false}` | 200 |

`namespace` is URL-encoded; the conventional shape is
`("learned_patterns", "<domain>")`.

Until Step 8 lands, the backend returns empty memory result sets with
`implemented=false`; callers must treat that as a valid placeholder, not
an error.

### 6.6 Events / SSE (`api/events.py`)

| Method | Path | Response |
|---|---|---|
| `GET` | `/runs/{run_id}/stream` | `text/event-stream` — see §7 below for event shape |

A single SSE stream per run multiplexes events from all branches; each
event carries its `thread_id` so the dashboard can route events to the
right branch in the trajectory tree.

---

## 7. SSE event format

*Channel naming convention (internal): `run:{run_id}` (multiplexed across
all threads of that run). Per Appendix A §A.5 the alternative is one
EventSource per branch (`run:{thread_id}`); we go with the multiplexed
form to limit browser connection count, with `thread_id` in every event.*

### 7.1 Wire format (HTML SSE spec)

```
event: state-update
id: <checkpoint-id>
data: {"thread_id": "run-2026-04-25-1430", "node": "propose", "iteration": 3, "ts": "2026-04-25T14:32:11Z", "summary": {"candidates_count": 3, "budget_remaining": 2}}

event: candidate-created
id: <checkpoint-id>
data: {"thread_id": "...", "candidate": "few-shot-tool-results", "import_path": "agents.few_shot_tool_results:CodingAgentHarness", "parent": "more-specific-descriptions"}

```

Blank line terminates each event. Reconnect via `Last-Event-ID` header
(checkpoint-id is monotonic per thread).

### 7.2 Event types (closed set)

| Event | Fired by | Data shape |
|---|---|---|
| `state-update` | every LangGraph node transition | `{thread_id, node, iteration, ts, summary}` |
| `checkpoint-written` | AsyncPostgresSaver post-write | `{thread_id, checkpoint_id, parent_checkpoint_id, ts, node}` |
| `candidate-created` | `propose` node after parsing pending_eval.json | `{thread_id, candidate, import_path, parent}` |
| `validate-result` | `validate` node | `{thread_id, candidate, valid, error?}` |
| `eval-result` | `benchmark` node | `{thread_id, candidate, accuracy, per_task, tokens, cost_usd}` |
| `frontier-updated` | `update_frontier` node | `{thread_id, iteration, frontier, best_candidate, delta}` |
| `iteration-complete` | end of `update_frontier` | `{thread_id, iteration, status: "improved"\|"no_improvement"}` |
| `fork-created` | `worktree_add` | `{thread_id, parent_thread_id, parent_checkpoint_id, mods_summary}` |
| `branch-cancelled` | cancel endpoint | `{thread_id, reason}` |
| `memory-pattern-stored` | end-of-run memory write | `{thread_id, namespace, key, score_delta}` |
| `error` | any node exception | `{thread_id, node, message, traceback}` |

### 7.3 Closed-set enforcement rule

The 11 event types in §7.2 are a **closed set, enforced at runtime**.

- To add a new SSE event type post-launch, both `INTERFACES.md` and
  `frontend/lib/sse.ts` must update in the same commit.
- The backend SSE channel registry (`backend/app/streaming.py`) maintains
  a registered allowlist of event-type strings derived from §7.2.
  `emit(event_type, payload)` for an unregistered type raises a
  500-class error rather than silently dropping; this surfaces drift in
  CI and at runtime instead of degrading the dashboard.
- Closed-ness is enforced, not just documented.

### 7.4 Subscription model — per-run multiplex (rationale)

The dashboard subscribes once per run via `GET /runs/{run_id}/stream`,
which multiplexes events from all branches. `thread_id` is on every
event payload; the frontend filters by it for view-specific updates.

Rationale: a user viewing a run wants to see all branches simultaneously
— the demo-day beat is two branches growing on screen at once. The
per-thread alternative (one EventSource per branch, per Appendix A §A.5)
would force the frontend to subscribe / unsubscribe as forks happen,
which is fragile during a live demo. Multiplexing costs one extra field
(`thread_id`) per event; cheap.

---

## 8. Resolutions of formerly-open questions

All 8 items previously surfaced here are now resolved. The locking pass
above pulled each into the relevant section.

| # | Topic | Resolution |
|---|---|---|
| 1 | Skill loading mechanism (Phase 1.3) | §5.3 — `skill_path` precedence rules + `--skill` / `--skill-dir` CLI |
| 2 | `Candidate` dataclass shape | §1.3 — `traces_dir: Path` is non-optional |
| 3 | `frontier_val.json` shape | §2.2 — `dominated_by_names: list[str]` per candidate; `_pareto_names` convenience |
| 4 | `evolution_summary.jsonl` row shape | §2.3 — `parent_candidate_name: str \| null` added |
| 5 | `write_file` status | §3.6 — formal 6th fixed tool with structured return shape |
| 6 | REST endpoint shapes | §6 — `POST /runs` returns **201 Created** + `Location` header |
| 7 | SSE event-types closed-set | §7.3 — runtime-enforced allowlist; 500 on unknown type |
| 8 | SSE subscription model | §7.4 — per-run multiplex with `thread_id` per event |

If a genuinely new ambiguity surfaces during implementation, it goes back
into this section as a 9th item rather than being silently designed.
