# Appendix B — The Meta-Harness Two-Loop Architecture & Our Minimal Coding Agent

*A deep-dive into how Stanford's Meta-Harness actually works internally, and a precise spec for what we ship: the inner harness (a minimal coding agent) and the outer meta-harness skill (the proposer's instruction set).*

---

## B.0 Why this appendix exists

Until now, we've talked about "the meta-harness loop" as one thing. After reading the Stanford reference repo line-by-line, **it's actually two loops, and conflating them obscures what we're really building.** This appendix separates them, specifies each clearly, and lands on the concrete code shape for our hackathon scope: a minimal coding agent (the inner loop) and a meta-harness skill (the thing that lets Claude Code rewrite the inner loop).

By the end, you'll know:
- Exactly what the "meta-harness tool" is (it's a SKILL.md, not a tool)
- What's in our `agents/` directory (the harness being optimized)
- What's in our `.claude/skills/relay-meta/SKILL.md` (the proposer's instructions)
- How both layers map onto LangGraph state machines
- What we cut from the paper and why

---

## B.1 The Two Loops, Disambiguated

The Stanford repo has two state machines. Calling both "the loop" causes confusion every time. Name them:

```
                         ┌───────────────────────────────────────┐
                         │           OUTER LOOP                  │
                         │      (the META-HARNESS itself)        │
                         │                                       │
                         │   Runs ~20 iterations per session.    │
                         │   Each iteration produces a new       │
                         │   candidate HARNESS by reading prior  │
                         │   candidates' source + traces.        │
                         │                                       │
                         │   Actor: PROPOSER AGENT               │
                         │           (Claude Code w/ SKILL.md)   │
                         └───────────────┬───────────────────────┘
                                         │
                                         │ writes a new
                                         │ harness file
                                         ▼
                         ┌───────────────────────────────────────┐
                         │           INNER LOOP                  │
                         │    (the HARNESS being optimized)      │
                         │                                       │
                         │   Runs once per (candidate × task).   │
                         │   With 5 tasks × 5 trials × 5 iters   │
                         │   = 125 inner-loop runs total.        │
                         │                                       │
                         │   Actor: TASK AGENT                   │
                         │           (the harness's Python code) │
                         └───────────────────────────────────────┘
```

The outer loop is what gets called "the meta-harness." The inner loop is what people usually call "the agent."

**The outer loop's job:** evolve the inner loop's source code.
**The inner loop's job:** solve actual user tasks.

Everything that follows is precise about which loop a given component belongs to.

---

## B.2 How Stanford's Outer Loop Works (the actual mechanics)

The outer loop is implemented in `meta_harness.py` per reference example. It has four phases per iteration, exactly as the deepwiki page describes:

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  1. PROPOSE      │───▶│  2. VALIDATE     │───▶│  3. BENCHMARK    │───▶│  4. UPDATE       │
│                  │    │                  │    │                  │    │     FRONTIER     │
│  claude_wrapper  │    │  smoke test:     │    │  run validation  │    │  parse results,  │
│  spawns Claude   │    │  Python import   │    │  set with        │    │  compute Pareto  │
│  Code with the   │    │  check, or 1-task│    │  ThreadPool      │    │  frontier on    │
│  SKILL.md skill  │    │  smoke run       │    │  parallelism     │    │  (acc, ctx_size)│
└──────────────────┘    └──────────────────┘    └──────────────────┘    └──────────────────┘
```

Three persistent state files coordinate the phases:

| File | Written by | Read by | Purpose |
|---|---|---|---|
| `pending_eval.json` | Proposer (phase 1) | Validator + Benchmark (2, 3) | New candidates to evaluate this iteration |
| `frontier_val.json` | UpdateFrontier (phase 4) | Proposer next iteration (1) | Current Pareto frontier of validated candidates |
| `evolution_summary.jsonl` | UpdateFrontier (phase 4) | Proposer next iteration (1) | Append-only log of EVERY candidate, hypothesis, score |

**Critical detail:** the proposer reads ~82 files per iteration in TB2 (paper's Table 8): 41% prior harness source code, 40% execution traces, 6% scores, 13% other. **The proposer is non-Markovian** — it routinely reads from candidates 5-10 iterations ago, not just the most recent parent. This is the entire point of the filesystem approach: uncompressed access to the full history.

---

## B.3 The "Meta-Harness Tool" Is a SKILL.md (not a tool)

This is the key thing that wasn't clear before. The "tool that lets the AI edit other tools" is **a Claude Code skill** — a specific Markdown file with YAML frontmatter that gets injected into the proposer's system prompt.

When `claude_wrapper.py` spawns `claude` as a subprocess, it does this (paraphrased from the Stanford code):

```bash
claude \
    --dangerously-skip-permissions \
    --disable-slash-commands \
    --plugin-dir /tmp/empty \
    --output-format stream-json \
    --append-system-prompt "$(cat .claude/skills/meta-harness/SKILL.md)
                            $(cat domain_spec.md)
                            $(cat proposer_prior.md)" \
    "Improve the harness. Iteration {N}. Read evolution_summary.jsonl first."
```

Three pieces are appended to the system prompt:

1. **`SKILL.md`** — the *workflow* the proposer follows (Analyze → Prototype → Implement → Register). This is the same across all runs of this domain.
2. **`domain_spec.md`** — the *interface contract* (what file structure, what Python class, what evaluation metric). Domain-specific, written once via `relay init`.
3. **`proposer_prior.md`** — the *anti-overfitting rules* + *anti-parameter-tuning rules*. Same across runs.

**The skill is the meta-harness tool.** When the user kept asking "what's the actual tool that lets the AI rewrite other tools," they were asking about this Markdown file. It's the literal prompt that turns Claude Code into a meta-harness proposer.

### B.3.1 The skill structure (verbatim shape from Stanford's repo)

A meta-harness skill has this structure:

```
.claude/
└── skills/
    └── meta-harness-{domain}/
        └── SKILL.md          # frontmatter + body
```

The frontmatter is YAML:

```yaml
---
name: meta-harness-{domain}
description: Evolve the harness for {domain}. Use when running meta_harness.py
             iterations to propose new candidate harnesses based on prior
             execution traces and scores.
---
```

The body is Markdown with these required sections (extracted from the Stanford text-classification skill):

1. **What you are doing** — one paragraph framing the task
2. **Hard rules (Anti-Overfitting)** — explicit forbidden behaviors:
   - No mentioning specific dataset/task names in code or comments
   - No hard-coded class mappings or task-specific string matches
   - All improvements must be framed as general principles
3. **Hard rules (Anti-Parameter-Tuning)** — mechanism-first design:
   - Don't change constants (pool sizes, learning rates) without changing mechanism
   - Self-critique: verify the new candidate is *structurally* different from base
4. **Workflow** — numbered steps:
   1. Analyze — read `evolution_summary.jsonl` and `frontier_val.json`. Form 3 falsifiable hypotheses.
   2. Prototype — write isolated test scripts in `/tmp/` to exercise logic before full implementation.
   3. Implement — copy a base system; apply targeted modifications; create `agents/<name>.py` files.
   4. Register — write `pending_eval.json` with name, hypothesis, axis (exploration vs exploitation).
5. **Interface contract** — Python class signature the candidate must implement
6. **The pending_eval.json schema** — exact JSON shape required

The body is typically 100-200 lines. Total skill file: ~5KB of Markdown.

---

## B.4 What We're Building: The Minimal Coding Agent (Inner Loop)

The Stanford TB2 example uses Harbor + Runloop sandboxes + Opus 4.6 + ~$500/iteration. **This is impossible for a hackathon.** We need a domain that's:

- Realistic enough to demo meaningfully (climbs from ~62% → ~85%)
- Cheap enough to run live (Sonnet 4.6, no sandbox infrastructure)
- Small enough that one iteration completes in ~60-90 seconds
- Bounded enough that failures are localized (no runaway shell commands)

The answer: **a minimal coding agent operating on a sandbox-in-a-Docker-container or in-memory virtual filesystem, solving small code-editing tasks.**

### B.4.1 The harness interface (what gets evolved)

```python
# agents/baseline.py — the starting harness
from typing import Any
from relay_sdk import BaseHarness  # our project's base class


class CodingAgentHarness(BaseHarness):
    """Minimal coding agent. The OUTER LOOP evolves this file's source code."""

    SYSTEM_PROMPT = """You are a careful coding assistant. You have access to
                       read_file, write_file, list_dir, and run_bash tools.
                       Solve the user's task by reading the relevant files first,
                       then making targeted edits."""

    MAX_TURNS = 20
    REASONING_EFFORT = "medium"

    def solve(self, task: dict) -> dict:
        """
        Run the agent loop on a single task.
        task = {"id": str, "instruction": str, "workspace_path": str,
                "test_command": str}
        Returns {"final_files": dict[path, content], "transcript": list[message],
                 "turn_count": int}
        """
        # standard agent loop:
        # 1. assemble system prompt + task instruction + initial workspace listing
        # 2. call LLM with tools
        # 3. execute tool calls (read_file, write_file, list_dir, run_bash)
        # 4. append result to message history
        # 5. loop until task_complete tool called or MAX_TURNS reached
        ...

    def _call_llm(self, messages, tools):
        """The LLM call — overridable by candidates."""
        ...

    def _build_initial_context(self, task):
        """How the workspace is summarized for the model — overridable."""
        ...

    def _format_tool_result(self, result):
        """How tool outputs are presented back — overridable."""
        ...
```

### B.4.2 The four tools (what the agent can do)

These mirror the standard tool bundles in Stanford's `claude_wrapper.py` but applied to our task agent (not the proposer):

```python
TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file from the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write or overwrite a file in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": "List directory contents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."}
            },
        },
    },
    {
        "name": "run_bash",
        "description": "Run a bash command in the sandboxed workspace. "
                       "Returns stdout + stderr + exit_code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_sec": {"type": "integer", "default": 30},
            },
            "required": ["command"],
        },
    },
    {
        "name": "task_complete",
        "description": "Signal that the task is done. Call this when you "
                       "believe the task is solved.",
        "input_schema": {"type": "object", "properties": {}},
    },
]
```

The `run_bash` runs in an isolated Docker container per task (or, for hackathon scope, a `/tmp/relay-task-{uuid}/` directory with `subprocess.run(..., cwd=...)` and a strict timeout). No real sandbox; just process isolation. This is fine because the eval tasks are bounded.

### B.4.3 What the proposer overrides (the search space)

The proposer (outer loop) creates new files like `agents/candidate_001.py` that subclass `CodingAgentHarness` and override specific methods. The search space is:

| Method | What candidates change |
|---|---|
| `SYSTEM_PROMPT` | Prompt engineering — tone, instructions, few-shot examples |
| `MAX_TURNS` | Budget allocation per task |
| `_build_initial_context` | What the agent sees first (full file dump? `tree` output? README only?) |
| `_format_tool_result` | How tool outputs come back (truncate? summarize? include line numbers?) |
| `_call_llm` | LLM call mechanics (caching, message ordering, reasoning_effort) |
| `solve` | The whole loop architecture — could add planning step, verification step, etc. |

This matches the paper's "search over harness code" exactly — single-file Python programs where the proposer can make any change to any of these methods.

### B.4.4 The eval tasks (what the agent solves)

For the demo: 5 small code-editing tasks, each with a unit test as ground-truth:

```
eval/
├── tasks/
│   ├── task-001-fix-typo/
│   │   ├── workspace/
│   │   │   ├── calculator.py        # has `def add(a, b): return a - b`
│   │   │   └── test_calculator.py
│   │   └── task.json                # {"instruction": "Fix the bug in calculator.py"}
│   ├── task-002-add-function/
│   │   ├── workspace/
│   │   │   ├── stats.py             # has mean() but task asks for median()
│   │   │   └── test_stats.py
│   │   └── task.json
│   ├── task-003-refactor/...
│   ├── task-004-handle-error/...
│   └── task-005-implement-spec/...
└── score.py                          # runs pytest, returns pass rate
```

Each task is solvable in 5-15 turns with good prompting; brittle to bad prompting (e.g., if the agent doesn't read `test_*.py` first, it'll guess wrong). This gives the proposer real signal — failures concentrate around specific harness decisions like "does the agent know to look at tests before editing?"

### B.4.5 Why this scope is right

| Decision | Reason |
|---|---|
| 5 tasks (not 89 like TB2) | One eval cycle = ~3-5 minutes; demo budget allows ~5 iterations |
| 5 trials per task | Mirror paper's multi-trial averaging; expose variance |
| Sonnet 4.6 (not Opus) | ~10× cheaper, ~3× faster, still capable enough for the task complexity |
| Local sandbox (not Runloop) | Zero infrastructure; works on any laptop |
| Single Python file harness | Matches paper's search space; easy to diff between candidates |
| `pytest` as scoring | Deterministic; no LLM-judge needed |

Cost estimate: ~$0.50 per outer-loop iteration. A full 5-iteration demo run = ~$2.50. The total LA Hacks demo cost over the weekend stays under $50 even with extensive testing.

---

## B.5 What We're Building: The Meta-Harness Skill (Outer Loop)

Now the actual skill file. This is what makes Claude Code (or our LangGraph proposer) into a meta-harness. **This is the literal text that tells the AI "go edit the inner loop's code."**

### B.5.1 `relay/skills/meta-harness-coding-agent/SKILL.md`

```markdown
---
name: meta-harness-coding-agent
description: Evolve the coding agent harness. Use this skill when invoked
             from `relay loop` to propose a new candidate harness based on
             prior execution traces and scores. Read the filesystem first;
             form falsifiable hypotheses; produce ONE new agents/<name>.py
             file and register it in pending_eval.json.
---

# Meta-Harness Coding Agent Evolution

You are evolving the source code of a minimal coding agent. Your job is to
read the full history of prior candidate harnesses, identify a specific
failure pattern, and write ONE new candidate harness file that addresses it.

## What gets evolved

The harness is a single Python file in `agents/<name>.py` that subclasses
`CodingAgentHarness` from `relay_sdk`. You may override:

- `SYSTEM_PROMPT` — how the agent is instructed
- `MAX_TURNS` — how many turns before timeout
- `_build_initial_context` — what the agent sees at task start
- `_format_tool_result` — how tool outputs are shown
- `_call_llm` — model call mechanics
- `solve` — the agent loop itself

You may NOT override the four task tools (`read_file`, `write_file`,
`list_dir`, `run_bash`, `task_complete`) — those are the contract with the
evaluator.

## Hard rules (Anti-Overfitting)

1. **No task-specific knowledge.** Never reference specific tasks like
   "calculator.py" or "the typo bug" in your code or comments. Your
   improvements must generalize.
2. **No hard-coded fixes.** Don't write code that detects the eval tasks by
   name and special-cases them. The evaluator will reject candidates with
   string-leakage from task names into harness code.
3. **General principles only.** Frame every change as a hypothesis about
   *coding agents in general*, not "what would have worked on task 003."

## Hard rules (Anti-Parameter-Tuning)

1. **Mechanism, not constants.** If your only change is `MAX_TURNS = 30`
   instead of `MAX_TURNS = 20`, that is a parameter tweak, not an evolution.
   Reject it.
2. **Self-critique before writing.** Before writing the candidate file,
   verify in a comment block at the top:
   "STRUCTURAL CHANGE: this candidate differs from {parent} by {mechanism}.
    The mechanism is genuinely new, not a constant change."
3. **No combinatorial sweeps.** Don't propose 3 candidates that vary one
   constant. Propose 1 candidate that introduces a new mechanism.

## Workflow (mandatory order)

### Step 1 — Analyze (read the filesystem)

Read these files in this order:

1. `evolution_summary.jsonl` — every prior candidate, hypothesis, score.
2. `frontier_val.json` — current Pareto frontier (which candidates are
   non-dominated on accuracy vs. token-cost).
3. The 2-3 lowest-scoring candidates' `agents/<name>.py` source code AND
   their `traces/<task-id>-trial-<n>.jsonl` execution traces.
4. The current best candidate's `agents/<name>.py` and 2-3 traces.

Then form THREE falsifiable hypotheses about why the best candidate
fails on specific tasks. Write them in `/tmp/hypotheses-{iteration}.md`.

### Step 2 — Pick one hypothesis

From the three, pick the most likely to produce a >5% improvement.
Write a one-sentence justification in `/tmp/chosen-hypothesis-{iteration}.md`.

### Step 3 — Prototype (test the mechanism in isolation)

Write a small `/tmp/prototype-{iteration}.py` that exercises the new
mechanism on 1-2 trace examples WITHOUT the full harness. Verify the
mechanism does what you think it does before committing it to a candidate.

### Step 4 — Implement (write the candidate)

1. Copy the current best candidate as `agents/{descriptive-name}.py`.
2. Apply the targeted modification.
3. Add the self-critique comment block at the top.
4. Verify the file imports cleanly: `python -c "from agents.{name} import *"`.

### Step 5 — Register (write pending_eval.json)

Write to `pending_eval.json`:

```json
{
  "iteration": <N>,
  "candidates": [
    {
      "name": "<descriptive-name>",
      "import_path": "agents.<descriptive-name>:CodingAgentHarness",
      "parent": "<parent-candidate-name>",
      "hypothesis": "<one-sentence falsifiable claim>",
      "axis": "exploration | exploitation",
      "expected_score_delta": <float>
    }
  ]
}
```

## What you may NOT do

- Modify files outside `agents/`, `/tmp/`, and `pending_eval.json`
- Modify the eval tasks in `eval/`
- Modify any baseline file in `agents/baseline.py`
- Read the test set (`eval/holdout/`) — it is held out from the proposer
- Make API calls to anything other than the Anthropic API for prototyping
- Propose more than ONE candidate per iteration (we keep the demo loop tight)
```

That's the whole thing. ~150 lines of Markdown. **This is the meta-harness tool the user kept asking about.**

When `relay loop` invokes the proposer, this file gets concatenated with `domain_spec.md` (written once via `relay init`) and `proposer_prior.md` (general harness-engineering wisdom), and the whole bundle is `--append-system-prompt`-ed onto the Claude Code invocation.

### B.5.2 Why the structure is what it is

Every part of the skill maps to a specific lesson from the Stanford paper:

| Skill section | Why it's there (paper finding) |
|---|---|
| Anti-Overfitting rules | Paper section 4.1 — proposers will absolutely overfit to specific eval tasks if not blocked. Manual + regex audits found ~5% of candidates leaked task names without these rules. |
| Anti-Parameter-Tuning rules | Paper Table 3 ablation — "Scores Only" baseline beat "Scores + Summaries" because summaries hide that proposers were just changing constants. The mechanism-first rule prevents this collapse. |
| Step 1 (Analyze, read 5+ files) | Paper Table 8 — the proposer reads ~82 files per iteration in TB2. Skipping this step means the proposer is effectively memoryless; performance collapses. |
| Step 2 (pick one hypothesis) | Paper section 5.1 — proposers that proposed too many simultaneous changes had higher reject rates. One change per iteration → causal attribution. |
| Step 3 (prototype in /tmp/) | Paper section 5.2 — "fail-fast" prototyping prevented expensive eval cycles on broken candidates. ~30% time savings. |
| Step 4 (smoke test the import) | TB2 reference uses `extract-elf` task as smoke test. We use `import` check because text classification's smoke test is the same. |
| Step 5 (pending_eval.json contract) | This is the literal handoff schema between the proposer (NL) and evaluator (Python). Without it, evaluator can't dispatch. |

---

## B.6 Mapping Both Loops onto LangGraph State Machines

This is where our project's contribution lives. Stanford's reference is plain Python with shell scripts and signal handlers for interruption. We're going to express the same logic as two LangGraph `StateGraph`s, gaining: checkpointing, time-travel, persistence, durable execution, and parallel branches (per Appendix A).

### B.6.1 The OUTER state graph (meta-harness)

```python
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


class MetaHarnessState(TypedDict):
    run_id: str
    iteration: int
    budget_remaining: int
    candidates: list[Candidate]          # all candidates ever, append-only
    frontier: list[str]                  # names on the Pareto frontier
    best_candidate: str | None
    proposer_prior: str                  # editable via time-travel forks


# Each node is one of the four phases from B.2
async def propose(state: MetaHarnessState) -> dict:
    # invoke claude_wrapper-equivalent: spawn Claude API call with the SKILL.md
    # injected as system prompt; let the proposer read the filesystem at
    # ~/.relay/runs/{run_id}/ and write a new agents/<name>.py
    new_candidate = await invoke_proposer(
        run_dir=run_dir(state["run_id"]),
        skill=read_skill("meta-harness-coding-agent"),
        prior=state["proposer_prior"],
        iteration=state["iteration"],
    )
    return {"candidates": [*state["candidates"], new_candidate]}


async def validate(state: MetaHarnessState) -> dict:
    candidate = state["candidates"][-1]
    smoke_ok = await python_import_check(candidate.import_path)
    if not smoke_ok:
        candidate.status = "smoke_failed"
    return {"candidates": state["candidates"]}


async def benchmark(state: MetaHarnessState) -> dict:
    candidate = state["candidates"][-1]
    if candidate.status == "smoke_failed":
        return {}  # skip
    # run the inner loop (B.6.2 below) for each task × each trial
    eval_result = await run_eval(candidate, state["run_id"])
    candidate.scores = eval_result
    return {"candidates": state["candidates"]}


async def update_frontier(state: MetaHarnessState) -> dict:
    new_frontier = compute_pareto(state["candidates"], axes=["accuracy", "tokens"])
    new_best = max(state["candidates"], key=lambda c: c.scores.accuracy)
    return {
        "frontier": [c.name for c in new_frontier],
        "best_candidate": new_best.name,
        "iteration": state["iteration"] + 1,
        "budget_remaining": state["budget_remaining"] - 1,
    }


workflow = StateGraph(MetaHarnessState)
workflow.add_node("propose", propose)
workflow.add_node("validate", validate)
workflow.add_node("benchmark", benchmark)
workflow.add_node("update_frontier", update_frontier)

workflow.add_edge(START, "propose")
workflow.add_edge("propose", "validate")
workflow.add_edge("validate", "benchmark")
workflow.add_edge("benchmark", "update_frontier")
workflow.add_conditional_edges(
    "update_frontier",
    lambda s: "propose" if s["budget_remaining"] > 0 else END,
)

outer_graph = workflow.compile(
    checkpointer=AsyncPostgresSaver(...),
    interrupt_before=["benchmark"],   # optional: human review before expensive step
)
```

That's the outer loop. Every node transition writes a checkpoint. `get_state_history` gives us the candidate trajectory tree. `update_state` + `invoke(None, fork_config)` gives us the time-travel forking from Appendix A.

### B.6.2 The INNER state graph (the coding agent)

The inner loop runs *inside* the `benchmark` node above. This is what's being optimized. It's also a LangGraph state graph (this gives us streaming + interrupts even within a single task):

```python
class CodingAgentState(TypedDict):
    task: dict
    workspace_path: str
    messages: Annotated[list[Message], add_messages]
    turn_count: int
    final_files: dict[str, str] | None
    test_result: TestResult | None


async def call_model(state: CodingAgentState) -> dict:
    # the candidate harness's _call_llm method
    response = await harness._call_llm(state["messages"], TOOLS)
    return {"messages": [response]}


async def execute_tools(state: CodingAgentState) -> dict:
    last = state["messages"][-1]
    tool_calls = extract_tool_calls(last)
    results = []
    for tc in tool_calls:
        result = await execute_tool(
            tool_name=tc.name,
            tool_input=tc.input,
            workspace=state["workspace_path"],
        )
        # apply the candidate's _format_tool_result method
        formatted = harness._format_tool_result(result)
        results.append(formatted)
    return {"messages": results, "turn_count": state["turn_count"] + 1}


async def score_task(state: CodingAgentState) -> dict:
    # run pytest in the workspace, return pass/fail
    result = await run_pytest(state["workspace_path"], state["task"]["test_command"])
    return {"test_result": result, "final_files": snapshot_workspace(state["workspace_path"])}


def should_continue(state: CodingAgentState) -> str:
    last = state["messages"][-1]
    if has_tool_call(last, "task_complete"):
        return "score"
    if state["turn_count"] >= harness.MAX_TURNS:
        return "score"
    if has_tool_calls(last):
        return "tools"
    return "score"   # model returned no tool call — terminate


inner_workflow = StateGraph(CodingAgentState)
inner_workflow.add_node("call_model", call_model)
inner_workflow.add_node("tools", execute_tools)
inner_workflow.add_node("score", score_task)

inner_workflow.add_edge(START, "call_model")
inner_workflow.add_conditional_edges("call_model", should_continue, {
    "tools": "tools",
    "score": "score",
})
inner_workflow.add_edge("tools", "call_model")
inner_workflow.add_edge("score", END)

inner_graph = inner_workflow.compile(checkpointer=AsyncPostgresSaver(...))
```

Two state graphs, one Postgres checkpointer, one filesystem. The outer graph orchestrates; the inner graph executes. **The proposer reads inner-graph traces — checkpoints from the inner runs are exactly the diagnostic information the paper says is essential.**

### B.6.3 Why the two-graph design is the right fit

| Property | Why both graphs benefit |
|---|---|
| Checkpointing | Outer graph survives crashes mid-iteration; inner graph allows replay of any task run |
| Time-travel forking | Outer graph forks the meta-harness; inner graph forks within a single task to study failure modes |
| Streaming | Both graphs stream to the dashboard via SSE; user sees both layers grow in real time |
| Subgraphs (security) | Each candidate's inner graph can be compiled in isolation; a buggy candidate can crash without corrupting the outer state |
| Memory store (cross-run) | Outer graph writes "what worked across runs" to the cross-thread memory; new runs read it on first iteration |

This is how we earn the right to claim the project ships LangGraph primitives doing real work, not just decoration.

---

## B.7 What We Cut from the Paper

Honest list of simplifications we make for hackathon scope. Knowing these makes Q&A bulletproof.

| Paper feature | What we ship | Why |
|---|---|---|
| 89 TB2 tasks @ Opus 4.6 | 5 coding tasks @ Sonnet 4.6 | $500/iter → $0.50/iter |
| Harbor + Runloop sandboxes | Local Docker container per task | Zero infrastructure |
| Multi-agent harnesses | Single-file `agents/<n>.py` | Matches paper's actual scope (paper uses single-file too) |
| 20 iterations × 2 candidates | 5 iterations × 1 candidate | Demo runtime budget |
| Anthropic prompt caching for the harness | Skip (Sonnet is fast enough for 5 tasks) | Optimization, not core |
| Marker-based polling for terminal output | Skip — `subprocess.run` with timeout | Coding tasks don't need terminal multiplexing |
| Context summarization on overflow | Skip — small tasks won't overflow | Edge case |
| `image_read` tool for visual analysis | Skip — coding tasks are text-only | Out of scope |
| Self-critique mandatory before write | Keep | Critical anti-collapse rule |
| Anti-overfitting rules | Keep | Critical correctness rule |
| pending_eval.json contract | Keep | Required handoff |
| Pareto frontier on (accuracy, tokens) | Keep | Single Pareto frontier UI is photogenic |
| `--holdout` for test set | Keep | One-line CLI flag, real value |
| Cross-run memory store (LangGraph) | **Add (NEW vs paper)** | Our LangGraph contribution |
| Time-travel forks | **Add (NEW vs paper)** | Our LangGraph contribution |
| Parallel branches via `asyncio.gather` | **Add per Appendix A** | Our LangGraph contribution |

The features we keep are the ones the paper's section 5 ablations show actually matter. The features we cut are infrastructure-heavy or domain-specific to TB2.

---

## B.8 The Filesystem Layout, Concrete

Putting it all together, here's exactly what `~/.relay/runs/{run-id}/` looks like at iteration 4 of a demo run:

```
~/.relay/runs/run-2026-04-25-1430/
├── manifest.json                          # run config: budget, model, etc.
├── domain_spec.md                         # from `relay init`
├── proposer_prior.md                      # general harness-engineering rules
│
├── eval/                                  # the 5 frozen tasks (read-only)
│   ├── tasks/
│   │   ├── task-001-fix-typo/
│   │   ├── task-002-add-function/
│   │   ├── task-003-refactor/
│   │   ├── task-004-handle-error/
│   │   └── task-005-implement-spec/
│   ├── score.py
│   └── holdout/                           # held out from proposer
│
├── agents/                                # all candidate harnesses
│   ├── baseline.py                        # immutable starting point
│   ├── retry-on-test-fail.py             # iter 1 — current best (0.70)
│   ├── tighter-tool-hashing.py           # iter 2 — REJECTED (0.66)
│   ├── early-exit-on-auth.py             # iter 3 (0.74)
│   ├── more-specific-descriptions.py     # iter 4 — current best (0.80)
│   └── (pending) few-shot-tool-results.py # iter 5 — proposer is writing now
│
├── traces/                                # inner-loop execution traces
│   ├── baseline/
│   │   ├── task-001-trial-1.jsonl
│   │   ├── task-001-trial-2.jsonl
│   │   └── ...                            # 5 tasks × 5 trials = 25 files
│   ├── retry-on-test-fail/
│   │   └── ...
│   └── ...
│
├── proposer-sessions/                     # outer-loop proposer interactions
│   ├── iter-1/
│   │   ├── session.json                  # full Anthropic API session
│   │   ├── transcript.txt                # human-readable
│   │   └── system_prompt.txt             # exact prompt sent (incl SKILL.md)
│   ├── iter-2/...
│   └── iter-5/                            # currently being written
│
├── pending_eval.json                      # what to eval this iteration
├── frontier_val.json                      # current Pareto frontier
├── evolution_summary.jsonl                # append-only log of all candidates
└── checkpoint-graph.json                  # LangGraph thread tree (NEW)
```

This is **structurally identical to Stanford's reference repo's run output**, plus three additions of our own: `proposer-sessions/` instead of `experience/`, `eval/` mirroring the actual paper convention, and `checkpoint-graph.json` for time-travel.

A user familiar with Stanford's repo can navigate ours immediately. That's the drop-in compatibility we keep claiming.

---

## B.9 What Ships in 36 Hours

Concretely, the new pre-hackathon prep this appendix adds to the v7 plan:

### Pre-hackathon (Wednesday)

- [ ] Build the 5 eval tasks in `eval/tasks/`. Each task = workspace + task.json + test_*.py.
- [ ] Pre-evaluate the baseline harness across all 5 tasks × 5 trials. Establish baseline = 60-65%.
- [ ] Hand-tune two known-good candidates that score ~80% and ~85%. Save as fallbacks.
- [ ] Write the actual `meta-harness-coding-agent/SKILL.md` (~150 lines).
- [ ] Write `domain_spec.md` for the coding-agent domain.
- [ ] Write `proposer_prior.md` (general anti-overfitting rules).

### Hackathon Friday-Saturday — backend changes

- [ ] Implement `CodingAgentHarness` base class in `relay_sdk` (~150 lines).
- [ ] Implement the 4 task tools (`read_file`, `write_file`, `list_dir`, `run_bash`).
- [ ] Implement the inner LangGraph state machine (Section B.6.2).
- [ ] Implement the outer LangGraph state machine (Section B.6.1).
- [ ] Implement `propose_node` — calls Anthropic API directly with SKILL.md injected.
- [ ] Implement Pareto frontier computation.
- [ ] Implement `pending_eval.json` write/read.

### What's already in v7 — unchanged

- Cloud signup with Clerk
- Dashboard with state graph viz
- Time-travel UI
- Cross-run memory
- All tooling around presentation

---

## B.10 The Crisp One-Sentence Summary

**Stanford's Meta-Harness is two loops: an outer loop where Claude Code (guided by a SKILL.md skill) reads prior traces and rewrites the inner loop's source, and an inner loop where the rewritten code does the actual task. We're shipping both loops as LangGraph state machines, with a minimal coding agent as the inner loop and a SKILL.md as the meta-harness tool — runnable on any laptop in ~6 minutes for ~$2.50.**

**Three things deserve repeating:**

1. The **meta-harness tool** the user kept asking about is **a SKILL.md file** that gets `--append-system-prompt`-ed onto Claude Code. ~150 lines of Markdown. That's it.

2. Our **inner loop** is a **minimal coding agent** with 5 tools (read/write/list/bash/done) on a Docker-isolated workspace, scored by `pytest`. Single Python file per candidate.

3. Both loops as **LangGraph state machines** is what makes RELAY a *substrate* and not just a fork of the Stanford repo — checkpointing, time-travel, parallel branches, and cross-run memory are all primitives we get for free from LangGraph.

That's the project. Build the proxy. Ship the substrate. Watch the score climb.
