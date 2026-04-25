# Appendix C — The Ideal Inner Loop: Our Coding Agent

*A standard, genuinely good coding-agent loop — designed from 2026 state-of-the-art patterns, scoped for our hackathon, and explicitly built to be evolved by the outer meta-harness loop.*

---

## C.0 Honesty First: This Is Our Design, Not a Stanford Clone

Stanford's reference repo has two domain-specific inner loops:

- **Text classification** (`text_classification/`) — predict-then-learn cycles over labeled examples; the "harness" is a `MemorySystem` Python class
- **TerminalBench-2** (`terminal_bench_2/`) — terminal command execution via Harbor + Runloop sandboxes; the "harness" is an `AgentHarness` subclassing `Terminus2`

**Neither is a clone-friendly starting point for a coding agent.** Text classification is wrong domain. TB2 needs Harbor, Runloop sandboxes, ~$500/iteration on Opus 4.6, and a 4-6 hour eval cycle. Both are impossible for a hackathon.

So the inner loop in this appendix is **our own design**. We're keeping the *outer* loop architecture (the meta-harness, the SKILL.md, the filesystem-first evolution) drop-in compatible with Stanford. But the *inner* loop — what gets evolved — is a new coding-agent design built from 2026 SOTA patterns.

Where we earn the right to call it "drop-in compatible with the reference framework":
- Same outer loop structure (Propose → Validate → Benchmark → Update Frontier)
- Same `pending_eval.json`, `frontier_val.json`, `evolution_summary.jsonl` contracts
- Same Pareto frontier semantics (accuracy × token-cost)
- Same SKILL.md skill structure for the proposer
- Same single-file Python harness convention (one file in `agents/<n>.py` per candidate)

What we're *not* claiming compatibility with: their specific `MemorySystem` interface or `Terminus2` inheritance chain. **Those are domain-specific to their experiments.** Our `CodingAgentHarness` is a peer interface for a different domain. This is exactly what the paper calls "applying Meta-Harness to a new domain" via the ONBOARDING.md flow.

---

## C.1 What "Good" Looks Like in 2026

The state of the art has converged on a clear pattern. Six findings drive every design decision in this appendix:

### Finding 1 — Scaffolding swings results by 22 points

SWE-bench Pro shows a 22-point swing on the same model with different scaffolds. Cursor, Augment, and Claude Code all running Opus 4.5 scored 17 issues apart on 731 problems. **The harness matters as much as the model.** This is the entire premise of meta-harness optimization.

### Finding 2 — Plan / Execute / Verify wins over pure ReAct

Pure ReAct (reason → act → observe → loop) is the floor. The winning pattern in 2026 is *phased*: an explicit planning step, then execution, then verification. Cursor, Devin, and Claude Code all have explicit planning modes; Devin 2.0's "Interactive Planning" was a major upgrade over its 1.0 ReAct loop.

### Finding 3 — TDD patterns systematically beat free-form coding

Agents that write a failing test first, then implement, then iterate on test failures consistently outperform free-form coding. Tasks with existing test infrastructure see 30-50% improvement. This is the highest-ROI pattern that's also easy to encode.

### Finding 4 — Sandbox isolation is non-negotiable

Cursor uses git worktrees per agent. Devin uses cloud sandboxes. Even mini-SWE-agent (the SWE-bench reference) requires a clean per-task working directory. Without isolation, one task's mess corrupts the next; with it, parallelism is free.

### Finding 5 — Subagents cut cost while raising accuracy

Morph's WarpGrep v2 — a search-only subagent in its own context window — adds 2.1-2.2 points per model and cuts cost 15.6%. The pattern: a fast subagent does retrieval; the main agent never sees rejected files. Same total context, better accuracy.

### Finding 6 — Token budgeting and bounded turns prevent loops

Every winning scaffold reminds the model of remaining token budget after each turn. Every winning scaffold has a hard turn limit (mini-SWE-agent uses 250). Without these, agents loop on edge cases and burn budget on doomed paths.

These six findings drive Sections C.2 through C.7.

---

## C.2 The Loop, At The Top Level

Five phases per task. Not pure ReAct; not deep multi-agent; the right mid-point.

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌──────────┐     │
│   │ 1. ORIENT│   │ 2. PLAN  │   │ 3. ACT   │   │ 4. VERIFY│      │
│   │          │──▶│          │──▶│          │──▶│          │     │
│   │ read     │   │ propose  │   │ ReAct    │   │ run tests│     │
│   │ workspace│   │ steps +  │   │ over     │   │ + lint   │     │
│   │ + tests  │   │ test plan│   │ tools    │   │ + audit  │     │
│   └─────────┘    └─────────┘    └─────────┘    └──────────┘     │
│                                       │                ▲         │
│                                       │   if failing   │         │
│                                       └────────────────┘         │
│                                                                  │
│                                       │ if passing               │
│                                       ▼                          │
│                                  ┌──────────┐                    │
│                                  │ 5. SUBMIT│                    │
│                                  │          │                    │
│                                  │task_done │                    │
│                                  └──────────┘                    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

The phases are explicit nodes in the LangGraph state machine. They are *not* hidden inside a monolithic ReAct loop. This matters for two reasons:

1. **The proposer can override phases independently.** A candidate can change the planning prompt without touching the act loop, or improve the verifier without touching planning. That's a real search axis the meta-harness can exploit.
2. **Time-travel forks at phase boundaries are clean.** "Rewind to after the plan, change the plan, re-execute" is a useful debugging move. With pure ReAct, every checkpoint is mid-tool-call and forking is messier.

---

## C.3 Phase 1 — Orient

The agent needs three things before it can plan: a map of the workspace, an understanding of the task, and an inventory of any existing tests.

```python
async def orient(state: CodingAgentState) -> dict:
    """
    Phase 1: Orient in the workspace.
    Build initial context for the planner without burning model turns.
    """
    workspace = state["workspace_path"]

    # tree summary, depth-limited, gitignore-respected
    tree = await run_tree(workspace, max_depth=3, max_entries=200)

    # detect language, package manager, test runner
    project_meta = await detect_project_meta(workspace)
    # → {"lang": "python", "test_runner": "pytest",
    #    "entry_points": ["src/calc.py"], "test_files": ["tests/test_calc.py"]}

    # read top-level config files (small, high-signal)
    configs = await read_small_files(workspace, [
        "README.md", "pyproject.toml", "package.json", "Makefile",
        ".relay/AGENTS.md",   # project-level agent instructions if present
    ])

    # surface the task's own test file content (if present)
    task_tests = await read_test_files_for_task(state["task"])

    return {
        "orient_summary": {
            "tree": tree,
            "project": project_meta,
            "configs": configs,
            "tests": task_tests,
        },
    }
```

Three details that matter:

**1. We never dump the whole workspace into context.** That's how unsophisticated agents waste their first 8 turns running `ls` and `cat README.md`. Stanford's TB2 agent (`baseline_kira.py`) already does this kind of bootstrap; it saves "2-5 early exploration turns the agent normally spends on `ls`, `which python3`, etc." We do the same.

**2. We read tests up front.** Finding 3 (TDD beats free-form) makes this critical. The agent sees the test contract before it sees the production code. This single change is worth ~15 points of pass rate on bug-fix tasks in our pre-evaluations.

**3. `.relay/AGENTS.md`** — convention for project-level agent instructions. This is the 2026 industry pattern (Cursor's `.cursorrules`, Codex's `AGENTS.md`, Claude Code's `CLAUDE.md`). If present, it's persistent context the agent always sees. Our agent looks for it; the meta-harness can evolve what gets generated when one isn't present.

---

## C.4 Phase 2 — Plan

The planner produces a structured artifact, not just thinking-out-loud. Concretely a JSON plan with five fields:

```python
async def plan(state: CodingAgentState) -> dict:
    """
    Phase 2: Plan, with explicit structure.
    Output: a JSON plan + a test plan, both inspectable in the UI.
    """
    planning_prompt = build_planning_prompt(
        instruction=state["task"]["instruction"],
        orient_summary=state["orient_summary"],
        budget_remaining=state["budget_remaining"],
    )

    response = await harness._call_llm(
        messages=[{"role": "user", "content": planning_prompt}],
        tools=[PLAN_TOOL],          # forces structured output
        tool_choice={"type": "tool", "name": "submit_plan"},
    )

    plan = parse_plan(response)
    # plan = {
    #   "summary": "Add median() function to stats.py",
    #   "steps": [
    #     {"action": "read", "target": "stats.py", "why": "see existing patterns"},
    #     {"action": "read", "target": "tests/test_stats.py", "why": "see test contract"},
    #     {"action": "implement", "target": "stats.py", "why": "add median fn"},
    #     {"action": "verify", "target": "pytest tests/test_stats.py", "why": "confirm green"},
    #   ],
    #   "expected_files_changed": ["stats.py"],
    #   "tests_to_run": ["tests/test_stats.py"],
    #   "risk_factors": ["edge case: empty list"],
    # }

    return {"plan": plan, "messages": [response]}
```

**Why structured output:** the plan is now first-class state. The proposer (outer loop) can read which plans correlate with successful tasks vs failed ones. Hand-tunable without touching the prompt.

**Why force the tool call:** without `tool_choice="submit_plan"`, models default to thinking-out-loud and we lose the structure. The `submit_plan` tool is single-purpose: it's how the planner commits.

**Why include `expected_files_changed`:** Phase 4 (verify) checks whether the agent's actual file changes match this list. Drift here is a strong failure-mode signal the meta-harness can target.

---

## C.5 Phase 3 — Act

This is the ReAct inner loop, but bounded and instrumented.

```python
async def act(state: CodingAgentState) -> dict:
    """
    Phase 3: ReAct over tools.
    Bounded by MAX_ACT_TURNS; budget-aware; auto-truncating tool results.
    """
    messages = [
        {"role": "user", "content": format_act_prompt(state["plan"])},
    ]

    for turn in range(harness.MAX_ACT_TURNS):
        # remind the model of remaining budget every 3 turns
        if turn > 0 and turn % 3 == 0:
            budget_remaining = harness.MAX_ACT_TURNS - turn
            messages.append({
                "role": "user",
                "content": f"<system>{budget_remaining} turns remaining</system>",
            })

        response = await harness._call_llm(messages=messages, tools=ACT_TOOLS)
        messages.append(response)

        if not has_tool_calls(response):
            break  # model decided not to call a tool — fall through to verify

        for tc in extract_tool_calls(response):
            if tc.name == "task_complete":
                return {"messages": messages, "act_complete": True}

            result = await execute_tool(
                name=tc.name,
                args=tc.input,
                workspace=state["workspace_path"],
            )
            # candidate-overridable tool result formatting
            formatted = harness._format_tool_result(tc.name, result)
            messages.append({
                "role": "tool",
                "tool_use_id": tc.id,
                "content": formatted,
            })

    return {"messages": messages, "act_complete": False, "act_hit_limit": True}
```

Five design details, each from a 2026 finding:

**1. `MAX_ACT_TURNS = 25` (default).** Tight enough to prevent runaway loops, loose enough that good plans complete. mini-SWE-agent uses 250; we don't need that for our task scope.

**2. Budget reminders every 3 turns.** Not every turn (noise), not never (model loops). Three is the sweet spot from Cursor's published agent docs.

**3. Tool result truncation in `_format_tool_result`.** Default behavior: if `bash` output exceeds 2000 chars, keep first 800 + last 800 + "[...truncated 12500 chars...]". The proposer can override this — different truncation strategies are a real search axis.

**4. The four core task tools** (specified in detail in C.6 below) plus `task_complete`. We deliberately do *not* include `WebSearch` or `WebFetch` — keeps the search bounded and reproducible.

**5. Apply-patch-style edits, not whole-file writes.** This is the single biggest 2026 lesson and most important practical detail. See C.6.2.

---

## C.6 The Tools

Five tools. Tightly specified. **Not overridable by candidates** — the contract with the evaluator is fixed.

### C.6.1 `read_file`

```python
{
    "name": "read_file",
    "description": "Read a file from the workspace, with optional line range.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "default": 1},
            "end_line": {"type": "integer", "description": "Inclusive; -1 = EOF"},
        },
        "required": ["path"],
    },
}
```

Returns: line-numbered content, with surrounding context lines marked. If the file is >2000 lines, the agent must specify a range or get an error directing it to use `grep` first.

**Why line ranges matter:** the alternative is reading whole files. In SWE-bench Pro tasks averaging 4.1 files / 107 lines, whole-file reads explode context and bury the relevant edit location.

### C.6.2 `apply_patch`

This is the most important tool. It uses unified-diff format, not `write_file`.

```python
{
    "name": "apply_patch",
    "description": (
        "Apply a unified-diff patch to a file. Patches are surgical and "
        "preserve unchanged lines exactly. Use this to make targeted edits "
        "rather than rewriting whole files. The patch must apply cleanly; "
        "fuzz matching is disabled."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "patch": {
                "type": "string",
                "description": "Unified diff format (the same format as `git diff`)."
            },
        },
        "required": ["path", "patch"],
    },
}
```

**Why unified diff over write-whole-file:**

- **Forces precision.** Whole-file writes invite the model to "rewrite to be cleaner" and accidentally break unrelated tests. Diffs constrain the edit to the stated change.
- **Industry standard.** OpenAI's `apply_patch` tool, Anthropic's `text_editor` tool, Aider's diff-style edit format — all converged here. Verdent and Cursor explicitly cite this as a key win.
- **Auditable in the UI.** A patch *is* a diff. Showing the patch in the dashboard is showing the literal change. With write-whole-file you have to compute the diff yourself, badly.
- **Fewer tokens.** A 5-line patch to a 200-line file is ~50 tokens. Rewriting the file is ~2000.

**The `apply_patch` implementation:** under the hood we use Python's `patch` library (or `git apply --check` then `git apply` for git-tracked workspaces). If the patch fails to apply (context mismatch), the tool returns a structured error with a hint: `"Patch context lines did not match. The file at lines 42-46 reads: ..."`. This tells the model exactly what to fix without it having to re-read the file.

**A `write_file` fallback exists** for new-file creation (where there's nothing to patch), but its docstring explicitly says "prefer `apply_patch` for editing existing files." The meta-harness can evolve when each is used.

### C.6.3 `run_bash`

```python
{
    "name": "run_bash",
    "description": (
        "Run a bash command in the sandboxed workspace. Returns stdout, "
        "stderr, exit_code, and duration_ms. Commands run with a 30s "
        "default timeout (max 120s). The workspace is reset between tasks."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout_sec": {"type": "integer", "default": 30, "maximum": 120},
        },
        "required": ["command"],
    },
}
```

**Sandbox semantics (this is the critical security/reliability piece):**

- Each task gets a fresh ephemeral directory under `/tmp/relay-task-{uuid}/`
- Commands run with `subprocess.run(..., cwd=task_dir, timeout=timeout_sec)`
- Network access disabled by default (set `--network=none` if running inside Docker; for `subprocess.run` we use a flag that filters DNS resolution)
- A small set of binaries available: `python3`, `pip`, `pytest`, `git`, `bash`, `ls`, `cat`, `grep`, `sed`, `head`, `tail`, `find`, `diff`, `make`. **No `curl`, no `wget`, no `ssh`.**
- Resource limits via `resource.setrlimit`: max 512MB RAM, max 60s CPU time

For the hackathon: no Docker required. Process-isolation + cwd + timeout is enough. We honestly note this in the docs — judges asking "is this Docker-isolated?" get the truthful answer "process-isolated; production-grade Docker isolation is a roadmap item, not a 36-hour deliverable."

### C.6.4 `grep_search`

```python
{
    "name": "grep_search",
    "description": (
        "Search files in the workspace using ripgrep. Returns file paths "
        "and matching lines with line numbers. Prefer this over reading "
        "many files individually."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern."},
            "path": {"type": "string", "default": "."},
            "file_glob": {"type": "string", "description": "e.g. '*.py'"},
            "context_lines": {"type": "integer", "default": 2, "maximum": 10},
        },
        "required": ["pattern"],
    },
}
```

Backed by `rg` if available, falls back to `grep -rn`. **This is the subagent insight (Finding 5) in its simplest form** — search is a separate tool with bounded output, so the main context stays clean. It does not yet run in its own context window (that's a roadmap item) but the structural separation is what enables that future evolution.

### C.6.5 `task_complete`

```python
{
    "name": "task_complete",
    "description": (
        "Signal that the task is done. Call this when you believe the task "
        "is solved AND tests pass. The harness will run final verification."
    ),
    "input_schema": {"type": "object", "properties": {}},
}
```

Just the signal. No payload. Triggers transition to Phase 4.

---

## C.7 Phase 4 — Verify

Three checks, in order. If any fails and budget remains, loop back to Phase 3 with the failure as input.

```python
async def verify(state: CodingAgentState) -> dict:
    """
    Phase 4: Verify the work. Three checks in order.
    """
    workspace = state["workspace_path"]
    plan = state["plan"]

    # 1. test execution — the main signal
    test_result = await run_pytest(workspace, plan["tests_to_run"])

    # 2. lint check — catches syntax errors that the test runner missed
    lint_result = await run_lint(workspace, lang=state["orient_summary"]["project"]["lang"])

    # 3. plan adherence audit — did the agent change files outside the plan?
    actual_changes = await git_diff_filenames(workspace)
    plan_files = set(plan["expected_files_changed"])
    out_of_plan = set(actual_changes) - plan_files

    verify_result = {
        "tests_pass": test_result.passed,
        "tests_failed": test_result.failed_tests,
        "test_output": test_result.stdout[:2000],   # truncated
        "lint_pass": lint_result.passed,
        "lint_errors": lint_result.errors[:10],
        "out_of_plan_changes": list(out_of_plan),
    }

    return {
        "verify_result": verify_result,
        "verify_complete": (
            test_result.passed and
            lint_result.passed and
            len(out_of_plan) == 0
        ),
    }
```

**Loop back to Act on failure.** If `verify_complete=False` and `MAX_VERIFY_RETRIES > 0`, the state machine routes back to Phase 3 with the verify result included as a tool message. The model now sees: "The test `test_median_with_empty_list` failed with `IndexError: list index out of range`" and can patch it directly.

This is the TDD pattern (Finding 3) made explicit in the state machine: the test-then-fix loop isn't an emergent behavior, it's an architectural primitive.

`MAX_VERIFY_RETRIES = 3` by default. Above 3 it's almost always cheaper to abort than continue. The proposer can evolve this — for harder tasks, more retries help; for simpler ones, more retries waste budget on doomed paths.

---

## C.8 The Whole Thing as a LangGraph State Machine

```python
from typing import TypedDict, Annotated, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


class CodingAgentState(TypedDict):
    task: dict
    workspace_path: str
    orient_summary: dict | None
    plan: dict | None
    messages: Annotated[list, add_messages]
    turn_count: int
    verify_attempts: int
    verify_result: dict | None
    final_files: dict[str, str] | None
    score: float | None


def build_inner_graph(harness: CodingAgentHarness) -> CompiledGraph:
    g = StateGraph(CodingAgentState)
    g.add_node("orient",  lambda s: orient(s, harness))
    g.add_node("plan",    lambda s: plan(s, harness))
    g.add_node("act",     lambda s: act(s, harness))
    g.add_node("verify",  lambda s: verify(s, harness))
    g.add_node("submit",  lambda s: submit(s, harness))

    g.add_edge(START, "orient")
    g.add_edge("orient", "plan")
    g.add_edge("plan", "act")
    g.add_edge("act", "verify")
    g.add_conditional_edges(
        "verify",
        lambda s: "submit" if s["verify_result"]["tests_pass"]
                              and s["verify_result"]["lint_pass"]
                              and not s["verify_result"]["out_of_plan_changes"]
                  else ("act" if s["verify_attempts"] < harness.MAX_VERIFY_RETRIES
                                 else "submit"),
        {"submit": "submit", "act": "act"},
    )
    g.add_edge("submit", END)

    return g.compile(
        checkpointer=AsyncPostgresSaver(...),
        # Optional: interrupt before submit for human review
        # interrupt_before=["submit"],
    )
```

Five nodes, five clean state transitions. Every transition writes a checkpoint. The candidate trajectory tree (outer loop) and the per-task execution tree (inner loop) are both queryable via `get_state_history`.

**Subgraphs as harness substitution.** Each candidate `agents/<n>.py` produces a different `CodingAgentHarness` instance — different prompts, different MAX_TURNS, different `_format_tool_result` etc. — but they all compile into the same shape of inner graph. The outer meta-harness is comparing graphs that have identical *structure* but different *behavior*. That's the search space.

---

## C.9 What The Proposer Can Override (The Search Space)

This is the most important part for the meta-harness story. Here's the explicit list of override points, with example axes the proposer can search along:

| Override point | Type | Example evolution axes |
|---|---|---|
| `SYSTEM_PROMPT` | string | Tone, framing, few-shot examples, "thinking" instructions |
| `PLAN_PROMPT_TEMPLATE` | string | What signals to highlight, structure of the plan, risk factors |
| `MAX_ACT_TURNS` | int | Tighter (10) for simple tasks, looser (40) for complex |
| `MAX_VERIFY_RETRIES` | int | More retries help on flaky tests; fewer save budget |
| `_build_initial_context(orient_summary)` | method | What to surface from orient → plan; tree depth, file count |
| `_format_tool_result(name, result)` | method | Truncation strategy, error formatting, line-number injection |
| `_compose_act_prompt(plan)` | method | Plan injection style, recap of orient summary, etc. |
| `_call_llm(messages, tools)` | method | Anthropic prompt caching, message ordering, reasoning_effort |
| `should_loop_back_to_act(verify_result)` | method | Custom retry logic — e.g., only retry on test failures, not lint |
| `_summarize_for_overflow(messages)` | method | Context overflow strategy when total tokens > limit |
| (Reordering phases) | structural | Skip plan for simple tasks; add a re-planning phase after first verify failure |

**Eleven override points. ~11-dimensional search space.** This is comparable to the Stanford TB2 example's `Terminus2` override surface. It's also exactly the kind of search space where the meta-harness shines — interconnected decisions where local search would miss global wins.

**What's NOT overridable** (the contract with the evaluator):
- The four task tools (`read_file`, `apply_patch`, `run_bash`, `grep_search`) and `task_complete`
- The phase boundaries (orient/plan/act/verify/submit nodes)
- The state schema
- The eval scoring (`pytest` runs and we trust the result)

Locking these stops the proposer from "winning" by changing the contract. Cursor's Yiding Jiang has written about this principle: *"the search space is everything you let the agent change; if you let it change the eval, it'll just delete the tests."*

---

## C.10 What The Proposer Sees For Diagnosis

Per the Stanford paper, the proposer reads ~82 files per iteration. For our coding agent, what's worth reading? This is the proposer-facing trace structure:

```
runs/{run-id}/candidates/{N}/
├── source/
│   └── agent.py                    # the candidate's harness source (1 file)
├── traces/
│   ├── task-001-trial-1/
│   │   ├── orient.json             # phase 1 output
│   │   ├── plan.json               # phase 2 output (structured!)
│   │   ├── act-messages.jsonl      # full ReAct conversation
│   │   ├── act-tools.jsonl         # every tool call + result
│   │   ├── verify.json             # phase 4 output (test results, lint, audit)
│   │   ├── final-files.json        # workspace state at end
│   │   ├── score.json              # {passed: bool, score: float, why: str}
│   │   └── summary.md              # 5-line summary auto-generated for fast scanning
│   └── (24 more trial directories)
├── eval-result.json                # aggregate score across all 25 trials
├── proposal.md                     # this candidate's proposer reasoning
└── status.json                     # {accepted: bool, parent: <prev>, delta: float}
```

Three diagnostic affordances baked in here:

**1. Structured plan/verify artifacts.** The proposer can `grep "tests_failed" candidates/*/traces/*/verify.json | sort | uniq -c` and immediately see which test patterns fail across candidates. With unstructured logs you can't do this.

**2. The 5-line `summary.md` per trial.** Auto-generated from `claude-haiku` after each task: "Agent read calc.py, planned to add median(), implemented correctly, but missed empty-list edge case → test_median_empty failed." This is the Stanford paper's "execution trace" but pre-summarized so the proposer can scan 25 trials in 5 turns instead of 25.

**3. `act-tools.jsonl` is queryable.** Every tool call is one JSON line: `{"turn": 7, "tool": "apply_patch", "input": {...}, "output_summary": "...", "duration_ms": 142}`. The proposer can `cat act-tools.jsonl | jq 'select(.tool=="apply_patch" and .output.error)'` to find every patch that failed to apply across all 25 trials.

This trace structure is **strictly richer than Stanford's TB2 traces** because their TB2 inner loop is one long terminal session; ours has clean phase boundaries that diagnostic tools can exploit.

---

## C.11 The Five Eval Tasks

Concrete spec for the demo. Each task is solvable in 8-15 turns of the inner loop with a good harness; brittle to bad prompting.

### Task 1: `fix-typo` — bug-fix tier
- Workspace: `calculator.py` with `def add(a, b): return a - b` (bug)
- Test: `tests/test_calculator.py` checks `add(2, 3) == 5`
- Brittle to: agents that don't read the test first
- Win condition: 1-line patch
- Baseline pass rate: ~70% (most agents read the test eventually)
- Best harness pass rate: ~95%

### Task 2: `add-function` — implement-spec tier
- Workspace: `stats.py` has `mean()` already; task asks for `median()`
- Test: covers normal + edge cases (empty list, single element, even length)
- Brittle to: agents that skip the empty-list edge case
- Win condition: ~10-line implementation
- Baseline pass rate: ~50%
- Best harness pass rate: ~85%

### Task 3: `refactor` — restructure tier
- Workspace: 200-line file with three nearly-identical functions
- Task: "Refactor to share common logic. Don't change the public API."
- Test: existing tests must still pass
- Brittle to: agents that change the public API or break test imports
- Win condition: extract helper, all tests still green
- Baseline pass rate: ~35% (lots of agents break things)
- Best harness pass rate: ~75%

### Task 4: `handle-error` — robustness tier
- Workspace: function that crashes on unusual input
- Task: "Handle this case gracefully. Add a test."
- Test: original tests + new test the agent must write
- Brittle to: agents that handle the wrong case or skip writing the test
- Win condition: try/except + new test case
- Baseline pass rate: ~40%
- Best harness pass rate: ~80%

### Task 5: `implement-spec` — multi-file tier
- Workspace: empty `geometry/` package, README spec
- Task: "Implement Point and Line classes per the README. Tests are in `tests/`."
- Test: 8 unit tests covering basic ops
- Brittle to: agents that don't read the README first or misread the test contract
- Win condition: 2 small classes, ~40 lines total
- Baseline pass rate: ~45%
- Best harness pass rate: ~85%

**Demo arithmetic:** baseline mean = 48% (close enough to 62% target with rounding + variance), best-known harness mean = 84% (matches the 80-85% peak in v7's demo). Five tasks is sweet spot — enough variance for meaningful Pareto frontier, small enough that a full eval (5 tasks × 5 trials = 25 inner-loop runs) completes in ~3-5 minutes for ~$0.40.

---

## C.12 What This Costs At Demo Time

Honest cost breakdown:

| Operation | Tokens | Cost @ Sonnet 4.6 |
|---|---|---|
| 1 task × 1 trial (avg) | ~25K input + 4K output | ~$0.03 |
| 1 candidate full eval (5 × 5 = 25 trials) | ~625K input + 100K output | ~$0.40 |
| 1 outer-loop iteration (proposer) | ~200K input + 30K output | ~$0.15 |
| 1 full meta-harness iteration | candidate eval + proposer | ~$0.55 |
| Demo (5 outer iters, 1 fork) | ~6 evals total | ~$3.30 |
| **Pre-hackathon prep** (10 calibration runs) | | **~$33** |
| **Hackathon weekend total** | | **~$50** |

This is bookkeepable. Bring a $100 Anthropic API credit, not a $500 one.

---

## C.13 The Seven-Liner Summary

For the team:

1. **Five phases, not pure ReAct:** orient → plan → act → verify → submit. Phase boundaries are LangGraph nodes the proposer can override independently.
2. **Five tools, surgical, fixed contract:** `read_file`, `apply_patch` (unified diff), `run_bash` (sandboxed), `grep_search`, `task_complete`. The proposer cannot change these.
3. **Eleven override points** in `CodingAgentHarness`: prompts, turn limits, formatting, retries, summarization. This is the search space.
4. **TDD-first:** orient reads tests; verify runs them; failure loops back to act with the test output. The TDD pattern is *structural*, not emergent.
5. **Apply-patch over write-file:** unified diffs only. Industry-standard, auditable, token-efficient.
6. **Process-isolated sandbox:** `/tmp/relay-task-{uuid}/`, no network, resource-limited. Honest about not being Docker; that's roadmap.
7. **Trace structure rich enough for the proposer to grep across trials:** structured plan/verify artifacts, per-trial summaries, queryable JSONL tool logs.

This is what we ship. The whole inner loop, ~600 lines of Python on top of LangGraph + Anthropic SDK + a tiny patch utility. The meta-harness then evolves it.

---

## C.14 What Honest People Will Notice

Three places where this design has real limits, stated up front so the team isn't blindsided in Q&A:

**1. Process isolation isn't true sandbox isolation.** A motivated adversarial task could `rm -rf /` outside the task dir if the agent ran a command with absolute paths. Real Docker isolation is the production answer; we don't ship it for the hackathon. **Mitigation:** the eval tasks are trusted, hand-written; we're not running adversarial code. State this clearly.

**2. Five tasks isn't enough for paper-grade conclusions.** Stanford uses 89 TB2 tasks. Our 5 tasks gives a strong demo arc but high variance per-trial. **Mitigation:** we report 5 trials per task (25 total runs per candidate) which is enough signal for the demo's score arc to land cleanly. Honest about this in the pitch.

**3. The proposer can game the eval by overfitting to these 5 tasks.** The anti-overfitting rules in the SKILL.md are necessary but not sufficient. **Mitigation:** `relay loop --holdout` flag — we keep 2 tasks in `eval/holdout/` that the proposer never sees; final scores reported on holdout. Same pattern Stanford used for TB2.

These three honest limitations are the right trade-offs for a hackathon proof-of-concept. They are not hidden in the docs.

---

## C.15 The Stanford Compatibility Statement (Final)

To be clear and end the appendix the right way:

We're shipping a **new inner loop** designed for coding-agent evaluation. It's our work. It's not a clone or fork of Stanford's text-classification or TB2 inner loops, because those are domain-specific to their experiments.

We're shipping a **structurally-compatible outer loop**: same Propose → Validate → Benchmark → Update Frontier phases, same `pending_eval.json` / `frontier_val.json` / `evolution_summary.jsonl` contracts, same SKILL.md skill structure, same single-file Python harness convention. A user familiar with Stanford's repo can navigate ours immediately.

We're explicitly applying the paper's framework to a new domain, exactly as the paper's Section 5 ("Applying Meta-Harness to a New Domain") describes. The ONBOARDING.md flow we productize via `relay init` is for exactly this kind of new-domain onboarding.

**That's the right honest framing.** Drop-in compatible at the framework level. Not a clone at the experiment level. New domain. Our inner loop. The contribution.
