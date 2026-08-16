# Meta-Harness: Deep Research, Architecture, and Implementation Brief

> **Status:** repository-grounded research and roadmap brief
> **Snapshot date:** 2026-08-15
> **Audience:** project owners, research engineers, future contributors, and coding agents
> **Scope:** the local Meta-Harness checkout, its Stanford IRIS lineage, and the current public Prime Agent repository
> **Primary purpose:** provide a durable, evidence-backed basis for deciding what this project is, what it can already prove, what it cannot yet prove, and how to make it substantially more powerful without losing experimental validity.

This document is intentionally both analytical and operational. It explains the ideas behind the project, records the important implementation findings from the live checkout, compares the project with the Stanford reference design and Prime Agent, and turns those observations into an ordered implementation plan. It is not a claim that every future version of the repository will retain the same line numbers or behavior. The local links and verification results describe the checkout inspected on the snapshot date above.

## How to read and maintain this document

The document uses five evidence labels:

- **[LIVE]** means observed in the local checkout or produced by a local command during this review.
- **[PAPER]** means derived from the Stanford IRIS Meta-Harness paper or its reference repository.
- **[PRIME]** means derived from the public `PrimeIntellect-ai/prime-agent` repository and documentation inspected for this review.
- **[RECOMMENDATION]** means a design judgment or proposed next step. It is not an existing project fact.
- **[OPEN]** means a decision or verification item that should remain explicit rather than being silently assumed.

When this brief conflicts with an older project document, prefer the following order of authority:

1. Current source behavior and current tests.
2. A newly generated run manifest, evaluation artifact, or immutable candidate record.
3. Current repository configuration and command output.
4. The Stanford paper/reference implementation for research lineage.
5. Older local status, build-order, and handoff documents.

That ordering matters here because the repository contains useful historical documents whose completion claims no longer line up with the current code. A green test suite is evidence about the tests that ran; it is not by itself evidence that the outer research loop is scientifically valid, that real token accounting works, or that remote/production behavior is safe.

### Implementation update — 2026-08-16

The current working tree now implements the first architecture pass described by this brief: immutable run-scoped candidate manifests, source/runtime/dependency-lock hashes, explicit candidate IDs, baseline evaluation, population evaluation, measured/unknown/synthetic metric contracts, one evaluator for search and holdout, task runtime adapters, corrected retry feedback and structural hooks, inner checkpoint propagation, isolated holdout finalization, paired regression reports, append-only evidence events with content-addressed artifacts and torn-tail recovery, scoped/versioned memory fields, reversible refinement records, durable branch projections, research/autonomous modes, deterministic experiment bundles, repeated-run confidence summaries, and provenance/evidence surfaces in the CLI, API, and dashboard.

This is an implementation claim, not a self-improvement result. Current deterministic and Postgres-backed verification passes with `121 passed, 1 skipped`; the single skip is the credential-gated live Anthropic trial. Frontend lint/build and all 9 Playwright dashboard tests pass, including a live FastAPI/SSE provenance flow. A persistent two-iteration mock CLI run produces three immutable candidates, a candidate-ID frontier, a durable lifecycle/evidence ledger, and a synthetic-labeled report; holdout finalization correctly refuses that synthetic search.

Live provider benchmarking, a stronger security sandbox, an actual recursive/RLM backend, larger task distributions, held-out models, multiple measured seeds, and independent re-execution of exported experiment bundles still require separate validation or additional inputs. The roadmap below remains authoritative for those later gates.

## Contents

- [Executive conclusion](#executive-conclusion)
- [Decision summary for project owners](#decision-summary-for-project-owners)
- [Repository identity and current shape](#1-repository-identity-and-current-shape)
- [The Stanford IRIS lineage](#2-the-stanford-iris-lineage)
- [Deep read of the local implementation](#3-deep-read-of-the-local-implementation)
- [Findings and confidence blockers](#4-findings-what-is-strong-what-is-misleading-and-what-blocks-confidence)
- [Deep read of Prime Agent](#5-deep-read-of-prime-agent)
- [Adjacent research lessons](#58-adjacent-research-lessons)
- [Stanford versus Prime versus this project](#6-stanford-meta-harness-versus-prime-agent-versus-this-project)
- [Recommended target architecture](#7-recommended-target-architecture)
- [Prioritized implementation roadmap](#8-prioritized-implementation-roadmap)
- [Recommended first engineering slice](#9-recommended-first-engineering-slice)
- [Evaluation and ablation program](#10-evaluation-and-ablation-program)
- [Agent-facing implementation contract](#11-agent-facing-implementation-contract)
- [Open product and research decisions](#12-product-and-research-decisions-still-open)
- [Suggested success criteria](#14-suggested-success-criteria-for-a-finalized-meta-harness)
- [Source index and local evidence map](#15-source-index-and-local-evidence-map)

## Executive conclusion

Meta-Harness is a promising experimental substrate: it already has the shape of a two-level system in which an outer proposer changes a coding harness and an inner fixed harness attempts tasks. It has a public SDK, a backend orchestration layer, a dashboard, task fixtures, persistence hooks, branching concepts, a frontier module, memory storage, and a committed proposer skill. That is a useful foundation.

However, the current system should be described as an **early research/demo harness with substantial production-oriented scaffolding**, not yet as a validated self-improving agent platform. Several of the most important quantities used by the outer loop are currently placeholders or are disconnected from the actual execution path:

- provider token usage is now measured when exposed and unavailable cost is explicitly unknown, but the live provider path still needs an artifact-backed benchmark run;
- `mock_bench` is now synthetic throughout the schema and UI and remains useful only for plumbing;
- populations are evaluated by candidate ID and immutable manifest, but broader search-policy ablations still need real experiments;
- search and holdout now share one evaluator contract and write separate artifacts without feedback, but anti-leak guarantees remain limited by the trusted-local proposer profile;
- lint is explicitly unknown and file scope is measured; a configurable lint adapter remains future work;
- durable events and branch projections now survive registry loss, while active task ownership still requires a full multi-worker admission/reconciliation service for production;
- the current sandbox remains process/workspace isolation rather than a security boundary;
- the search set is still very small, and no generalized self-improvement claim is justified yet;
- the optional recursive/RLM backend, held-out-model studies, repeated seeds, and shareable external experiment bundles remain unimplemented or unvalidated.

The most important strategic recommendation is therefore:

> **Keep the Stanford-style outer experiment loop as the research core, but surround it with Prime-like durable execution, evidence-backed refinement, and explicit artifact/provenance contracts. Do not start by copying Prime’s entire daemon or recursive runtime. First make every candidate, metric, test, trace, branch, and refinement truthful, reproducible, and rollbackable.**

## Decision summary for project owners

### What to preserve

- The two-level distinction between an outer search process and an inner fixed task-solving harness.
- The ability for a proposer to inspect source, traces, scores, and prior artifacts rather than receiving only a compressed reward.
- The fixed task evaluation boundary and protected holdout concept.
- The small override surface exposed by `CodingAgentHarness`.
- The use of explicit candidates and a frontier instead of silently mutating the only copy of the harness.
- The paper’s core discipline: evolve the harness around a fixed model and evaluate actual task outcomes.

### What to fix before calling the system self-improving

1. Make candidate source and run outputs immutable and run-scoped.
2. Make evaluation use the same sandbox and task contract everywhere.
3. Record real usage, cost, wall time, turns, retries, tool calls, and failure categories.
4. Evaluate every proposed candidate, not only the last list element.
5. Separate search-set measurement from holdout/finalization measurement.
6. Replace synthetic benchmark values with explicit `mock`-labeled fixtures.
7. Replace process-local run/branch state with a durable event/ledger model or state the degraded mode loudly.
8. Add evidence-backed, versioned, reversible refinements for prompts, skills, memory, and subagent specifications.
9. Make the task runner configurable rather than hard-coded to Python and pytest.
10. Bring the docs, source, and test contracts back into alignment.

### What to borrow from Prime Agent

- Durable worker/session/child registries.
- A single execution path for interactive, scheduled, heartbeat, goal, and autonomous work.
- Persistent state that survives compaction and process restarts.
- A typed host boundary around recursive model calls.
- Explicit harness entries and refinement events with before/after snapshots, evidence, scope, and rollback.
- Append-only ledgers with bounded records, idempotent reconciliation, tombstones, and torn-tail repair.
- Clear separation between lifecycle isolation and security isolation.

### What not to borrow yet

- The full daemon/autonomous scheduling surface before the evaluation contract is trustworthy.
- Recursive child agents without a hard budget and usage attribution.
- The assumption that a persistent kernel or worker is a security sandbox.
- Implicit global mutable state for candidate source, memory, or branch metadata.
- Large generated context summaries that erase raw causal traces.

## 1. Repository identity and current shape

### 1.1 What this project is trying to be

[LIVE] The repository is a `uv` workspace with two Python packages:

- `sdk/` contains the public `meta_harness` package.
- `backend/` contains the internal orchestration package under `app.meta_harness`.

The project also includes:

- `agents/` for the committed baseline harness;
- `eval/tasks/` for frozen search and holdout task workspaces;
- `frontend/dashboard/` for an operational UI;
- `graphify-out/` for generated AST/semantic graph material;
- `docs/` for historical architecture, build, status, and handoff records;
- `skills/meta-harness-coding-agent/` for the proposer’s operating instructions.

The clean conceptual model is:

```text
fixed model + coding task
          │
          ▼
   inner CodingAgentHarness
   orient → plan → act → verify → submit
          │
          ▼
 task result, trace, diff, usage, failure evidence
          │
          ▼
       outer proposer
       inspect → hypothesize → edit harness → candidate
          │
          ▼
   benchmark candidate population
   update archive/frontier → choose next search state
```

That conceptual model is sound. The key work is making each arrow a real, typed, durable contract rather than a mixture of state dictionaries, root-level files, synthetic metrics, and process-local registries.

### 1.2 Source map

| Area | Live location | Role | Current assessment |
|---|---|---|---|
| Public SDK | [`sdk/meta_harness/`](../sdk/meta_harness/) | `wrap_graph`, tracing, run metadata | Thin but appropriately separated from backend internals |
| Outer loop | [`backend/app/meta_harness/outer.py`](../backend/app/meta_harness/outer.py) | Baseline, propose, validate, benchmark populations, update frontier | Candidate-ID and immutable-artifact path implemented; live search-policy ablations remain |
| Inner harness | [`backend/app/meta_harness/inner.py`](../backend/app/meta_harness/inner.py) | Orient, plan, act, verify, submit | Runtime adapters, telemetry, retry feedback, structural hook, and checkpoint propagation implemented |
| Harness base class | [`backend/app/meta_harness/harness.py`](../backend/app/meta_harness/harness.py) | Prompt and tool override points | Good experimental seam; context and model defaults need explicit contracts |
| Tools | [`backend/app/meta_harness/tools.py`](../backend/app/meta_harness/tools.py) | Read, search, patch, shell, file operations | Patch validation is a good start; shell and file provenance require stronger task-scoped policy |
| Sandbox | [`backend/app/meta_harness/sandbox.py`](../backend/app/meta_harness/sandbox.py) | Copy workspace and apply process limits | Process isolation only; not a security sandbox; shared by tool execution and verification |
| Proposer | [`backend/app/meta_harness/proposer.py`](../backend/app/meta_harness/proposer.py) | Mock or Claude CLI proposer | Writes run-scoped proposals that are materialized immutably; trusted-local broad permissions and access auditing remain |
| Persistence | [`backend/app/meta_harness/persistence.py`](../backend/app/meta_harness/persistence.py) | Postgres checkpoint/store setup | Valuable path, but fallback and deployment mode must be explicit |
| Memory | [`backend/app/meta_harness/memory.py`](../backend/app/meta_harness/memory.py) | Scoped learned patterns in Postgres store | Version, scope, confidence, candidate evidence, and evidence-ranked retrieval implemented; live ablation remains |
| Branches | [`backend/app/meta_harness/branches.py`](../backend/app/meta_harness/branches.py) | Fork a checkpoint into an isolated execution directory | Active tasks remain process-owned; metadata, lineage, lifecycle, and terminal state are durably projected |
| API | [`backend/app/api/`](../backend/app/api/) | Run, artifact, evidence, finalization, branch, memory, and refinement endpoints | Provenance surfaces implemented; backend remains unauthenticated under the trusted-local profile |
| Frontend | [`frontend/dashboard/`](../frontend/dashboard/) | Run graph, candidate, evidence, and review UI | Synthetic/mode/durability/security labels and evidence panel implemented; live UX validation remains |
| Evaluation | [`eval/`](../eval/) | Search/holdout fixtures plus shared runtime/evaluator adapters | Per-attempt evidence and aggregate metrics implemented; task set remains too small for generalization claims |
| Proposer skill | [`skills/meta-harness-coding-agent/SKILL.md`](../skills/meta-harness-coding-agent/SKILL.md) | Agent operating contract | Strong research discipline; implementation must enforce its filesystem and holdout constraints |
| Baseline | [`agents/baseline.py`](../agents/baseline.py) | Committed seed harness | Materialized, hashed, and evaluated through the same candidate/evaluator contract before search |

### 1.3 Current verification snapshot

[LIVE] The local repository was checked on 2026-08-15. At the time of review:

- Git status was clean before this document was added.
- `HEAD` was `5ac5d90`, aligned with `origin/main`.
- Backend verification from `backend/` passed:

```text
uv run pytest tests -q
73 passed, 21 skipped in 3.49s
```

- Frontend verification passed:

```text
npm run lint && npm run build
```

- The documented Postgres service was started temporarily for the deterministic outer-loop smoke command and the command completed with two mock iterations, two candidates, a frontier, and `"persistent": true`:

```text
uv run meta-harness loop --proposer mock --mock-bench --budget 2 --fresh
```

- The frontend build emitted warnings about Next inferring `/Users/mo/package-lock.json` as the workspace root and about the deprecated `middleware` convention. Those warnings do not invalidate the build, but they should be resolved before treating frontend deployment behavior as clean.
- The skipped backend tests include live Anthropic and/or external-infrastructure paths. No claim is made here that a real proposer run, a real inner evaluation against all tasks, or a production deployment was executed during this review. The Postgres-backed smoke run used the mock proposer/benchmark path only.

The repository therefore has a healthy deterministic test baseline, but the research-critical path still needs live, artifact-backed validation.

## 2. The Stanford IRIS lineage

### 2.1 Primary references

- [Stanford IRIS Meta-Harness paper, arXiv HTML](https://arxiv.org/html/2603.28052v1)
- [Stanford IRIS Meta-Harness abstract](https://arxiv.org/abs/2603.28052)
- [Meta-Harness project page](https://yoonholee.com/meta-harness/)
- [Stanford reference repository](https://github.com/stanford-iris-lab/meta-harness)

[PAPER] The Stanford design is not simply “an agent that edits its own prompt.” It is a search process over a harness around a fixed model. The proposer can inspect prior source, scores, and execution traces, then write a new harness candidate. The candidate is evaluated on tasks, and the outer process keeps searching. The paper’s central argument is that a scalar reward or short summary loses the information needed to assign credit to the harness’s actual behavioral choices.

The paper’s mathematical framing can be summarized as:

```text
fixed model M
task distribution X
harness H
rollout trace τ ~ M(H, x)
reward r(τ, x)

search for H that maximizes expected reward,
while tracking resource objectives such as tokens/cost.
```

This framing is important for Meta-Harness because it answers a foundational question: the object being improved is the **harness**, not the underlying model weights. A candidate may change prompts, tools, control flow, verification, context assembly, memory use, or other harness-level behavior while the selected model remains fixed for a given experiment.

### 2.2 What the paper says is unusually important

[PAPER] The strongest research lessons are:

1. **Raw traces carry causal signal.** The paper reports that a proposer with raw traces substantially outperformed versions receiving only scores or a summary. A summary can remove the exact failed action, misleading observation, tool result, or recovery opportunity that explains why a rollout failed.
2. **The outer loop can remain minimal.** The Stanford system intentionally gives the proposer filesystem access to prior experience instead of imposing a large fixed archive, planner, or persistent memory subsystem.
3. **Search can improve both quality and efficiency.** The objective is not only “pass more tasks”; it can include tokens, cost, latency, or other resource measures, which naturally creates a Pareto frontier.
4. **Validation and final evaluation are separate.** Search needs a feedback signal, but final test performance should be measured with a separately controlled procedure to avoid conflating discovery and reporting.
5. **The task distribution and holdout design are part of the algorithm.** A candidate that wins only on a small, repeatedly inspected search set is not evidence of general self-improvement.
6. **A skill or operating contract matters.** The proposer needs enough freedom to diagnose, but should be constrained on safety, artifact boundaries, and objectives.
7. **Small additive discoveries can matter.** The paper’s coding example describes environment bootstrap information as a useful harness improvement because it removes repeated exploration turns without changing the core agent’s problem-solving model.

The paper reports notable improvements in text classification, math, and coding, including gains over comparison systems and hand-engineered baselines. Those numbers are evidence about the Stanford experimental setup, not a forecast for the current local implementation. Reproducing the result requires matching task construction, candidate protocol, models, sandbox, trace collection, search budget, and finalization procedure.

### 2.3 The Stanford reference loop and what it reveals

The reference repository contains concrete examples that are more useful than the high-level paper alone:

- [TerminalBench 2 reference harness](https://github.com/stanford-iris-lab/meta-harness/blob/main/reference_examples/terminal_bench_2/meta_harness.py)
- [TerminalBench README](https://github.com/stanford-iris-lab/meta-harness/blob/main/reference_examples/terminal_bench_2/README.md)
- [TerminalBench setup notes](https://github.com/stanford-iris-lab/meta-harness/blob/main/reference_examples/terminal_bench_2/SETUP.md)
- [Text classification reference harness](https://github.com/stanford-iris-lab/meta-harness/blob/main/reference_examples/text_classification/meta_harness.py)

[PAPER] The reference coding loop makes several distinctions that Meta-Harness should preserve or make more explicit:

- The proposer can use an `Agent`-style subagent tool for delegated analysis; the current local proposer tool allowlist does not include that capability.
- Candidate generation is separate from validation and finalization.
- The coding tasks use a remote sandbox and collect per-task reward, metrics, token usage, cost, turns, and API calls rather than only a binary test result.
- The reference workflow has a baseline phase, an evolving search phase, a Pareto/frontier phase, and a final test phase.
- Search trials and run names isolate logs/results sufficiently to compare experiments.
- The final test set is not silently fed back into the proposer during search.
- The system records enough information to compare candidates and diagnose regressions.

The Stanford reference repository also cautions readers that release code should not automatically be treated as a production-hardened system. This is a useful reminder for the local project: research code can be conceptually correct while still requiring extensive work around lifecycle, security, reproducibility, and deployment boundaries.

### 2.4 Stanford principles that should remain non-negotiable

The following should be treated as research invariants for a “paper-faithful” Meta-Harness mode:

- The model under evaluation is identified and fixed for the experiment.
- The candidate source is immutable once evaluated.
- The proposer cannot access holdout task content or final test results.
- Every score has a task, candidate, model, evaluator, and run identity.
- Traces and raw tool results remain available even when summaries are generated.
- Evaluation happens outside the proposer’s own ability to rewrite the evaluator.
- Search-time metrics and final test metrics are distinct artifacts.
- Candidate improvements are compared against an explicit baseline and not merely against a moving last candidate.
- Resource objectives use measured usage, not placeholders.

These invariants are compatible with a more durable and capable runtime; they are not limitations that Prime-style features require us to abandon.

## 3. Deep read of the local implementation

### 3.1 Outer state machine

[LIVE] The outer loop in [`outer.py`](../backend/app/meta_harness/outer.py) is the project’s experimental control plane. Its broad sequence is:

1. Initialize or resume an outer run.
2. Propose a new candidate, either with a mock proposer or the real Claude CLI proposer.
3. Validate the candidate’s shape and source location.
4. Benchmark the candidate on the evaluation set.
5. Update the frontier/best-candidate state.
6. Optionally synthesize or persist a next-step summary.
7. Continue until the budget is exhausted or the run is stopped.

The outer graph is a good home for research logic because it can remain stable while the inner harness changes. It also creates a natural place for candidate archives, search policies, budget accounting, and ablations.

The original review found contract-level weaknesses rather than a conceptual failure. The implementation now evaluates an explicit baseline, materializes every proposal as a `CandidateArtifact`, passes active candidate IDs between nodes, evaluates complete populations, preserves all archive records, and records `best_accuracy` or deterministic `pareto_sample` as the parent policy. Unknown resource measurements remain unknown, synthetic fixtures remain synthetic, and the frontier records whether its token objective is active.

Candidate/evaluation/evidence/refinement contracts are Pydantic-validated and serialized as dictionaries only at the LangGraph checkpoint boundary. The remaining outer-loop work is empirical: run live multi-policy and population ablations, validate provider usage at scale, and add distributed admission if multiple backend workers must coordinate one run.

### 3.2 Inner coding harness

[LIVE] The inner implementation in [`inner.py`](../backend/app/meta_harness/inner.py) is a LangGraph-style sequence:

```text
orient → plan → act → verify → submit
```

The base harness in [`harness.py`](../backend/app/meta_harness/harness.py) exposes eleven override points covering system instructions, planning, verification, tool behavior, and related control decisions. This is a strong fit for meta-harness research: candidates can change meaningful behavior without rewriting the entire orchestration engine.

The current inner harness has several useful properties:

- bounded act turns (`MAX_ACT_TURNS = 25`);
- bounded verification retries (`MAX_VERIFY_RETRIES = 3`);
- a configured inner model via `META_HARNESS_INNER_MODEL`;
- explicit plan, act, verify, and submit phases;
- trace accumulation and file snapshots;
- structured tool calls instead of unconstrained raw model output.

The main limitations are:

#### Runtime adapters

Task specifications now declare a runtime adapter. `python-pytest-v1` preserves the original orientation and pytest behavior, while `generic-command-v1` establishes the extension boundary for other ecosystems. The shared adapter owns orientation and verification for standalone scoring, inner retries, search evaluation, and holdout finalization. Adding JavaScript, Rust, or remote-sandbox support no longer requires changing the graph topology.

#### Shared verification and evaluation policy

Every task workspace is copied through `sandbox_for(...)`; verification and tool shell calls use the shared executor. `EvaluationPolicy` records task visibility, sandbox profile, runtime adapter, execution backend, fixed model, trials, workers, memory/recursion flags, and synthetic status. The evaluator records manifest/task hashes, command, exit code, timeout, artifacts, usage, retry count, and failure category. Provider-reported model drift aborts research evaluation rather than becoming a low score.

The remaining sandbox work is OS enforcement: network mode, binary/environment allowlists, stronger CPU/memory behavior on Darwin/Windows, and container/VM isolation for untrusted code.

#### Lint and scope status

Lint is now explicitly `unknown`, never hard-coded passing. File scope is measured by before/after hashes, compared with `expected_files_changed`, and persisted as changed/out-of-plan evidence. A future lint adapter can turn lint from unknown into measured without changing `TaskResult`.

#### Submission and evaluator metrics

The inner `submit` score remains binary for the current fixtures. The evaluator preserves that field while adding per-task aggregates, paired regressions, structured candidate/model/evaluator/policy/sandbox/timeout/verification failures, measured or unknown usage, tool/model-call counts, turns, retries, wall time, and immutable artifact references.

### 3.3 Tools and patch semantics

[LIVE] [`tools.py`](../backend/app/meta_harness/tools.py) exposes six core tools, including read/search, patch, file operations, and shell execution. The patch path performs a useful `git apply --check`-style validation and emits a context echo. Traversal protection also exists.

This is a good foundation for a controlled coding harness. The next step is to make tool calls first-class evidence:

```text
ToolCall {
  call_id,
  candidate_id,
  task_id,
  attempt_id,
  tool_name,
  normalized_arguments,
  started_at,
  ended_at,
  exit_code,
  stdout_ref,
  stderr_ref,
  files_read,
  files_written,
  policy_decision
}
```

Without these fields, a future proposer receives a trace but cannot reliably answer questions such as “did the agent fail because the tool was denied, because the command timed out, or because the model misread the result?”

### 3.4 Sandbox and security boundary

[LIVE] [`sandbox.py`](../backend/app/meta_harness/sandbox.py) creates a temporary task directory, copies the workspace, and applies process limits where supported. It is best described as **process isolation and workspace copying**, not as a complete security sandbox:

- there is no Docker or VM boundary;
- network restriction is not enforced by the current wrapper;
- there is no binary allowlist;
- shell commands are still run through a shell;
- Darwin skips some address-space limits;
- the inner verifier previously bypassed `run_in_sandbox(...)`; it now uses that shared executor, but the overall sandbox remains process/workspace isolation only.

This distinction should appear in code, docs, CLI help, and UI labels. Prime Agent makes the same distinction explicitly: workers and kernels provide lifecycle/failure containment, but not a security boundary. That is an important shared lesson.

The real proposer also runs the Claude CLI with a broad tool allowlist including `Edit`, `Write`, and `Bash`, plus `--dangerously-skip-permissions`. That may be acceptable for a deliberately trusted local research machine, but it should be an explicit execution profile, not an unnoticed default in a service that could receive untrusted tasks.

### 3.5 Proposer and candidate source lifecycle

[LIVE] [`proposer.py`](../backend/app/meta_harness/proposer.py) supports a mock proposer and a real Claude CLI proposer. The real proposer records useful prompt/event/token/cost logs and is constrained by an operating prompt. It does not include the `Agent` subagent tool used in the Stanford reference loop.

The source lifecycle now uses two explicit stages:

1. The proposer writes only to `runs/{run_id}/proposals/iter-{N}/` and registers `source_path` plus `class_name`.
2. The runtime copies those bytes into `runs/{run_id}/candidates/{candidate_id}/source/harness.py`, records a manifest and SHA-256 identity, and verifies the hash before every load.

The baseline follows the same materialization and evaluation path. The API diff and manifest endpoints resolve immutable candidate IDs rather than reading root-global generated modules. Branches write to their own execution directories, eliminating the previous shared `pending_eval.json`, candidate-name, frontier, and trace collisions.

The authentication policy is now explicit and aligned: the Claude child inherits the configured authentication environment, while session logs record the authorization profile. Research mode audits proposer tool inputs for holdout access and rejects detected violations. Because the proposer still runs as a trusted local process with broad host permissions, that audit is not equivalent to OS-enforced holdout or security isolation.

### 3.6 Persistence, runs, and branches

[LIVE] The project uses Postgres checkpoint/store components when available and explicitly labels its in-memory fallback as degraded. Active `asyncio.Task` ownership remains process-local, but run, candidate, task-attempt, model-call, tool-call, verification, frontier, refinement, and lifecycle evidence is appended to a bounded JSONL ledger. Branch metadata, lineage, execution directory, status, and lifecycle are durably projected and can be reloaded after the in-process registry is cleared.

The ledger validates transitions, uses append writes plus `fsync`, stores large payloads as content-addressed artifacts, and can repair an invalid torn tail. Branch files and events provide enough evidence to distinguish completed, failed, canceled, and abandoned work. Search and branch artifacts no longer share mutable candidate or frontier paths.

This is still not a complete distributed worker system: two backend instances do not yet have a shared admission lease, active-task ownership protocol, or automatic dead-worker election. The remaining Phase 3 work is therefore multi-worker admission/reconciliation rather than merely adding fields to checkpoints.

### 3.7 Memory and frontier

[LIVE] [`memory.py`](../backend/app/meta_harness/memory.py) stores learned patterns with schema version, scope, confidence, task family, mechanism axis, score delta, evidence run IDs, evidence candidate IDs, outcome, and timestamps. Retrieval can filter by scope/task family and ranks confidence, evidence count, outcome delta, and recency. Research mode disables global-memory injection; autonomous mode requires an explicit opt-in.

[`refinements.py`](../backend/app/meta_harness/refinements.py) represents prompt, memory, skill, subagent, control-flow, and tool-interface changes as evidence-backed records with before/after hashes and immutable artifacts. Apply, reject, and rollback are explicit ledger events. Research mode permits attempt/run-local application but rejects project/global mutation.

Semantic retrieval and empirical memory ablations remain future work. [`frontier.py`](../backend/app/meta_harness/frontier.py) now treats unknown tokens as unknown rather than zero, records active objective status, and separates archive records, frontier membership, and the configured best-parent policy. Its resource dimension becomes scientifically useful only after a live usage-bearing benchmark validates provider telemetry end to end.

### 3.8 Evaluation set and proposer skill

[LIVE] The search set currently contains five tasks:

- `task-001-fix-typo`
- `task-002-add-function`
- `task-003-refactor`
- `task-004-handle-error`
- `task-005-implement-spec`

The holdout contains two tasks:

- `task-006-fix-recursion`
- `task-007-implement-stack`

The scorer in [`eval/score.py`](../eval/score.py) copies a pristine task workspace to a temporary directory and runs its configured test command. It returns a binary result. This is good for protecting pristine fixtures and preventing the evaluator from accidentally modifying the source task, but a five-task search set cannot support strong claims about generalized self-improvement.

The proposer skill in [`skills/meta-harness-coding-agent/SKILL.md`](../skills/meta-harness-coding-agent/SKILL.md) contains several excellent research rules:

- inspect prior summaries, frontier state, lower-performing candidates, traces, and the best candidate;
- form multiple hypotheses before editing;
- prototype and test the theory;
- write one candidate per iteration;
- do not use task-specific knowledge;
- do not make parameter-only changes;
- restrict output to the intended candidate and pending evaluation artifacts;
- do not access holdout tasks during search.

These rules should be turned into executable checks wherever possible. A skill is guidance; a run-scoped filesystem policy and evaluator boundary are enforcement.

## 4. Findings: what is strong, what is misleading, and what blocks confidence

### 4.1 Strengths worth building on

1. **The project has the correct conceptual decomposition.** The outer and inner loops are separate, and the harness is represented as an evolvable object.
2. **The override surface is concrete.** Eleven hooks are easier to mutate, diff, test, and attribute than an unstructured monolithic prompt.
3. **The repository has actual frozen tasks.** Even though the set is small, it gives the project a reproducible starting point.
4. **The project understands traces and memory are first-class.** The source includes trace APIs, run artifacts, Postgres storage, and memory concepts.
5. **Branching is already part of the product vocabulary.** That makes population search, comparisons, and counterfactuals easier to introduce.
6. **The UI exposes the graph and artifacts.** This can become an observability surface rather than only a demo screen.
7. **The test suite is deterministic and currently healthy.** This gives a safe base for contract hardening.
8. **The project has already documented interfaces and a build order.** Those documents can be reconciled rather than starting from zero.

### 4.2 P0 blockers to research truth

| Priority | Finding | Why it matters | Minimum correction |
|---|---|---|---|
| P0 | Real benchmark token/cost values are zero | A resource frontier and efficiency claim are false | Capture provider usage from every inner/model call; fail or label when unavailable |
| P0 | Mock benchmark synthesizes scores | Mock improvement can be mistaken for agent improvement | Put mock metrics under an explicit `synthetic=true` schema and exclude them from research reports |
| P0 | Verifier had bypassed the shared sandbox execution policy | The copied workspace was present, but resource/policy behavior diverged between tool commands and verification | Route verification through `run_in_sandbox(...)` and then consolidate both paths behind one evaluator policy |
| P0 | Candidate source is root-global | Runs and branches can collide; provenance is ambiguous | Materialize immutable candidate bundles under run/candidate IDs |
| P0 | Lint/scope fields are hard-coded | Reported dimensions look real but are not measured | Implement them or remove them from research metrics |
| P0 | Search/holdout boundary is not a first-class finalized artifact | Holdout leakage and optimistic reporting become easy | Separate search evaluator from finalizer and enforce task visibility |

### 4.3 P1 blockers to scalable experimentation

| Priority | Finding | Why it matters | Minimum correction |
|---|---|---|---|
| P1 | Several nodes select the last candidate by list position | Multi-candidate runs can evaluate the wrong artifact | Pass explicit candidate IDs and validate all intended candidates |
| P1 | Only strict accuracy improvement promotes the best candidate | Cost/latency improvements can be discarded | Use policy-driven archive/frontier promotion |
| P1 | Runtime state types and actual dictionaries diverge | Agents and maintainers cannot safely reason from types | Introduce Pydantic/dataclass contracts and serialize them |
| P1 | Python/pytest assumptions are embedded in orientation | The harness cannot generalize beyond the first fixture family | Introduce task runtime/evaluator adapters |
| P1 | Memory retrieval is recency-first | Helpful patterns can be missed; stale patterns can dominate | Rank by evidence, task fit, confidence, recency, and outcome |
| P1 | Truncation keeps a small head and tail | Causal middle events can disappear | Preserve raw trace references and generate queryable indexes |
| P1 | Run/branch lifecycle is process-local | Restart and multi-worker behavior are unreliable | Add a durable run/attempt/worker ledger |
| P1 | Auth/environment documentation and tests disagree | A future security change may be applied incorrectly | Choose one auth policy and encode it in a contract test |
| P1 | Docs describe historical completion states | Agents can implement against stale assumptions | Add snapshot dates and reconcile status docs |

**2026-08-16 status:** the P0 candidate, mock-labeling, shared-evaluator, verifier, scope, and finalization contracts above are implemented. Provider usage is captured when exposed and unknown otherwise; a live benchmark is still required to validate it. The P1 candidate-ID, population, policy, typed-contract, runtime-adapter, evidence-retention, memory-ranking, lifecycle-ledger, and auth-documentation corrections are also implemented at the local single-process layer. Distributed worker admission, semantic retrieval, real ablations, and historical-document cleanup remain open.

### 4.4 The central architectural diagnosis

At the original snapshot, the project had a **good experimental control graph but a weak artifact/evidence substrate**. The 2026-08-16 implementation pass replaces mutable candidate files, list-position selection, placeholder metrics, and summary-only evidence with explicit contracts and durable artifacts. The remaining weakness is operational validation: live models, stronger isolation, distributed ownership, and broader experiments have not yet proved those contracts under production-like load.

Adding more agent intelligence remains premature until those gates pass. A more capable proposer must not outpace the system’s ability to answer:

- Which exact source was evaluated?
- Which model and prompt version produced the trace?
- Which task workspace and environment were used?
- Were the tests run inside the intended sandbox?
- Which candidate actually caused the score change?
- Did the candidate improve average performance or just one task?
- Did it spend more tokens or invoke more children?
- Can the run be resumed after a crash?
- Can the refinement be rolled back?
- Did a branch inherit only its parent state or also unrelated global files?

Those are not secondary product questions. They are the conditions under which “self-improvement” becomes a falsifiable engineering claim.

## 5. Deep read of Prime Agent

### 5.1 Primary Prime references

- [Prime Agent repository](https://github.com/PrimeIntellect-ai/prime-agent)
- [Prime Agent README](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/README.md)
- [Prime architecture overview](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/architecture.md)
- [RLM documentation](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/rlm.md)
- [RLM runtime design](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/rlm-runtime.md)
- [Long-running agents](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/long-running-agents.md)
- [Refinement implementation](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/src/core/refinement/refinement.ts)
- [RLM ledger implementation](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/src/modes/daemon/rlm-ledger.ts)
- [RLM ledger tests](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/test/rlm-ledger.test.ts)
- [RLM Python runtime shim](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/prime-agent-runtime/src/rlm/__init__.py)

[PRIME] Prime describes itself as a self-improving RLM agent for coding workflows and long-running autonomous tasks. Its important contribution is not one magic prompt. It is the combination of:

1. a persistent programmatic control environment;
2. explicit recursive child-agent handles;
3. durable daemon/session/worker lifecycle;
4. compaction-resistant state and artifacts;
5. a “continual harness” that can refine prompts, memories, skills, and reusable subagent specifications;
6. a strong distinction between lifecycle isolation and security isolation.

Prime is therefore complementary to Stanford Meta-Harness rather than a direct replacement for it. Stanford primarily studies search over harnesses using outcome/traces. Prime primarily builds a durable runtime in which an agent can operate, delegate, remember, and refine itself over time.

### 5.2 Prime’s RLM abstraction

[PRIME] Prime’s RLM model gives the agent a persistent Python/IPython control environment. The model can write code that calls an `rlm(...)` handle, admits child work, stores intermediate state, reads files, and coordinates multiple calls. The child answer is not implicitly dumped into the parent context; it is delivered through an explicit result/message path or artifact reference.

The useful design properties are:

- **state survives turns and compaction;**
- **child work is asynchronous and explicit;**
- **parent and child identities are durable;**
- **child usage can be attributed to the parent;**
- **the runtime, not model-generated Python, owns provider calls and lifecycle;**
- **the same execution path can support interactive messages, heartbeats, goals, schedules, and autonomous continuations.**

This addresses a weakness that a purely linear LangGraph loop will eventually encounter: long-running work needs a control plane that can pause, resume, inspect, schedule, cancel, and reconcile work without assuming one uninterrupted request.

It is important not to confuse RLM with the Stanford outer proposer. In the Stanford design, the proposer edits the harness across evaluations. In Prime, RLM is primarily the execution/control environment available to an agent during a task or long-running session. A future Meta-Harness could evaluate an RLM-backed harness, but the two layers should remain analytically distinct.

### 5.3 Prime’s runtime boundaries

[PRIME] Prime separates:

```text
terminal/UI
    ↓
AgentConnection
    ↓
daemon supervisor / worker
    ↓
AgentSession
    ↓
provider calls, queues, tools, compaction, goals, child registry
    ↓
IPython/RLM host bridge and persisted artifacts
```

The architecture is valuable because it assigns ownership clearly:

- the daemon owns process/session coordination;
- the worker owns a root session tree, scheduler, root kernel, and children;
- the session owns provider calls, prompts, queues, transcript, compaction, and goals;
- the typed host bridge owns operations the Python control plane is allowed to request;
- artifacts and JSONL state provide recovery material.

Meta-Harness currently mixes some of these responsibilities inside graph nodes, API background tasks, process-local dictionaries, and filesystem helpers. The project does not need Prime’s full TypeScript process model, but it should adopt the ownership principle.

### 5.4 Prime’s continual harness and refinement model

[PRIME] Prime’s refinement design is particularly relevant to Meta-Harness. A harness can contain entries of kinds such as:

- `prompt`;
- `memory`;
- `skill`;
- `subagent`.

Entries carry stable identity, title/content/path, local/global scope, reference/arguments, metadata, timestamps, and version. A refinement event records the trigger, proposed changes, evidence, outcome, and date. Applying a refinement records before/after state, paths, rollback information, scope, and applied edits. The implementation uses atomic save patterns, history, merge/conflict handling, and rollback.

This is a much more disciplined form of “the agent improves itself” than overwriting a prompt file. It answers:

- What changed?
- Why did it change?
- What evidence supported it?
- Was the change local to one project or global?
- Which version was active for a run?
- Can it be reversed?
- Did the change actually improve outcomes after application?

Meta-Harness should borrow this event model even if its actual candidate source remains a Python module. The outer loop can propose a candidate bundle; a refinement subsystem can turn accepted candidate deltas into typed prompt/skill/memory/subagent entries only after evaluation evidence supports them.

### 5.5 Prime’s durable long-running model

[PRIME] Prime’s daemon model persists worker JSONL and artifacts, supports detach/attach, direct messages, heartbeats, schedules, goals, and bounded autonomous continuation. It treats compaction as an event rather than completion. It can rerun gates only when the workspace changes, and it has explicit token/turn/wall-clock bounds.

The key lesson for Meta-Harness is not to add every feature. It is to make the lifecycle explicit:

```text
created → admitted → running → waiting → resumed
       → succeeded / failed / canceled / expired
       → reconciled / archived
```

Each transition should be durable, idempotent, and tied to a run/attempt/worker identity. If a process dies after a candidate is written but before benchmark completion, a new process should be able to discover that state and either resume or mark it abandoned without guessing from directory names.

### 5.6 Prime’s latest ledger hardening

[PRIME] At the inspected current `main` snapshot, commit [`97b994c3d7c45ca1ae635190e91e9e58ddf2577c`](https://github.com/PrimeIntellect-ai/prime-agent/commit/97b994c3d7c45ca1ae635190e91e9e58ddf2577c) added a supervisor-owned RLM spawn ledger. The linked implementation and tests illustrate production-grade concerns that are directly useful here:

- append-only JSONL per session family;
- spawn, rename, and delete records;
- canonical paths and parent/child edges;
- bounded bytes/records;
- versioned record parsing;
- last-writer-wins semantics;
- duplicate path detection;
- torn-tail repair with byte-safe UTF-8 handling;
- race-safe seed creation;
- depth consistency checks;
- dead-session reconciliation;
- durable tombstones;
- focused tests for lifecycle races.

Meta-Harness does not need this full ledger immediately, but its current process-local branch registry is exactly the kind of place where these ideas become valuable.

### 5.7 Prime’s explicit safety caveat

[PRIME] Prime’s own documentation says model-generated Python and project commands run with the user’s permissions, and worker/kernel separation is not a security sandbox. This is not a weakness unique to Prime; it is a correct boundary statement. Meta-Harness should adopt the same honesty in its own docs and UI.

The project should keep two words separate:

- **Lifecycle isolation:** a failure in one worker, branch, or kernel should not corrupt unrelated runtime state.
- **Security isolation:** untrusted code cannot access protected files, networks, credentials, or host capabilities.

The current Meta-Harness sandbox is closer to lifecycle/workspace isolation than to security isolation. The shared verifier executor now uses the same process-limit hook as tool execution, but neither layer is a complete security boundary.

### 5.8 Adjacent research lessons

The Stanford/Prime comparison is the central one for this repository, but three other research lines sharpen the design choices. They should be treated as inspiration and ablation candidates, not as claims that their benchmark numbers transfer directly to Meta-Harness.

#### ACE: incremental playbooks, not repeated context rewrites

[PAPER] [Agentic Context Engineering (ACE)](https://arxiv.org/abs/2510.04618) separates a Generator, Reflector, and Curator. The Generator performs work with the current context/playbook; the Reflector analyzes successful and unsuccessful trajectories; the Curator applies structured incremental updates. The official implementation is [ace-agent/ace](https://github.com/ace-agent/ace), and the project describes the playbook as an evolving context rather than a repeatedly regenerated summary.

The useful lesson for Meta-Harness is not to replace the outer proposer. It is to separate three responsibilities that are currently easy to conflate:

1. **Generate:** propose a harness candidate or execute a task.
2. **Diagnose:** extract evidence-backed mechanisms from raw traces and evaluator results.
3. **Curate:** apply a small, typed, deduplicated update to a playbook, skill, or memory entry.

This is a direct argument for incremental refinement events. The project should prefer “add/update/delete this one evidence-backed component” over asking an agent to rewrite an entire global prompt or summary. It should also preserve a no-op result when the evidence does not support a new rule. ACE’s anti-context-collapse motivation aligns with the Stanford paper’s finding that raw traces matter: a concise summary is useful as an index, but it should not replace the underlying causal artifacts.

#### Reflexion: keep episodic trial memory distinct from accepted harness changes

[PAPER] [Reflexion](https://arxiv.org/abs/2303.11366) uses task feedback to generate verbal reflection and stores that reflection in an episodic memory buffer for subsequent attempts. Its reference code is [noahshinn/reflexion](https://github.com/noahshinn/reflexion).

The important distinction for this project is scope. A reflection about one failed attempt can help the next attempt without being promoted to a cross-run global rule. Meta-Harness should therefore model at least three memory scopes:

- **Attempt memory:** observations available to the next retry of the same task/candidate.
- **Run memory:** patterns available to later candidates within one outer run.
- **Global memory:** accepted, versioned patterns available across projects or runs.

Only the third scope should require a promotion/refinement event, evidence references, regression checks, and rollback. A self-generated reflection without a test result should be treated as a hypothesis, not as a learned fact. This protects the system from turning confident but incorrect self-critique into durable behavior.

#### Voyager: skill libraries need executable provenance and a curriculum

[PAPER] [Voyager](https://arxiv.org/abs/2305.16291) combines an automatic curriculum, an executable skill library, and iterative prompting driven by environment feedback, execution errors, and self-verification. Its public repository is [MineDojo/Voyager](https://github.com/MineDojo/Voyager).

The transferable lesson is that a reusable skill is a different artifact from a raw trace or a full harness candidate. A skill should have:

- an interface and preconditions;
- executable or inspectable content;
- task-family applicability;
- successful and failed evidence;
- version and parent identity;
- a test or verification record;
- retrieval metadata;
- a deprecation/rollback path.

For Meta-Harness, this suggests evolving `skills/meta-harness-coding-agent/` toward a versioned skill registry rather than only one static proposer instruction file. It also suggests a curriculum policy: once the baseline five-task set is mastered, the system should select new tasks that expose a missing mechanism, not merely keep replaying already-solved fixtures. Curriculum changes must remain outside the holdout boundary and must be recorded as part of the experiment manifest.

#### SWE-agent: the agent-computer interface is itself part of the harness

[PAPER] [SWE-agent](https://arxiv.org/abs/2405.15793) and its [ACI documentation](https://github.com/SWE-agent/SWE-agent/blob/main/docs/background/aci.md) argue that the design of the tool/interface layer materially affects software-engineering agent performance. This reinforces a point that is easy to miss when focusing only on prompts: the six local tools, their argument schemas, output truncation, patch format, error messages, and workspace visibility are all part of the evolvable harness.

Consequently, tool-interface changes should be classified separately from prompt or memory changes. The evaluation report should say whether a candidate changed:

- model instructions;
- planning/control flow;
- tool schemas or output formatting;
- context retrieval/truncation;
- verification/retry policy;
- memory or skill retrieval;
- runtime/child-agent behavior.

Otherwise a candidate that wins by changing the interface will be incorrectly described as a prompt improvement, and the experiment will not reveal which mechanism actually transferred.

#### Combined implication

These adjacent systems converge on one design rule:

> **Do not represent learning as one mutable blob. Represent it as scoped, typed, incremental artifacts that are generated from evidence, tested at the right boundary, and promoted only through explicit versioned transitions.**

That rule fits Stanford’s raw-trace research method, Prime’s continual-harness refinement, ACE’s generator/reflector/curator split, Reflexion’s episodic memory, Voyager’s skill library, and SWE-agent’s tool-interface emphasis without collapsing them into one undifferentiated framework.

## 6. Stanford Meta-Harness versus Prime Agent versus this project

The most useful comparison is by abstraction, not by feature count.

| Dimension | Stanford Meta-Harness | Current local Meta-Harness | Prime Agent | Recommended synthesis |
|---|---|---|---|---|
| Primary purpose | Search for better harnesses around a fixed model | Reproduce that shape with a coding harness and UI | Run, delegate, remember, and refine long-lived agents | Keep outer search as research plane; use durable runtime as execution plane |
| Unit of improvement | Harness candidate | Candidate Python harness / override behavior | Prompt, memory, skill, subagent spec, runtime state | Define a typed immutable candidate bundle with all of these as versioned components |
| Outer search | Minimal proposer with filesystem access to prior evidence | LangGraph outer loop | Not primarily a benchmark search loop | Keep proposer/archive/evaluator separate from runtime daemon |
| Inner execution | Task-specific reference harnesses | `orient → plan → act → verify → submit` | Persistent RLM/IPython plus tools and child agents | Support fixed graph first; add RLM as an optional execution backend |
| Evidence | Raw traces, scores, source, logs | Traces and artifacts exist but some paths are truncated or implicit | Transcripts, artifacts, usage, child registry, lifecycle logs | Build an append-only evidence ledger with raw references and structured indexes |
| Candidate isolation | Run/reference conventions and sandbox | Root `agents/` plus run artifacts | Session/artifact directories and daemon state | Never evaluate mutable root source; materialize candidate bundles |
| Selection | Multiobjective/Pareto search | Frontier module, but real usage is zero and candidate selection is last-item based | Refinement application/rollback, not benchmark Pareto | Separate archive, frontier, best-so-far, and accepted refinement |
| Memory | Deliberately lightweight filesystem access | Postgres learned-pattern store, mostly recency search | Local/global harness entries, history, rollback | Evidence-backed memory with explicit scope and version |
| Recursive delegation | Reference proposer can use delegated agents | Local real proposer allowlist has no `Agent`; inner loop is bounded | First-class RLM child handles and typed host bridge | Add delegation only after budget, attribution, and cancellation contracts exist |
| Durability | Research runs and logs | Postgres optional; API/branch registry process-local | Daemon workers, JSONL, artifacts, reconcilable state | Durable run/attempt/worker ledger before autonomous modes |
| Security | External/remote sandbox in reference coding setup | Copy/process limits; direct verifier bypass | Trust-oriented runtime, not a security sandbox | State capability policy and use a real sandbox for untrusted evaluation |
| Task scope | Text, math, coding examples | Small Python coding fixture set | Broad coding/workflow use | Generalize through task runtime adapters and larger frozen sets |
| Finalization | Separate final test flow | Holdout fixtures exist but finalization is not a strong first-class artifact | Long-running completion/gates | Implement explicit search, validation, and final test phases |
| Product surface | Research scripts/CLI | FastAPI + Next dashboard | Terminal/UI + daemon ecosystem | Use dashboard for provenance, evidence, and review—not only graph animation |
| Failure model | Research candidate failure | Test failure and subprocess errors | Worker/child failure, retry, resume, reconciliation | Classify failures and make lifecycle state durable |

### 6.1 The most important non-comparison

Prime is not automatically “a better Meta-Harness.” It solves a different center of gravity. Prime gives an agent a durable operating system for recursive work. Stanford Meta-Harness gives researchers a method for improving the harness itself through evidence-guided search.

The strongest combined system would look like this:

```text
              research / selection plane
  proposer → candidate archive → evaluator → frontier
       │             ▲                 │
       │             │ evidence        │ accepted candidate
       ▼             │                 ▼
  immutable harness bundle ─────── execution plane
                              fixed graph or RLM runtime
                                      │
                                      ▼
                           tasks, traces, usage, artifacts
                                      │
                                      ▼
                         evidence ledger + refinements
```

The research plane chooses what to try. The execution plane runs it durably. The evidence plane makes the result inspectable. The refinement plane converts supported improvements into versioned reusable harness components.

## 7. Recommended target architecture

### 7.1 Five planes, five responsibilities

#### A. Experiment plane

Owns:

- search runs and budgets;
- proposer prompts and permissions;
- parent-selection policy;
- candidate generation;
- archive/frontier policy;
- search versus holdout visibility.

It should not execute arbitrary candidate code directly or infer provenance from root directories.

#### B. Harness bundle plane

Owns the immutable description of what is being evaluated:

```yaml
candidate_id: cand_20260815_0007
run_id: run_20260815_001
parent_ids: [cand_baseline]
source:
  kind: python_module
  artifact_path: candidates/cand_20260815_0007/agents/harness.py
  sha256: ...
base_runtime:
  harness_api_version: 1
  inner_model: claude-haiku-4-5-20251001
  model_provider: anthropic
components:
  prompts: [prompt.default.v3]
  skills: [skill.coding-agent.v2]
  memories: [memory.pattern.42]
  subagents: []
evaluation_policy:
  search_tasks: [task-001, task-002, task-003, task-004, task-005]
  holdout_visible: false
  sandbox_profile: local-process-v1
provenance:
  proposer_session_id: ...
  git_commit: 5ac5d90
  created_at: ...
```

The exact serialization can be JSON, YAML, or Pydantic-backed JSON. The invariant is that the evaluator receives an ID and manifest, resolves an immutable artifact, and records the manifest hash in every result.

#### C. Execution plane

Owns:

- task workspace materialization;
- model/provider calls;
- tool execution;
- retries and timeouts;
- optional recursive children;
- cancellation and resume;
- resource accounting.

The current fixed LangGraph harness should remain the first backend. An RLM backend can later implement the same execution contract.

#### D. Evidence plane

Owns append-only events and query indexes:

```text
RunCreated
CandidateProposed
CandidateMaterialized
TaskAttemptStarted
ModelCallCompleted
ToolCallCompleted
VerificationCompleted
TaskAttemptFinished
CandidateBenchmarked
FrontierUpdated
RefinementProposed
RefinementApplied
RefinementRolledBack
RunPaused / RunResumed / RunCanceled
```

Raw stdout, stderr, transcripts, patches, and model responses should be stored as content-addressed or immutable artifacts. The event record can point to them without embedding huge payloads.

#### E. Refinement and archive plane

Owns:

- candidate archive;
- Pareto frontier;
- best-so-far policy;
- evidence-backed memory;
- typed prompt/skill/subagent refinements;
- global versus run-local scope;
- version history and rollback.

This is where the project should take the most direct inspiration from Prime’s continual harness.

### 7.2 Candidate identity and immutability

Every candidate should have two identities:

1. a human-readable candidate name for UI and discussion;
2. a content/provenance identity that is independent of the name.

A candidate is valid only if the evaluator can reproduce these facts:

- source bytes/hash;
- parent candidate IDs;
- base harness/runtime version;
- prompt/skill/memory component versions;
- model/provider identifiers;
- evaluator version;
- task set and visibility policy;
- sandbox profile;
- proposer session and authorization profile.

The candidate should never be “whatever is currently in `agents/`.” The root `agents/` directory may remain as a checked-in baseline or development convenience, but it must not be the source of truth for an evaluated candidate.

### 7.3 Evaluation contract

Define one evaluator interface and route both search and final evaluation through it:

```python
class Evaluator(Protocol):
    async def evaluate_task(
        self,
        candidate: CandidateArtifact,
        task: TaskSpec,
        policy: EvaluationPolicy,
    ) -> TaskResult: ...
```

`TaskResult` should include at least:

```text
candidate_id
task_id
attempt_id
passed
score
failure_category
test_summary
lint_summary
scope_summary
wall_seconds
model_calls
tool_calls
input_tokens
output_tokens
cached_tokens
estimated_cost
retry_count
artifact_refs
evaluator_version
sandbox_profile
```

If a provider does not expose a field, use `null` plus an explicit `measurement_status`, not zero. Zero means measured zero. Unknown means unknown.

### 7.4 Archive and frontier semantics

Maintain separate concepts:

- **Archive:** every valid candidate and its results.
- **Frontier:** non-dominated candidates under declared objectives.
- **Best-so-far:** one policy-selected candidate for convenience.
- **Accepted refinement:** a change promoted into a reusable component.
- **Rejected candidate:** retained for learning and regression analysis.

The archive must not discard low-scoring candidates. The Stanford ablation result makes raw failures and diagnostic traces valuable. Prime’s refinement history makes rejected/applied changes useful for rollback and comparison.

A selection policy should be configurable and recorded:

```text
parent_policy = best_accuracy
               | pareto_sample
               | diversity_sample
               | bandit_ucb
               | random_archive
```

The first policy can remain `best_accuracy`; the important change is that the policy becomes explicit and the archive remains available.

### 7.5 Evidence-backed refinements

Adopt a Prime-inspired refinement record adapted to Meta-Harness:

```json
{
  "refinement_id": "ref_00012",
  "kind": "prompt",
  "scope": "run",
  "target": "verify_prompt",
  "parent_version": "prompt.verify.v2",
  "proposed_version": "prompt.verify.v3",
  "rationale": "Failures show repeated omission of the configured test command.",
  "evidence": [
    {"run_id": "run_001", "task_id": "task-004", "artifact": "trace/..."},
    {"run_id": "run_002", "task_id": "task-005", "artifact": "trace/..."}
  ],
  "expected_outcome": "fewer verification retries without increasing task failures",
  "before_hash": "...",
  "after_hash": "...",
  "status": "proposed",
  "rollback_of": null
}
```

An accepted refinement should be tested in a new candidate/run. Do not mutate the active baseline in place and then compare it with itself.

## 8. Prioritized implementation roadmap

The roadmap is intentionally staged. Each phase improves the project’s ability to learn from the next phase.

### Phase 0: make current claims true

**Goal:** eliminate false precision and provenance ambiguity.

Implement:

1. A single `CandidateArtifact` manifest and materializer.
2. Run-scoped candidate directories with immutable source copies and hashes.
3. A single evaluator adapter used by benchmark and verify.
4. Sandbox-correct verification.
5. Explicit metric statuses for unknown token/cost/lint/scope values.
6. `synthetic=true` labeling for mock benchmarks.
7. Candidate-ID-based outer state transitions.
8. Snapshot dates and status labels in stale project docs.

**Done when:** a run can answer “what exactly was evaluated?” from its manifest alone, and no research report includes zero-as-placeholder metrics without saying so.

### Phase 1: make the search scientifically useful

**Goal:** turn the five-task demo into a defensible small experiment.

Implement:

1. Search/holdout task visibility enforcement.
2. Finalization command that evaluates baseline, Pareto candidates, and selected candidates on holdout without feeding results back.
3. Per-task results and failure categories.
4. Real token/cost/wall/turn/tool/retry accounting.
5. Candidate archive queries and CLI inspection.
6. Multi-candidate evaluation within one iteration.
7. At least two parent-selection policies for ablation.
8. Regression reports that show which tasks improved and regressed.

**Done when:** two independent runs can be compared from manifests and result tables without reading ad hoc logs by hand.

### Phase 2: evidence and memory

**Goal:** help the proposer learn from prior attempts without destroying raw evidence.

Implement:

1. Append-only event ledger with artifact references.
2. Queryable trace index: task, candidate, tool, failure category, model call, turn, and time.
3. Raw trace retention plus derived summaries; never summary-only storage.
4. Evidence-backed learned patterns with task-family, confidence, scope, and outcome fields.
5. Local/global memory scopes and versioned memory entries.
6. Refinement proposal/apply/rollback events.
7. Prompt/skill/subagent components as typed entries rather than only file diffs.

**Done when:** an agent can inspect an observed failure, propose a bounded change, apply it as a new version, and roll it back without rewriting the historical run.

### Phase 3: durable execution

**Goal:** make runs and branches recoverable across process restarts and multiple workers.

Implement:

1. Durable run/attempt/worker/branch identifiers.
2. Append-only state transition ledger.
3. Idempotent task-attempt admission and completion.
4. Cancellation, timeout, retry, abandoned-run, and reconciliation states.
5. Durable branch parent/child links and tombstones.
6. Explicit degraded mode when Postgres is unavailable.
7. Artifact retention and cleanup policies.

**Done when:** killing the backend during a candidate benchmark does not create an ambiguous result or orphaned branch that the system cannot reconcile.

### Phase 4: optional RLM execution backend

**Goal:** add Prime-style persistent recursive control only after the base evaluator is trustworthy.

Implement:

1. An execution backend interface shared by fixed LangGraph and RLM modes.
2. A typed host bridge for child admission, file/artifact references, messages, and cancellation.
3. Child budgets: maximum depth, count, tokens, cost, wall time, and concurrency.
4. Parent attribution for child usage and result delivery.
5. Persistent child registry and reconciliation.
6. Explicit kernel/worker lifecycle boundary.
7. Feature flag and research mode that disables recursion for clean ablations.

**Done when:** an RLM candidate can be compared fairly against the fixed-graph candidate using the same task, evaluator, evidence, and resource schemas.

### Phase 5: scale and broaden the research question

**Goal:** determine whether improvements generalize.

Implement:

1. More task families and enough examples for meaningful variation.
2. Multiple inner models and held-out models.
3. Search/evaluation concurrency with budget accounting.
4. Diverse task runtimes through adapters.
5. Independent final test sets and anti-leak audits.
6. Search efficiency metrics and repeated-seed confidence intervals.
7. Reproducible experiment bundles that can be shared or re-run.

**Done when:** the project can distinguish “better on our five fixtures” from “better across tasks, models, and environments.”

## 9. Recommended first engineering slice

If only one substantial slice can be implemented next, implement **run-scoped immutable candidates plus truthful evaluation**. The slice should be small enough to finish but large enough to remove the highest-risk false claims.

### Proposed code seams

These are proposed names, not existing APIs:

```text
backend/app/meta_harness/contracts.py
  CandidateArtifact, CandidateRef, TaskSpec, EvaluationPolicy, TaskResult

backend/app/meta_harness/candidates.py
  materialize_candidate(), load_manifest(), hash_candidate()

backend/app/meta_harness/evaluator.py
  evaluate_task(), evaluate_candidate(), finalize_holdout()

backend/app/meta_harness/ledger.py
  append_event(), get_run_events(), reconcile_run()

backend/app/meta_harness/provenance.py
  capture_model_config(), capture_git_state(), capture_environment()
```

Again, the exact module split can differ. The important design is that candidate materialization, evaluation, provenance, and durable evidence are independently testable.

### Suggested implementation order

1. Add contracts and serialization tests.
2. Materialize the baseline into a temporary run-scoped candidate and compare its hash to the source.
3. Change mock and real proposers to return a candidate artifact path/manifest instead of only writing to root `agents/`.
4. Change benchmark to accept a candidate ID and resolve its immutable artifact.
5. Route verify through the evaluator/sandbox adapter.
6. Record provider usage or `unknown` status.
7. Make the outer graph pass candidate IDs, not “last candidate.”
8. Add a finalization command that is unable to read holdout results during search.
9. Add one end-to-end test that kills or interrupts a run at each major boundary if a durable ledger is included in the same slice.

### Tests that should accompany the slice

- Candidate source is copied, hashed, and not changed when the root working tree changes.
- Two concurrent runs cannot resolve one another’s candidate source.
- A candidate manifest with missing usage says `unknown`, not zero.
- Mock benchmark results are marked synthetic and are rejected by research-report code.
- Verify uses the configured sandbox/evaluator adapter.
- A candidate ID mismatch fails closed rather than selecting the last list element.
- Holdout task IDs are unavailable to the proposer process and search evaluator.
- A failed candidate remains in the archive and is not silently promoted.
- Baseline and candidate results can be compared per task.
- Candidate source, model, evaluator, task set, and sandbox hashes appear in the result artifact.

## 10. Evaluation and ablation program

The project should not evaluate only “did the final score go up?” The point of a meta-harness is to learn which mechanisms cause improvement.

### 10.1 Core metrics

For every candidate and run, report:

- aggregate score;
- per-task score;
- pass rate;
- paired improvement versus baseline;
- regression count and regression task IDs;
- input, output, and cached tokens;
- estimated and billed cost where available;
- wall time;
- model-call count;
- tool-call count by tool;
- act turns;
- verification retries;
- child count/depth if recursion is enabled;
- sandbox failures and policy denials;
- evaluator failures distinct from agent failures;
- candidate generation time;
- archive size and frontier size;
- search efficiency: improvement per candidate, token, dollar, and wall hour.

### 10.2 Required ablations

1. **Scores only vs. raw traces.** Tests the Stanford claim that trace detail matters.
2. **Raw traces vs. structured trace index.** Tests whether queryability preserves signal while reducing context cost.
3. **One best parent vs. archive sampling.** Tests whether local hill climbing traps the search.
4. **Single candidate vs. candidate population per iteration.** Tests exploration diversity.
5. **Recency memory vs. evidence-ranked memory.** Tests whether Prime-like versioned memory helps.
6. **Fixed LangGraph runtime vs. RLM runtime.** Separates execution flexibility from harness improvement.
7. **No child agents vs. bounded children.** Measures whether recursive delegation is worth its cost.
8. **One inner model vs. held-out inner models.** Tests whether a harness overfits a model’s quirks.
9. **Search set vs. independent holdout.** Measures generalization.
10. **Environment bootstrap disabled/enabled.** Tests the Stanford coding insight directly.
11. **Summary compression strategies.** Measures whether current head/tail truncation loses important causal evidence.
12. **Prompt-only, skill-only, memory-only, and control-flow changes.** Identifies which harness components drive gains.

### 10.3 Experimental reporting rules

Every report should state:

- exact Git commit;
- candidate IDs and hashes;
- model/provider/model version;
- task set and holdout policy;
- evaluator version;
- sandbox profile;
- search budget and concurrency;
- whether metrics are measured or synthetic;
- skipped/failed tasks and why;
- whether the proposer had access to raw traces, summaries, or both;
- whether recursive children were enabled;
- whether any human intervention occurred.

A result that omits these fields may still be a useful demo, but it should not be labeled a reproducible research result.

## 11. Agent-facing implementation contract

Future coding agents working on this repository should follow these rules.

### Before changing code

1. Read [`AGENTS.md`](../AGENTS.md) and the relevant package-local guidance.
2. Inspect current Git status and preserve unrelated changes.
3. Read the current source and tests for the subsystem being changed.
4. Identify whether the task is changing the research protocol, runtime behavior, UI, or only documentation.
5. Find the nearest existing contract/test before inventing a new interface.

### When modifying the outer loop

- Never select a candidate by list position when an ID can be used.
- Never promote a candidate based on an unmeasured metric.
- Preserve rejected candidates and their traces.
- Record the parent-selection policy in the run manifest.
- Keep mock/synthetic paths visibly separate from live evaluation.
- Do not let proposer code read holdout data or final scores.

### When modifying the evaluator or sandbox

- Use the one evaluator boundary for both search and finalization.
- Treat process limits as resource controls, not security isolation.
- Fail closed on workspace escapes, unknown candidate IDs, and missing manifests.
- Record commands, environment policy, timeouts, exit codes, and artifact references.
- Do not silently turn unavailable usage into zero.

### When modifying prompts, skills, memory, or harness behavior

- Create a new version or candidate rather than mutating historical artifacts.
- Include rationale and evidence references.
- Keep scope explicit: run-local, project-local, or global.
- Make rollback possible.
- Test the change against baseline and at least one regression-sensitive task.

### When adding Prime-inspired recursion

- Use typed host requests rather than giving model-generated code unrestricted provider access.
- Bound depth, children, tokens, cost, wall time, and concurrency.
- Persist parent/child identities and attribute usage to the parent.
- Define cancellation and abandoned-child reconciliation before enabling autonomy.
- Keep a fixed-graph mode for clean comparison.

### Before claiming completion

Report separately:

- what changed;
- which exact tests/commands passed;
- which external/live paths were not exercised;
- whether the result is deterministic, synthetic, or production-like;
- any remaining docs/source contract drift;
- any new artifact paths.

Do not equate “tests pass” with “the meta-harness improved.” The former is a repository verification result; the latter requires candidate-level evaluation and comparison.

## 12. Product and research decisions still open

These decisions should be made explicitly by the project owners rather than inferred by future agents.

### 12.1 Is this one product or two modes?

Recommended answer: expose two named modes:

- **Research mode:** paper-faithful, deterministic, no hidden global memory, strict search/holdout boundary, fixed runtime policy, complete provenance.
- **Autonomous mode:** durable workers, schedules, recursive children, persistent memory, human review gates, and explicit trust assumptions.

Combining the modes into one default makes it difficult to know whether a gain came from a harness change, a persistent memory artifact, a larger context, a child agent, or a changed evaluator.

### 12.2 What is the candidate?

Possible choices:

- only a Python harness module;
- a module plus prompt/skill files;
- a complete immutable bundle including model/runtime/evaluator configuration;
- a refinement entry that can be applied to a reusable project harness.

Recommended answer: use the complete bundle for evaluation and expose component-level diffs for interpretation. A Python file alone is too narrow once prompts, memory, subagents, and runtime policies are part of the behavior.

### 12.3 What is the security model?

Possible choices range from trusted local experimentation to untrusted multi-tenant service. The current source is suitable only for a carefully trusted local profile unless a stronger sandbox is added. This should be stated in CLI help, deployment docs, API configuration, and the dashboard.

### 12.4 Is global memory allowed in research?

Recommended answer: not by default. Run-local memory can be part of a candidate’s bundle. Global memory should be an explicit ablation or a separate autonomous mode with provenance, review, and rollback.

### 12.5 Should the proposer delegate?

Recommended answer: eventually, but only as a budgeted experimental variable. The Stanford reference loop demonstrates why delegation can help diagnosis; Prime demonstrates how to make it durable. Neither justifies adding unpriced recursion to the current benchmark path.

## 13. Things that should not be done

- Do not add a bigger model and call that harness improvement.
- Do not copy Prime’s daemon wholesale before the candidate/evaluator contract is correct.
- Do not make the root `agents/` directory the implicit global source of truth.
- Do not use synthetic `mock_bench` results in a performance chart without a visible synthetic label.
- Do not interpret `avg_tokens=0` as an efficiency win.
- Do not keep raw-trace summaries while discarding the raw causal artifacts.
- Do not expose holdout results to the proposer because it makes debugging easier.
- Do not claim the sandbox is secure merely because it copies a directory and applies rlimits.
- Do not make `middleware`/frontend/auth warnings disappear by changing deployment behavior without recording the decision.
- Do not update a baseline in place and then compare it against an older candidate without hashes.
- Do not add persistent global memory without scope, evidence, version, and rollback.
- Do not make autonomous scheduling the default benchmark behavior.
- Do not let a process-local registry define durable truth.

## 14. Suggested success criteria for a “finalized” Meta-Harness

A reasonable definition of a mature next milestone is:

### Scientific correctness

- Candidate source is immutable and hashed.
- Search and holdout are separate and enforced.
- Every score is linked to candidate, task, model, evaluator, sandbox, and run.
- Real usage/cost fields are measured or explicitly unknown.
- Raw traces are retained and queryable.
- Baseline, candidate, frontier, and final-test reports are separate.

### Runtime correctness

- Verification uses the declared evaluator/sandbox policy.
- Candidate IDs and run IDs are used throughout the graph.
- Runs and branches have durable lifecycle records.
- Restart, cancellation, retry, and abandoned-run behavior are tested.
- Mock and live paths cannot be confused by the API or UI.

### Improvement capability

- The proposer can inspect evidence without receiving holdout data.
- Candidate selection can sample an archive, not only the last/best candidate.
- Prompt, skill, memory, and subagent refinements are versioned and reversible.
- The project can run ablations that identify which mechanism caused an improvement.
- An optional RLM backend can be enabled without changing the evaluator schema.

### Operational trust

- The security/trust profile is documented accurately.
- Auth and credential propagation behavior are covered by tests.
- Docs have snapshot dates and no stale completion claims without warnings.
- The dashboard shows provenance, usage, failures, and artifact links, not only graph state.
- Generated artifacts and sensitive files remain outside commits unless intentionally included.

## 15. Source index and local evidence map

### Local repository sources

- [Root README](../README.md)
- [Root agent instructions](../AGENTS.md)
- [Architecture section](../ARCHITECTURE_SECTION_1.md)
- [Current project status](PROJECT_STATUS.md)
- [Build order](BUILD_ORDER.md)
- [Definition of done](DEFINITION_OF_DONE.md)
- [Project layout](PROJECT_LAYOUT.md)
- [Interfaces](INTERFACES.md)
- [Project knowledge base](PROJECT_KNOWLEDGE_BASE.md)
- [Outer loop](../backend/app/meta_harness/outer.py)
- [Inner loop](../backend/app/meta_harness/inner.py)
- [Harness override surface](../backend/app/meta_harness/harness.py)
- [Tool implementations](../backend/app/meta_harness/tools.py)
- [Sandbox](../backend/app/meta_harness/sandbox.py)
- [Proposer](../backend/app/meta_harness/proposer.py)
- [Run helpers](../backend/app/meta_harness/runs.py)
- [Frontier](../backend/app/meta_harness/frontier.py)
- [Memory](../backend/app/meta_harness/memory.py)
- [Branches](../backend/app/meta_harness/branches.py)
- [Backend application](../backend/app/main.py)
- [Run API](../backend/app/api/runs.py)
- [State types](../backend/app/meta_harness/state.py)
- [Evaluation scorer](../eval/score.py)
- [Baseline harness](../agents/baseline.py)
- [Coding-agent skill](../skills/meta-harness-coding-agent/SKILL.md)

### External research sources

- [Stanford Meta-Harness paper](https://arxiv.org/html/2603.28052v1)
- [Stanford Meta-Harness abstract](https://arxiv.org/abs/2603.28052)
- [Stanford project page](https://yoonholee.com/meta-harness/)
- [Stanford reference repository](https://github.com/stanford-iris-lab/meta-harness)
- [Stanford TerminalBench harness](https://github.com/stanford-iris-lab/meta-harness/blob/main/reference_examples/terminal_bench_2/meta_harness.py)
- [Stanford text harness](https://github.com/stanford-iris-lab/meta-harness/blob/main/reference_examples/text_classification/meta_harness.py)
- [Prime Agent README](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/README.md)
- [Prime architecture](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/architecture.md)
- [Prime RLM](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/rlm.md)
- [Prime RLM runtime](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/rlm-runtime.md)
- [Prime long-running agents](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/long-running-agents.md)
- [Prime refinement source](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/src/core/refinement/refinement.ts)
- [Prime RLM ledger](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/src/modes/daemon/rlm-ledger.ts)
- [Prime RLM ledger tests](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/test/rlm-ledger.test.ts)
- [Prime current ledger-hardening commit](https://github.com/PrimeIntellect-ai/prime-agent/commit/97b994c3d7c45ca1ae635190e91e9e58ddf2577c)
- [ACE paper](https://arxiv.org/abs/2510.04618)
- [ACE implementation](https://github.com/ace-agent/ace)
- [Reflexion paper](https://arxiv.org/abs/2303.11366)
- [Reflexion implementation](https://github.com/noahshinn/reflexion)
- [Voyager paper](https://arxiv.org/abs/2305.16291)
- [Voyager implementation](https://github.com/MineDojo/Voyager)
- [SWE-agent paper](https://arxiv.org/abs/2405.15793)
- [SWE-agent ACI documentation](https://github.com/SWE-agent/SWE-agent/blob/main/docs/background/aci.md)

## Final recommendation

Treat the current Meta-Harness as a valuable research kernel that has outgrown its demo-era implicit state. The next version should not be defined by how many autonomous features it has. It should be defined by whether a human or agent can inspect one candidate and reconstruct its entire causal story:

```text
what changed
why it changed
which parent it came from
which exact source was evaluated
which model/runtime/evaluator ran it
what the agent did on every task
which raw evidence supports the diagnosis
what it cost
what improved and regressed
whether the change generalized
whether it can be rolled back
```

If that story is reliable, Prime-style persistent execution, recursive subagents, schedules, and continual refinement can increase the project’s power without compromising its research value. If that story is not reliable, more autonomy will mainly increase the number of plausible but untrustworthy explanations for a score change.
