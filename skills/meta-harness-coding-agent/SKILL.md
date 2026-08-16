---
name: meta-harness-coding-agent
description: Evolve the coding-agent harness from immutable run evidence. Read traces first, form falsifiable hypotheses, write one run-scoped proposal, and register its source_path and class_name in pending_eval.json.
---

# Meta-Harness Coding Agent Evolution

You are evolving the source code of a 5-phase coding-agent harness. Your
job is to read the full history of prior candidate harnesses, identify a
specific failure pattern, and write ONE new candidate harness file that
addresses it.

## What gets evolved

The proposal is one Python file under
`runs/{run_id}/proposals/iter-{N}/<name>.py`. After registration, the runtime
copies and hashes it into an immutable candidate bundle. It subclasses
`CodingAgentHarness` from `app.meta_harness.harness` and may override any of
the **11 search-space hooks**:

- `SYSTEM_PROMPT` — how the agent is instructed.
- `PLAN_PROMPT_TEMPLATE` — how planning is framed.
- `MAX_ACT_TURNS` — turn budget for the act phase (default 25).
- `MAX_VERIFY_RETRIES` — verify→act retry budget (default 3).
- `_build_initial_context(orient_summary)` — what the planner sees.
- `_format_tool_result(name, result)` — how tool outputs render.
- `_compose_act_prompt(plan)` — plan injection into act phase.
- `_call_llm(messages, tools, *, tool_choice=None)` — Anthropic API call mechanics.
- `should_loop_back_to_act(verify_result)` — retry decision logic.
- `_summarize_for_overflow(messages)` — context overflow strategy.
- (Structural) Override `build_inner_graph()` to reorder phases.

You may **NOT** override the 6 fixed inner-loop tools (`read_file`,
`apply_patch`, `write_file`, `run_bash`, `grep_search`, `task_complete`).
The default phases are evaluator-owned; structural changes must use only the
explicit `build_inner_graph()` hook and remain compatible with the state and
evaluator contracts.

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
4. **Keep the experiment model fixed.** Do not override `MODEL` or the
   telemetry-owning `call_llm()` boundary. `_call_llm()` remains evolvable,
   but provider usage must flow through `call_llm()`.

## Workflow (mandatory order)

### Step 1 — Analyze (read the filesystem)

Read these files in this order:

1. `runs/{run_id}/evolution_summary.jsonl` — every prior candidate,
   hypothesis, score.
2. `runs/{run_id}/frontier_val.json` — current Pareto frontier (which
   candidates are non-dominated on accuracy × tokens).
3. The 2-3 lowest-scoring candidates' immutable
   `runs/{run_id}/candidates/<candidate-id>/source/harness.py` source and traces.
4. The current best candidate manifest, source, raw traces, and task results.

Then form THREE falsifiable hypotheses about why the best candidate
fails on specific tasks. Briefly note them in your reasoning.

### Step 2 — Pick one hypothesis

From the three, pick the most likely to produce a >5% improvement.

### Step 3 — Prototype (test the mechanism in isolation)

Write a small `/tmp/prototype-iter-{N}.py` that exercises the new
mechanism on 1–2 trace examples WITHOUT the full harness. Verify the
mechanism does what you think it does before committing it to a candidate.

### Step 4 — Implement (write the candidate)

1. Copy the current best candidate to
   `runs/{run_id}/proposals/iter-{N}/<descriptive-snake-case-name>.py`.
2. Apply the targeted modification (override at most 2-3 of the 11
   search-space methods).
3. Add the self-critique comment block at the top.
4. Verify the file imports cleanly:
   ```bash
   uv run python runs/{run_id}/proposals/iter-{N}/<name>.py
   ```

### Step 5 — Register (write pending_eval.json)

Write to `runs/{run_id}/pending_eval.json`:

```json
{
  "iteration": <N>,
  "candidates": [
    {
      "name": "<descriptive-snake-case-name>",
      "source_path": "runs/{run_id}/proposals/iter-{N}/<name>.py",
      "class_name": "<ClassName>",
      "parent": "<parent-candidate-name>",
      "hypothesis": "<one-sentence falsifiable claim>",
      "axis": "exploration | exploitation",
      "expected_score_delta": <float between -0.2 and +0.2>
    }
  ]
}
```

`class_name` must match the class defined in `source_path`. The runtime copies
that source into a content-verified candidate directory before validation.

## Interface contract

Your new candidate must:

```python
from app.meta_harness.harness import CodingAgentHarness


class YourCandidateName(CodingAgentHarness):
    """One-sentence hypothesis."""

    # ... overrides ...
```

The candidate will be loaded from its immutable source hash under a unique
module identity and instantiated with `YourCandidateName()`. The `__init__`
must accept no required args
(it inherits from `CodingAgentHarness.__init__` which reads the
Anthropic API key from the env).

## What you may NOT do

- Modify files outside `/tmp/`, the current iteration's run-scoped proposal
  directory, and `runs/{run_id}/pending_eval.json`.
- Modify the eval tasks in `eval/`.
- Modify any baseline file (`agents/baseline.py`).
- Read `eval/holdout/` — it is held out from the proposer.
- Propose more than ONE candidate per iteration (we keep the demo loop tight).
