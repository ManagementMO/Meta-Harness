---
name: meta-harness-coding-agent
description: Evolve the coding-agent harness. Use this skill when invoked by `meta-harness loop` to propose a new candidate harness based on prior execution traces and scores. Read the filesystem first; form falsifiable hypotheses; produce ONE new agents/<name>.py file and register it in the run's pending_eval.json.
---

# Meta-Harness Coding Agent Evolution

You are evolving the source code of a 5-phase coding-agent harness. Your
job is to read the full history of prior candidate harnesses, identify a
specific failure pattern, and write ONE new candidate harness file that
addresses it.

## What gets evolved

The harness is a single Python file in `agents/<name>.py` that subclasses
`CodingAgentHarness` from `app.meta_harness.harness`. You may override
any of the **11 search-space methods** (Appendix C §C.9):

- `SYSTEM_PROMPT` — how the agent is instructed.
- `PLAN_PROMPT_TEMPLATE` — how planning is framed.
- `MAX_ACT_TURNS` — turn budget for the act phase (default 25).
- `MAX_VERIFY_RETRIES` — verify→act retry budget (default 3).
- `_build_initial_context(orient_summary)` — what the planner sees.
- `_format_tool_result(name, result)` — how tool outputs render.
- `_compose_act_prompt(plan)` — plan injection into act phase.
- `_call_llm(messages, tools)` — Anthropic API call mechanics.
- `should_loop_back_to_act(verify_result)` — retry decision logic.
- `_summarize_for_overflow(messages)` — context overflow strategy.
- (Structural) Override `build_inner_graph()` to reorder phases.

You may **NOT** override the 6 fixed inner-loop tools (`read_file`,
`apply_patch`, `write_file`, `run_bash`, `grep_search`, `task_complete`)
or the phase boundaries (`orient`, `plan`, `act`, `verify`, `submit`) —
those are the contract with the evaluator.

## Hard rules (Anti-Overfitting)

1. **No task-specific knowledge.** Never reference specific tasks like
   "calculator.py" or "the typo bug" in your code or comments. Your
   improvements must generalize.
2. **No hard-coded fixes.** Don't write code that detects the eval tasks
   by name and special-cases them. The evaluator will reject candidates
   with string-leakage from task names.
3. **General principles only.** Frame every change as a hypothesis about
   *coding agents in general*, not "what would have worked on task 003."

## Hard rules (Anti-Parameter-Tuning)

1. **Mechanism, not constants.** If your only change is `MAX_ACT_TURNS = 30`
   instead of `MAX_ACT_TURNS = 25`, that is a parameter tweak, not an
   evolution. Reject it.
2. **Self-critique before writing.** Before writing the candidate file,
   verify in a comment block at the top:
   ```
   # STRUCTURAL CHANGE: this candidate differs from {parent} by {mechanism}.
   # The mechanism is genuinely new, not a constant change.
   ```
3. **No combinatorial sweeps.** Don't propose 3 candidates that vary one
   constant. Propose 1 candidate that introduces a new mechanism.

## Workflow (mandatory order)

### Step 1 — Analyze (read the filesystem)

Read these files in this order:

1. `runs/{run_id}/evolution_summary.jsonl` — every prior candidate,
   hypothesis, score.
2. `runs/{run_id}/frontier_val.json` — current Pareto frontier (which
   candidates are non-dominated on accuracy × tokens).
3. The 2-3 lowest-scoring candidates' `agents/<name>.py` source code AND
   their `runs/{run_id}/candidates/<name>/traces/` execution traces.
4. The current best candidate's source + traces.

Then form THREE falsifiable hypotheses about why the best candidate
fails on specific tasks. Briefly note them in your reasoning.

### Step 2 — Pick one hypothesis

From the three, pick the most likely to produce a >5% improvement.

### Step 3 — Prototype (test the mechanism in isolation)

Write a small `/tmp/prototype-iter-{N}.py` that exercises the new
mechanism on 1–2 trace examples WITHOUT the full harness. Verify the
mechanism does what you think it does before committing it to a candidate.

### Step 4 — Implement (write the candidate)

1. Copy the current best candidate as `agents/<descriptive-snake-case-name>.py`.
2. Apply the targeted modification (override at most 2-3 of the 11
   search-space methods).
3. Add the self-critique comment block at the top.
4. Verify the file imports cleanly:
   ```bash
   uv run python -c "from agents.<name> import *; print('OK')"
   ```

### Step 5 — Register (write pending_eval.json)

Write to `runs/{run_id}/pending_eval.json`:

```json
{
  "iteration": <N>,
  "candidates": [
    {
      "name": "<descriptive-snake-case-name>",
      "import_path": "agents.<descriptive-snake-case-name>:<ClassName>",
      "parent": "<parent-candidate-name>",
      "hypothesis": "<one-sentence falsifiable claim>",
      "axis": "exploration | exploitation",
      "expected_score_delta": <float between -0.2 and +0.2>
    }
  ]
}
```

The class name in `import_path` must match the class you defined in
`agents/<name>.py` (a subclass of `CodingAgentHarness`).

## Interface contract

Your new candidate must:

```python
from app.meta_harness.harness import CodingAgentHarness


class YourCandidateName(CodingAgentHarness):
    """One-sentence hypothesis."""

    # ... overrides ...
```

The candidate will be loaded by the outer state machine via
`importlib.import_module("agents.<name>")` and instantiated with
`YourCandidateName()`. The `__init__` must accept no required args
(it inherits from `CodingAgentHarness.__init__` which reads the
Anthropic API key from the env).

## What you may NOT do

- Modify files outside `agents/` and `/tmp/` (and the run-specific
  `runs/{run_id}/pending_eval.json`).
- Modify the eval tasks in `eval/`.
- Modify any baseline file (`agents/baseline.py`).
- Read `eval/holdout/` — it is held out from the proposer.
- Propose more than ONE candidate per iteration (we keep the demo loop tight).
