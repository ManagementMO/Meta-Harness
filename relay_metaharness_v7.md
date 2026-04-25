# RELAY — Time-Travel for Meta-Harness Optimization (v7, hackathon-scoped PoC)

*A great proof-of-concept that maps the Stanford Meta-Harness loop onto LangGraph state machines, with rewind, fork, and memory.*
*Secure, consistent, reversible — by construction.*
*LA Hacks 2026 — definitive build doc, v7 (post-scope-correction).*

---

## Changelog v6 → v7

v6 over-reached into "enterprise platform" territory that doesn't fit a 36-hour hackathon. v7 is a deliberate scope reset.

**Cut from v6:**
1. SSO / SAML / OIDC scaffolding
2. RBAC roles, workspace-level permissions
3. Audit log streaming to Splunk/Datadog
4. Self-hosted Docker Compose / Helm chart
5. Multi-tenant cloud at scale
6. Approval workflows
7. Slack / PagerDuty webhooks
8. SOC 2 / GDPR / compliance posture
9. Pro tier / Enterprise tier pricing, Stripe integration
10. Public template marketplace at scale
11. The "50K MAU / Series A" talk

**Sharpened:**
12. **Three properties as the framing**: *secure, consistent, reversible* — each mapped to a specific LangGraph primitive.
13. **More LangGraph primitives showcased**: memory, interrupts, subgraphs, streaming, durable execution — not just time-travel.
14. **Memory beat added to the demo**: the proposer remembers successful patterns across runs.
15. **Honest hackathon scope**: ~5 features ship at demo time, not 25. The substrate is the contribution.
16. **Pitch is shorter** (90 seconds, not 105).

---

## 1. The One-Paragraph Thesis

The Stanford Meta-Harness paper (Lee, Nair, Q. Zhang, K. Lee, Khattab, Finn — arXiv 2603.28052) showed that an agent reading raw execution traces and rewriting its harness beats every prior text optimizer (ACE, OPRO, TextGrad, AlphaEvolve). But their loop is *linear*: iter 1 → 2 → 3 → 4. Real harness optimization needs branching: rewind to iter 2, try a different proposer prior, fork, compare. **RELAY is a proof-of-concept that maps Meta-Harness onto LangGraph state machines, making the loop secure (durable execution), consistent (checkpointed), and reversible (time-travel). Built in 36 hours. One template, one fork, one moment on stage where the candidate tree branches.**

---

## 2. The Triad: Secure, Consistent, Reversible

These are the three properties a meta-harness substrate needs that the Stanford paper's research scaffolding doesn't have. Each maps directly to a LangGraph primitive:

| Property | What it means here | LangGraph primitive |
|---|---|---|
| **Secure** | A buggy candidate harness can't corrupt the run; partial failures don't poison state | **Durable execution** + **subgraphs** (candidate eval is sandboxed) |
| **Consistent** | Every state transition checkpointed; reproducible; multi-trial averaging exposes variance | **`PostgresSaver` checkpointer** + **TypedDict state schema** |
| **Reversible** | Any prior state can be rewound to; forks explore alternatives without losing the original | **`get_state_history`** + **`update_state`** + **`invoke(None, ckpt_id)`** |

This is the framing the pitch leads with. Three properties, three primitives, one substrate.

---

## 3. The LangGraph Stack We're Using

RELAY is built directly on LangGraph. We're not reinventing primitives. We're showcasing them in a use case that didn't exist before.

| Primitive | What it does for RELAY |
|---|---|
| **`StateGraph` + TypedDict** | The meta-harness loop expressed as a state machine: `propose → evaluate → judge → decide_next` |
| **`PostgresSaver` (checkpointer)** | Every iteration writes a checkpoint with a deterministic ID; runs survive crashes |
| **Cross-thread memory store** | The proposer remembers successful harness patterns across runs (not just within one run) |
| **`get_state_history(config)`** | List every checkpoint of a run — feeds the candidate trajectory tree UI |
| **`update_state(config, values)`** | Modify the proposer prior at any past checkpoint, creating a new fork |
| **`invoke(None, new_config)`** | Resume execution from a forked checkpoint without restarting the run |
| **Interrupts** | Pause before accepting any candidate above a score threshold; human-in-the-loop safety |
| **Subgraphs** | Each candidate harness is a subgraph compiled separately, sandboxed during eval |
| **Streaming** | Real-time state updates pushed to the dashboard via SSE |

Nine primitives, each doing real work. The implementation IS the showcase.

---

## 4. The Meta-Harness Loop as a LangGraph State Machine

```python
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver

class MetaHarnessState(TypedDict):
    run_id: str
    iteration: int
    candidates: list[Candidate]
    best_candidate: Candidate | None
    budget_remaining: int
    proposer_prior: str
    memory_keys: list[str]  # cross-thread memory references


def propose(state: MetaHarnessState):
    # Read prior candidates from filesystem
    # Read cross-thread memory (patterns from other runs)
    # Call proposer agent (Stanford claude_wrapper.py compatible)
    # Return new candidate
    ...

def evaluate(state: MetaHarnessState):
    # Run candidate as a subgraph against the eval harness
    # 5 trials per task, averaged
    # Return updated candidates list
    ...

def judge(state: MetaHarnessState):
    # Compare candidate score to current best
    # Update best_candidate if accepted
    # Decrement budget
    ...

def decide_next(state: MetaHarnessState):
    # If budget > 0, return "propose"
    # Else, write learned patterns to cross-thread memory and end
    ...

workflow = StateGraph(MetaHarnessState)
workflow.add_node("propose", propose)
workflow.add_node("evaluate", evaluate)
workflow.add_node("judge", judge)
workflow.add_conditional_edges(
    "judge",
    lambda s: "propose" if s["budget_remaining"] > 0 else END,
)
workflow.add_edge(START, "propose")
workflow.add_edge("propose", "evaluate")
workflow.add_edge("evaluate", "judge")

graph = workflow.compile(
    checkpointer=PostgresSaver(...),
    interrupt_before=["judge"],  # human can review before acceptance
)
```

That's the core. About 60 lines of real code. Every iteration writes a checkpoint. Every checkpoint is rewindable.

---

## 5. Time-Travel — The Killer Feature

The Stanford paper's loop is linear. With LangGraph's time-travel primitives, the loop becomes a tree.

### 5.1 Replay
Pick any past run, click "Replay." RELAY re-runs from `START` with same inputs. Use case: determinism check (replay 5×, see variance) or comparing proposers (replay with a different proposer agent given identical history).

### 5.2 Fork
Pick any checkpoint mid-run, click "Fork." RELAY creates a new thread from that checkpoint. Modify the proposer prior, hit "Resume." The new branch runs in parallel, visible in the candidate trajectory tree alongside the original.

### 5.3 Edit-and-Resume
The most powerful workflow. Modify the harness source, the proposer prior, or the eval task set at any checkpoint. `graph.update_state(checkpoint, values)` writes the modification as a new checkpoint. `graph.invoke(None, new_config)` resumes from there.

### 5.4 Why this is a Cognition rubric bullseye

Cognition's challenge specifically calls out *"smarter human-AI collaboration tooling — session replay, context transfer, progress dashboards…"*

**Time-travel debugging IS session replay taken to its logical conclusion** — not just "show me what happened" but *"show me what happened, let me change it, show me what would have happened differently."* This is the gold standard of session replay for agent systems, and nobody has shipped it for the meta-harness use case.

---

## 6. Memory — The Underrated LangGraph Feature

LangGraph's cross-thread memory store is the second beat that makes RELAY interesting. While checkpoints are *per-run* state, the memory store is *across runs*.

For meta-harness this matters because:

- The proposer learns that *"adding retry logic on schema_drift errors"* improves classification harnesses across multiple domains
- When you start a new run on a different domain, the proposer can read these cross-run patterns
- Without persistent memory, every run starts cold

### 6.1 What gets stored

```python
from langgraph.store.postgres import PostgresStore

store = PostgresStore(...)

# After a successful run:
store.put(
    namespace=("learned_patterns", "classification"),
    key=str(uuid.uuid4()),
    value={
        "pattern": "retry on schema_drift errors",
        "evidence": [run_ids_where_this_helped],
        "score_delta": 0.18,
    },
)

# Proposer reads at start of next run:
relevant_patterns = store.search(
    namespace=("learned_patterns", state["domain"]),
    query="schema drift retry",
    limit=5,
)
```

### 6.2 The memory beat in the demo

Without memory: every run starts at 62% baseline.
With memory: the proposer for a *new* run on a *different domain* immediately suggests retry logic because it remembers that worked elsewhere — and the new run starts at 70% on iter 1 instead of fighting through schema-drift errors first.

This is a 10-second beat in the demo, but it's the moment that signals "this is more than a wrapper around LangGraph time-travel."

---

## 7. Interrupts — Human-in-the-Loop Safety

LangGraph's interrupts let you pause execution at specific nodes. RELAY uses this for an optional safety feature: pause before accepting candidates that score significantly above current best.

```python
graph = workflow.compile(
    checkpointer=PostgresSaver(...),
    interrupt_before=["judge"],
)

# In the UI: when interrupt fires, dashboard shows
# "Candidate 3 scored 0.85 (+0.16) — review before accepting"
# User clicks "Approve" or "Reject + Note"
# graph.invoke(None, config) resumes
```

This is a 5-second beat in the demo, mostly to signal "this isn't a runaway optimization loop." Cuttable if time-pressed.

---

## 8. Subgraphs — Sandboxed Candidate Evaluation

Each candidate harness is a *subgraph* compiled separately:

```python
def make_candidate_subgraph(candidate_source: str) -> CompiledStateGraph:
    # Compile the candidate's harness as its own StateGraph
    # Runs in an isolated subprocess for the evaluation step
    # If it crashes, the parent graph's state is unaffected
    ...

def evaluate(state: MetaHarnessState):
    candidate = state["candidates"][-1]
    candidate_graph = make_candidate_subgraph(candidate.source)

    # Run the candidate against eval tasks in a sandbox
    # If candidate crashes, parent state stays consistent
    scores = run_with_isolation(candidate_graph, state["eval_tasks"])
    ...
```

This is what "secure" means in the triad. A buggy candidate doesn't corrupt the run.

---

## 9. Stanford Reference Framework Alignment

RELAY remains drop-in compatible with `stanford-iris-lab/meta-harness`:

- **Filesystem layout** matches `runs/{thread_id}/baseline/...` and `candidates/{checkpoint_id}/...`
- **`proposer-session.json`** is schema-compatible with the reference's `session.json` from `claude_wrapper.py`
- **`agents.X:AgentHarness`** import-path convention is supported
- **`relay init`** productizes their `ONBOARDING.md` flow as a guided CLI conversation

We support `claude_wrapper.py` as the default proposer backend. LangGraph proposer is the alternative. Users pick.

---

## 10. Why This Wins Cognition

### 10.1 Rubric fit

| Direction | RELAY hit |
|---|---|
| **Eliminating professional toil** | `relay loop` automates manual harness tuning. Time-travel automates *exploring alternatives* manually. |
| **Better verification for AI-generated code** | Eval harness with multi-trial averaging + holdout. Time-travel adds counterfactual verification. |
| **Smarter context retrieval** | Discovered harnesses learn better retrieval; cross-run memory persists those patterns. |
| **Agent plugins** | LangGraph `wrap_graph()` is the integration point. |
| **Session replay → human-AI collaboration** | **Bullseye.** Time-travel is session replay's natural endpoint. |

Five of five if you count session replay at full strength.

### 10.2 The hidden tiebreaker

A Cognition judge can sign up at `relay.dev` during the demo and fork a run on their own. The signup is one OAuth click; the fork is one right-click. **That conversion is the win condition.**

### 10.3 Research-literacy signal

Naming Khattab (DSPy author), ACE (the paper's headline competitor), AND LangGraph's specific time-travel primitives — three technical citations in 30 seconds — is the calibration trifecta for technical judges.

---

## 11. The Killer Demo (90 seconds, three acts)

### 11.1 Pre-demo setup
- `relay.dev` cloud instance pre-warmed
- Demo team's account pre-signed-in (skip OAuth in the actual run for speed)
- One pre-built template: "GitHub PR Triage Agent" — a LangGraph agent that classifies incoming PRs (urgent / docs / refactor / etc.)
- Frozen 5-task eval, baseline pre-evaluated at ~62%
- One prepared fork available from yesterday's run scoring 85% (used only as fallback)
- Backup demo video in 1-click

### 11.2 The 90-second flow

```
[0:00–0:08] HOOK (8s)
"Stanford published Meta-Harness four weeks ago — Lee, Khattab,
Finn. Their proposer agent reads execution traces and rewrites
the harness, beating ACE by seven and a half points.

But their loop is linear. We mapped it onto LangGraph and
made it a tree."

[0:08–0:23] ACT 1 — Cloud signup + template (15s)
[Open relay.dev. Click "Sign in with Google."
Lands on dashboard. Click "Templates."]

"30 seconds, no install. Pick a template — GitHub PR triage.
This is a LangGraph agent. Five-task eval. Baseline: 62%."

[Click "Optimize." Run starts.]

[0:23–0:53] ACT 2 — Linear loop (30s)
[State graph visualization on screen.
Iterations populate as nodes in real time via streaming.]

Iter 1: proposed "retry on schema_drift errors"
        eval... 0.70 (+0.08) — keep ✓
Iter 2: proposed "stricter tool-description hashing"
        eval... 0.66 (-0.04) — reject ✗
Iter 3: proposed "early-exit on auth failures"
        eval... 0.74 (+0.04) — keep ✓
Iter 4: proposed "more specific tool descriptions"
        eval... 0.80 (+0.06) — keep, new best ✓

Best: Iter 4, score 0.80 (+0.18)

"Stanford's regime — exactly. But here's where it gets
interesting."

[0:53–1:20] ACT 3 — Time-travel + memory (27s)
[Click "Iter 2" in the candidate trajectory tree.
Right-click → "Fork from here." Modal opens.]

"I'm rewinding to iteration 2. The proposer went hash-strictness —
wrong direction. I'll fork with a different prior from this point."

[Edit proposer prior. Click "Resume." State graph shows the tree
growing — original branch on left, fork on right.]

Iter 2': proposed "rewrite tool descriptions w/ examples"
         eval... 0.78 (+0.16 from iter 1) — keep ✓
Iter 3': proposed "add few-shot demos to descriptions"
         eval... 0.85 (+0.07) — keep, new global best ✓

[Tree shows both branches. Iter 4 (0.80) on original.
Iter 3' (0.85) on fork. Compare view side-by-side.]

"Two branches. Original: 0.80. Fork: 0.85. The meta-harness
loop is no longer a sequence — it's a search tree.

[Click memory panel sidebar.]

And LangGraph's cross-thread memory means the next run, on
a different domain, starts with what this run learned."

[1:20–1:30] CLOSE (10s)
"Time-travel for Meta-Harness. Built on LangGraph state machines.
Secure, consistent, reversible by construction. Open source.
That's RELAY. One spark."
```

### 11.3 Demo failure recovery

| Failure | Probability | Mitigation |
|---|---|---|
| Cloud platform down | Low | Local instance running on demo laptop as backup |
| Pre-signed-in session lost | Low | Second browser pre-signed-in |
| Run takes too long live | Medium | Pre-recorded run in same UI; toggle |
| Fork doesn't visibly create new branch | Medium | Pre-prepared fork from yesterday available — *"Here's a fork I made yesterday from iter 2"* |
| Both branches converge by chance | Low | Pre-tested proposer prior known to diverge |
| State graph viz breaks | Low | Fallback table view of iterations |
| Judge: "is this real or recorded?" | High | Open browser DevTools, show network requests live |
| Judge: "show me the actual harness diff" | High | Open candidate detail page; diff is a tab |
| **Judge wants to sign up themselves** | High and good | URL ready. **This is the win.** |

---

## 12. The Pitch (90 seconds)

```
[HOOK — 15s]
"Stanford published Meta-Harness four weeks ago. Lee,
Khattab — yes, the Khattab who wrote DSPy — Finn.
Their proposer agent reads execution traces and rewrites
the harness, beating ACE by seven and a half points with
four times fewer tokens.

But their loop is linear. We mapped it onto LangGraph and
made it a tree.

[INSIGHT — 15s]
LangGraph's state machine plus its time-travel primitives —
get_state_history, update_state, invoke from any checkpoint —
turn the meta-harness loop from a sequence into a search tree.

Three properties: secure, consistent, reversible — by
construction, because that's what LangGraph gives you.

[DEMO — 50s]
[Run the 50-second compressed three-act demo: cloud signup,
linear loop 62→80, fork to 85, memory beat.]

[CLOSE — 10s]
A proof-of-concept built on LangGraph. Drop-in compatible
with Stanford's reference framework. Open source from day one.

That's RELAY. One spark."
```

### Delivery notes
- **The "linear → tree" beat (15-30s)** is the single most important moment of the pitch.
- **Naming Khattab + ACE + LangGraph in 30 seconds** is the calibration trifecta.
- **Pause two beats** after Iter 3' hits 0.85.

---

## 13. Q&A (ordered by likely frequency)

**Q: How is this different from LangSmith?**
A: LangSmith is observability — it stores traces and surfaces aggregates. RELAY is an *optimization platform* that uses time-travel as a first-class primitive. We don't compete with LangSmith; many users will run both (LangSmith for production observability, RELAY for harness optimization).

**Q: Isn't this just LangGraph time-travel with a wrapper?**
A: LangGraph time-travel is a primitive; the meta-harness application is non-trivial. Specifically: (1) the meta-harness state graph schema, (2) the candidate trajectory tree visualization, (3) cross-run memory via LangGraph's store, (4) Stanford framework compatibility, (5) sandboxed candidate evaluation via subgraphs. LangGraph gives us the foundation; we ship the application.

**Q: How does the meta-harness loop being a tree (not sequence) actually help?**
A: Three concrete ways. (1) Recoverability — if iter 5 corrupts the proposer's prior, rewind to iter 4. (2) Exploration — when iter 2 makes an interesting choice, fork to try the alternative without losing the original. (3) Counterfactual debugging — *"if the proposer had focused on retries instead of hashing, would it have converged faster?"* — answerable empirically. The Stanford paper can't answer any of these; they restart their experiment.

**Q: What's the actual integration with `stanford-iris-lab/meta-harness`?**
A: Three concrete points. (1) Our trace filesystem layout matches their `runs/.../candidates/N/` directory. (2) Our `proposer-session.json` is schema-compatible with their `session.json`. (3) `relay loop` uses their `agents.X:AgentHarness` import-path convention. A user can adopt RELAY without changing their existing AgentHarness code.

**Q: The paper used 20 iterations × 2 candidates on Opus 4.6. Your demo uses 5. Isn't this too small?**
A: Demo is scoped for live runtime (~6 minutes vs the paper's hours). The substrate is the contribution, not the budget. Production users running with bigger budgets get the paper's regime; demo users see a meaningful arc in 6 minutes.

**Q: What about overfitting to the eval set?**
A: `relay loop --holdout` flag. The proposer never sees holdout traces. Final scores reported on holdout, not search set. Same pattern the paper used for TerminalBench-2.

**Q: How do you handle non-determinism?**
A: Multi-trial averaging — 5 trials per candidate per task by default. Time-travel makes this studyable: replay the same checkpoint 5× and see variance.

**Q: How does cross-run memory not poison new runs with stale knowledge?**
A: Memory entries are scoped by namespace (domain category) and tagged with score deltas + evidence run-IDs. The proposer reads relevant patterns but treats them as suggestions, not facts. If a pattern stops working, scores will reject it within a couple iterations.

**Q: Is the time-travel actually free, or is forking expensive?**
A: Forking creates a new thread pointer in Postgres — cheap. The expensive part is *evaluating* the new branch (running the candidate against the eval set), same cost as a normal iteration. Budget is shared between linear and branched iterations.

**Q: This is a hackathon proof-of-concept. What's the path to a real product?**
A: Honest. Open-source first; build community around the LangGraph + Meta-Harness intersection. If usage warrants, add team features (shared workspaces, alerts) post-hackathon. Not promising enterprise SSO this weekend.

---

## 14. Tech Stack

| Component | Tech | Why |
|---|---|---|
| **State engine** | Python + LangGraph + `PostgresSaver` | The state machine, checkpointer, and time-travel primitives are all native |
| **Backend API** | FastAPI | Spins up alongside the LangGraph engine in one process |
| **Database** | Postgres (Vultr managed) | LangGraph's checkpointer + memory store both need Postgres |
| **Job queue** | Background tasks via FastAPI's BackgroundTasks (skip Celery — overkill) | Async eval execution |
| **Frontend** | Next.js 15 + shadcn/ui + Tailwind 4 | Polished UI in hackathon time |
| **State graph viz** | ReactFlow | Standard for state machine visualization |
| **Trajectory tree viz** | D3.js | Custom tree viz for the fork branches |
| **Auth** | Clerk (Google OAuth only) | One hour to wire up, no enterprise scope |
| **Cloud frontend** | Vercel | Free tier, instant deploy |
| **Cloud backend** | Vultr A1 | Cheap, runs FastAPI + Postgres + Redis |
| **LLM (proposer)** | Anthropic Claude Sonnet 4.6 | Matches Meta-Harness paper |
| **Streaming** | SSE from FastAPI to Next.js | Live state updates |
| **Domain** | `relay.dev` (GoDaddy) | — |
| **Mockups** | Figma Make | Plushie qualification |

**Sponsor stack:** Cognition (primary target), MLH Vultr, MLH MongoDB (skip — Postgres is enough), MLH GoDaddy / .Tech, Figma Make.

### Why this stack ships in 36 hours
- **LangGraph does the hard work.** State machine, checkpointing, time-travel, memory — all built-in.
- **Clerk + Vercel + Vultr** is the fastest cloud stack. Sign-up flow is one hour.
- **No Celery, no Helm, no SSO, no Stripe.** Cut everything that's not in the demo path.

---

## 15. The 36-Hour Build Plan

### 15.1 Pre-hackathon (week before — non-negotiable)

- [ ] Read the Meta-Harness paper (arXiv 2603.28052), each team member
- [ ] Clone and run `stanford-iris-lab/meta-harness` locally
- [ ] Read LangGraph time-travel docs end-to-end
- [ ] Build a 50-line LangGraph state machine with `PostgresSaver`. Verify `get_state_history` and `update_state` work.
- [ ] Vultr A1 + Postgres + GoDaddy domain provisioned
- [ ] Vercel project linked to GitHub repo
- [ ] Clerk account + Google OAuth credentials
- [ ] **Pre-build the demo template** — "GitHub PR Triage Agent" as a LangGraph state graph with intentionally suboptimal initial harness
- [ ] **Pre-build the 5-task frozen eval** — JSON tasks + score function
- [ ] **Pre-evaluate baseline** — establish 60-65% so demo arc lands
- [ ] **Pre-prepare a known-good fork** scoring 85%
- [ ] **Pre-record 90-second backup video** by Thursday

### 15.2 Friday 6pm – Saturday 2am: State engine + cloud signup

| Time | Owner | Task | Done when |
|---|---|---|---|
| 6-7pm | All | Opening + Devpost registered | Aligned |
| 7-9pm | Backend A | LangGraph state engine: meta-harness `StateGraph` with `PostgresSaver` | First iteration writes a checkpoint |
| 7-9pm | Backend B | FastAPI: workspace + run CRUD, auth, Clerk integration | API endpoints work |
| 7-9pm | Frontend | Next.js scaffold: landing, auth flow, dashboard | Sign-in works |
| 7-9pm | PM | Devpost draft, demo script locked | Aligned |
| 9-11pm | All | End-to-end: cloud user → click run → state engine executes → state visible in UI | First run completes |
| 11pm-2am | Backend A | Eval harness module + multi-trial scoring | Eval scores demo template |
| 11pm-2am | Backend B | State graph endpoint (returns checkpoint tree as JSON for ReactFlow) | API returns valid tree |
| 11pm-2am | Frontend | Run-detail page with ReactFlow state graph | Tree renders for first run |

### 15.3 Saturday 2am – 12pm: Sleep + time-travel UI + memory

| Time | Owner | Task | Done when |
|---|---|---|---|
| 2-8am | 3 of 4 | Sleep | — |
| 2-8am | 1 of 4 | Watch builds, fix bugs only | Stable overnight |
| 9-11am | Backend A | Time-travel API: replay, fork, update_state endpoints | All three work via curl |
| 9-11am | Backend B | LangGraph memory store integration; cross-run memory entries | Memory persists across runs |
| 9-11am | Frontend | Time-travel UI: right-click checkpoint → fork modal → resume | Fork action works |
| 9-11am | PM | `relay-sdk` Python package — `wrap_graph()` for LangGraph + `@trace_run` decorator | `pip install relay-sdk` works |
| **11am-12pm** | **All** | **INTEGRATION GATE**: full demo dry-run including time-travel fork. If fork doesn't visibly create a new branch in the UI, fix before any other work. | Fork branch visible in tree |

### 15.4 Saturday 12pm – 10pm: Polish + 2nd template + dress rehearsal

| Time | Owner | Task | Done when |
|---|---|---|---|
| 12-2pm | All | Lunch + dry-run | Demo timed |
| 2-4pm | Backend A | Memory beat in demo: pre-seed memory store with one cross-run pattern | Memory visible in proposal |
| 2-4pm | Backend B | Subgraph isolation for candidate eval (signals "secure") | Candidate crash doesn't kill parent run |
| 2-4pm | Frontend | Memory panel sidebar; trajectory tree polish | Memory visible in UI |
| 4-7pm | All | Dinner + dress rehearsal | Demo crisp |
| 7-10pm | All | Final polish — loading states, empty states, dark mode | "Looks like a real product" pass |

### 15.5 Saturday 10pm – Sunday: Devpost, sleep, pitch

| Time | Owner | Task |
|---|---|---|
| 10pm-12am | PM | Final Devpost. Backup video uploaded. Sponsor boxes checked. |
| 10pm-12am | Frontend | Record clean backup demo video on second laptop |
| 12-2am | All | Pitch rehearsal on neighboring teams |
| 2-4am | 3 of 4 | Sleep |
| 2-4am | 1 of 4 | Fresh-signup gate check (incognito browser) |
| 4-8am | All | Sleep or polish |
| 8-10am | PM + frontman | Pitch rehearsal 5× with timer |
| 10am-judging | All | Setup, eat, deliver. **If a judge asks to sign up — pause everything else and walk them through it.** |

### 15.6 Scope-cut decision tree

Cut bottom-first if falling behind:

1. The 2nd template (1 template is enough to demo)
2. Memory panel sidebar UI (memory still works in backend, just not visible)
3. Subgraph isolation (signals "secure" but the demo still works without it)
4. `relay-sdk` Python package (cut LAST — losing this breaks the SDK story)
5. Edit-and-resume time-travel mode (replay + fork are enough)
6. Stanford `claude_wrapper.py` proposer backend (LangGraph proposer only)
7. Interrupts / human-in-the-loop (cuttable; not in demo)

**Never cut:** the state engine, the time-travel fork, the state graph visualization, the cloud signup flow, the LangGraph integration.

---

## 16. What We Explicitly Cut from Scope

Stating these proactively disarms gotcha questions:

- **SSO (SAML / OIDC).** Google OAuth only.
- **RBAC / multi-user workspaces.** Single-user per workspace.
- **Audit logs.** State changes are logged via LangGraph's checkpointer, but no UI.
- **Self-hosted Docker Compose / Helm.** Cloud-only at demo time.
- **Webhooks (Slack / PagerDuty).** None.
- **Pricing / Stripe / paid tiers.** Free.
- **SOC 2 / GDPR posture.** None claimed.
- **Multi-tenant scaling.** Single Postgres instance, all users share.
- **Public template marketplace.** 1-2 hardcoded templates.
- **Edit-and-resume time-travel.** Replay + fork only at demo time.
- **All proposer backends.** Day 1 = Stanford `claude_wrapper.py` + LangGraph proposer.
- **Distributed eval execution.** Single-machine.
- **TerminalBench-2 reproduction.** Out of scope.
- **Mobile native app.** Web-responsive only.

What's IN scope: state engine, time-travel UI, cloud signup with OAuth, 1-2 templates, LangGraph SDK, Stanford framework compatibility, candidate trajectory tree visualization, memory store integration. Doing this *well* in 36 hours is plenty.

---

## 17. Devpost Writeup Template

### Inspiration
Yoonho Lee, Roshen Nair, Qizheng Zhang, Kangwook Lee, Omar Khattab, and Chelsea Finn published the Meta-Harness paper on March 30, 2026 (arXiv 2603.28052). Their proposer agent reads execution traces and rewrites the harness, beating ACE by 7.7 points on classification with 4× fewer tokens, top-2 on TerminalBench-2.

But their loop is linear: iter 1 → 2 → 3 → 4. We thought it could be a tree.

### What it does
RELAY is a proof-of-concept that maps the Stanford Meta-Harness loop onto LangGraph state machines, making the loop **secure** (durable execution + sandboxed subgraphs), **consistent** (Postgres-backed checkpointer), and **reversible** (time-travel via `get_state_history` + `update_state`).

Sign up at `relay.dev` with Google OAuth. Pick a pre-built template (we ship "GitHub PR Triage Agent" — a LangGraph agent that classifies incoming PRs). Click "Optimize." Watch the meta-harness loop run in real time as a state graph. Right-click any past checkpoint to fork a parallel branch with a different proposer prior. Compare branches in the candidate trajectory tree.

Cross-run memory is persisted via LangGraph's store — the proposer remembers successful harness patterns across runs, so each new run starts smarter than cold.

We're drop-in compatible with `stanford-iris-lab/meta-harness`: same filesystem layout, schema-compatible `proposer-session.json`, support for their `claude_wrapper.py` proposer pattern.

### How we built it
- **State engine:** Python + LangGraph `StateGraph` with `PostgresSaver`. Every iteration is a checkpoint; `get_state_history`, `update_state`, and `invoke(None, config)` give us replay, fork, and edit-and-resume natively.
- **Cross-run memory:** LangGraph's `PostgresStore` persists patterns across threads.
- **Sandboxed candidate eval:** each candidate compiles as its own subgraph; a buggy candidate can't corrupt the parent run.
- **Backend:** FastAPI alongside LangGraph in one process.
- **Frontend:** Next.js 15 + shadcn/ui + ReactFlow (state graph) + D3 (candidate trajectory tree).
- **Auth:** Clerk for Google OAuth.
- **Cloud:** Vercel for frontend, Vultr for backend.
- **SDK:** `relay-sdk` Python package — `wrap_graph()` for LangGraph, `@trace_run` for generic agents.
- **Demo template:** "GitHub PR Triage Agent" as a LangGraph state graph; baseline 62%, fork-best 85%.

### Challenges
The hardest design decision was modeling the candidate trajectory tree as a LangGraph thread structure. LangGraph's checkpointer tracks linear history per thread; we needed branched history. Solution: forks create *new threads* with a `parent_thread_id` pointer, and the tree is reconstructed by walking parent links across threads.

Designing the time-travel UI required deciding what's a *replay* vs a *fork* vs an *edit-and-resume*. We landed on: replay re-runs the same thread; fork creates a new thread from a parent checkpoint; edit-and-resume is fork + state modification.

Building the LangGraph SDK integration cleanly meant supporting both `wrap_graph()` (for LangGraph users) and `@trace_run` (for generic agents) with the same backend.

### Accomplishments
We shipped a proof-of-concept for the meta-harness paradigm extended with time-travel in 36 hours. Built on LangGraph's full primitive set: state machines, persistence, time-travel, memory, subgraphs, streaming. Drop-in compatible with Stanford's reference framework. Demo agent climbed from 62% (baseline) to 80% (linear iter 4) and then to 85% (forked iter 3') — a tree-search improvement that the linear loop literally cannot achieve.

### What we learned
LangGraph's time-travel primitives are dramatically more general than they look. Once you have `get_state_history` + `update_state` + `invoke(None, ckpt_id)`, you have a state machine that supports arbitrary historical mutation — exactly the right primitive for any optimization-over-history problem.

We also learned that "secure, consistent, reversible" isn't three separate engineering efforts when you build on LangGraph — it's three properties you get from using the right primitives.

### What's next
- Open-source release; PR to `stanford-iris-lab/meta-harness` adding RELAY as a "compatible tools" entry
- Outreach to Stanford IRIS Lab and LangChain
- Edit-and-resume time-travel mode (post-hackathon)
- More proposer backends (Codex, Cursor, Devin)

---

## 18. Failure Mode Matrix

| Failure | Probability | Impact | Mitigation |
|---|---|---|---|
| Cloud platform down | Low | Catastrophic | Local dev instance running on demo laptop |
| Run takes too long live | Medium | Catastrophic | Pre-recorded run with same UI |
| Fork doesn't visibly create new branch | Medium | Catastrophic | Pre-prepared fork from yesterday — *"Here's a fork I made yesterday from iter 2"* |
| Both branches converge by chance | Low | High | Pre-tested proposer prior known to diverge |
| State graph viz breaks | Low | Medium | Fallback table view |
| Postgres connection issue | Low | High | Connection pool pre-warmed; restart script ready |
| LangGraph PostgresSaver schema migration fails | Low | High | Schema migrated and frozen Wednesday |
| Memory beat doesn't fire | Low | Low | Memory still in backend; pitch around it |
| Judge: "is this real or recorded?" | High | Low | Open browser DevTools, show network requests |
| Judge: "show me the actual harness diff" | High | Low | Open candidate detail page; diff is a tab |
| Demo eval not well-calibrated | Medium | High | Pre-evaluate Wednesday; baseline 60-65%, fork-best 80-85% |
| **Judge wants to sign up themselves** | High and good | Game-changing | URL ready. **This is the win.** |

---

## 19. Honest Roadmap

This is a hackathon project. The roadmap is honest about that.

### Week 1-2: Open-source launch
- Public GitHub release (MIT license) — both `relay-sdk` and the cloud platform
- HN, r/LocalLLaMA, r/MachineLearning, r/LangChain posts
- Outreach to Stanford IRIS Lab — RELAY is a research extension of their work
- Outreach to LangChain — RELAY is a flagship LangGraph use case
- PR on `stanford-iris-lab/meta-harness` adding RELAY to a "compatible tools" section
- Submit to awesome-langgraph

### Month 2-3: If usage warrants
- Polish based on early-user feedback
- Add Cursor / Devin / Codex proposer backends
- Edit-and-resume time-travel mode

### Beyond
Honestly, we don't know yet. If the open-source release gets 1,000+ stars and active usage, we'll consider what's next. If it doesn't, that's fine too — it remains a useful research artifact and a great hackathon project.

---

**Time-travel for Meta-Harness, on LangGraph state machines.**
**Secure, consistent, reversible — by construction.**
**Drop-in compatible with Stanford's reference. Open source.**
**One spark.**
