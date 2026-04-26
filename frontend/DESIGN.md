# Frontend Design — Meta-Harness Dashboard

**Date:** 2026-04-25
**Status:** Approved for implementation
**Audience:** Hackathon demo (90-second pitch to judges)
**Mockup:** `frontend/mockup.html` (open in browser for visual reference)

---

## 1. Purpose

A real-time dashboard that shows two things simultaneously:

1. **The forking trajectory tree** — the evolutionary branching of agent variants, where the meta-harness loop becomes a search tree instead of a linear sequence.
2. **The live agent decision log** — a layered stream showing outer-loop strategy decisions as chapter headers and inner-loop execution (tool calls, patches, test results) as detail lines.

Both must be visible at all times with zero interaction required. A judge watching the screen for 90 seconds should immediately see the tree branch and the agent's reasoning.

A third panel provides context on demand: score convergence chart, code diffs, and test output.

---

## 2. Design Decisions (Locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Framework | Next.js 15 + React | Per architecture docs |
| Styling | Tailwind CSS 4 | Utility-first, fast iteration |
| Visual tone | Dark terminal aesthetic | Monospace (JetBrains Mono), near-black bg (#050508), neon cyan/green/purple accents |
| Layout | 3-panel split (28/42/30) | Tree left, log center, context right. All hero features always visible |
| Tree library | D3.js (custom SVG) | ReactFlow is overkill for a static-ish tree; D3 gives full control over the fork visualization |
| Diff rendering | Custom component (no Monaco) | Monaco is 2MB+ — too heavy for a hackathon demo. Line-by-line unified diff with syntax highlighting via Prism or manual spans |
| Chart | Custom SVG (no chart library) | The convergence chart is ~30 lines of SVG. No need for recharts/d3-chart |
| Data source | Mocked SSE + static JSON | Backend APIs (steps 7-10) don't exist yet. Mock data matches INTERFACES.md contracts exactly so rewiring is mechanical |
| State management | React context + useReducer | No Redux/Zustand. SSE events dispatch to a reducer; components subscribe via context |
| Fork animation | Instant split | No animation drama. Tree snaps to show both branches immediately |

---

## 3. Layout

```
┌──────────────────────────────────────────────────────────────┐
│  META-HARNESS   │ ● demo-2026-04-25 ▾ │ iter 4/5 │ best 0.85 │ $2.14 │ 4m32s  │
├─────────────────┼────────────────────────────┼───────────────┤
│  ◆ Trajectory   │  ▸ Decision Log      LIVE  │  ◇ Context    │
├─────────────────┼────────────────────────────┼───────────────┤
│  [all] [win] [fk]  zoom │ [all][tools][verify][scores][forks] 🔍 │ [Chart][Diff][Test] │
├─────────────────┼────────────────────────────┼───────────────┤
│                 │                            │               │
│   Tree with     │   Scrolling log with       │  Score chart   │
│   fork zones,   │   iteration chapters,      │  (always)      │
│   node scores,  │   expandable lines,        │  ─────────────│
│   zoom/pan      │   inline test output       │  Diff viewer   │
│                 │                            │  or            │
│                 │                            │  Test output   │
│                 │                            │  (on selection)│
│                 │                            │               │
├─────────────────┴────────────────────────────┴───────────────┤
│  ● SSE connected │ 2 branches │ ckpt: a8f3…2e1b │ v0.1.0     │
└──────────────────────────────────────────────────────────────┘
```

**Panel widths:** 28% / 42% / 30%. Panels are NOT resizable in v1 (not worth the complexity for a demo).

**Viewport:** Designed for 1920×1080 (projector resolution). Must be legible at that size from 3 meters.

---

## 4. Components

### 4.1 TopBar

Static bar showing run metadata.

| Element | Source | Behavior |
|---------|--------|----------|
| Logo | Static | "META-HARNESS" in cyan, uppercase, letter-spacing 3px |
| Run selector | `GET /runs` | Dropdown with live dot. Mocked: single entry |
| Iteration counter | SSE `state-update` | "iter N/budget" |
| Best score | SSE `frontier-updated` | Cyan highlight, updates on new best |
| Cost | SSE `eval-result` | Running total of `cost_usd` |
| Elapsed | Client timer | Starts when run begins |

### 4.2 TrajectoryTree (left panel)

SVG-based tree rendered with D3. Each node is a candidate. Edges encode parent→child. Forks create visible branching.

**Data source:** `evolution_summary.jsonl` rows. Each row has `candidate`, `parent_candidate_name`, `scores.accuracy`, `delta`, `outcome`. The tree is reconstructed by walking `parent_candidate_name` links.

**Node rendering:**

| Status | Border | Background | Glow |
|--------|--------|------------|------|
| Baseline (seed) | `#2a2a3a` | `#111118` | None |
| Accepted | `#39ff14` (green) | `#081a12` | Subtle green |
| Rejected | `#ff3b5c` (red) | `#18080e` | None, 50% opacity |
| Best | `#00ffc8` (cyan) | `#081a18` | Cyan glow |
| Fork branch | `#a855f7` (purple) | `#120a1a` | Subtle purple |

Each node shows:
- Iteration label (top-left, 8px, uppercase, ghost color)
- Candidate name (middle, 10px, primary color)
- Score (bottom-left, 13px, bold, color-coded)
- Delta (next to score, 9px, +green/−red)
- Badge for rejected/best (top-right, 7px uppercase)

**Fork zone:** When a fork occurs, a horizontal band spans the tree width at the fork point. Contains "⑂ FORK" label and the fork's prior text. Background `#a855f708`, dashed purple border.

**Toolbar:**
- Filter buttons: `all` | `winning path` | `forks only`
  - "winning path" dims all nodes not on the path from baseline→best
  - "forks only" shows only fork points and their descendants
- Zoom: `−` / `+` / `⊡` (fit to view)
- Canvas: grab to pan, scroll to zoom

**Interaction:** Clicking a node selects it. Selection:
- Highlights the node border (2.5px stroke)
- Scrolls the decision log to that iteration's chapter
- Shows that candidate's diff in the context panel

**Scaling strategy for 20+ nodes:** Vertical layout with collapsible subtrees. If a linear chain has no forks, consecutive accepted nodes collapse into a single "N iterations" summary node with expand on click. Rejected nodes are rendered at 50% opacity and can be hidden via toolbar toggle.

### 4.3 DecisionLog (center panel)

Scrolling terminal-style log with two levels of hierarchy.

**Outer level — Iteration chapters:**
Each iteration gets a chapter header block containing:
- Iteration number (14px bold, cyan for main branch, purple for fork)
- Candidate name (11px, medium weight)
- Accept/reject/running status badge (top-right)
- Phase pipeline: `propose → validate → benchmark → frontier` with done/active states
- Hypothesis text (10px italic, below phases)

Chapters are collapsible. Clicking the header toggles showing/hiding the inner log lines.

**Inner level — Log lines:**
Each line shows: timestamp | tag | text | expand indicator

Tags (color-coded pills):
| Tag | Color | When |
|-----|-------|------|
| orient | indigo | Workspace scan at start of trial |
| plan | blue | Hypothesis and plan steps |
| tool/read | green | File reads |
| tool/patch | green | Patch applications |
| act | cyan | Active execution |
| verify | amber | Test runs |
| score | green | Score results |
| fail | red | Failures |
| fork | purple | Fork-related events |
| memory | amber | Cross-run memory reads/writes |

**Expandable lines:** Lines with `▸` indicator expand on click to show:
- `read` lines → file content preview (first 20 lines)
- `patch` lines → inline unified diff (selects it in context panel too)
- `verify` lines → full pytest output with pass/fail per test and failure tracebacks
- `score` lines → per-task breakdown

**Score result bars:** After each iteration's log lines, a colored bar shows:
- Left: "accuracy — accepted/rejected/regression"
- Right: score value (16px bold) + delta

**Fork events:** Rendered as a prominent card (not a log line) with:
- Icon + title + timestamp
- Parent checkpoint ID
- New prior text
- Branch ID
- Rationale

**Filter bar:**
- Toggle buttons: `all` | `tools` | `verify` | `scores` | `forks`
- Search input (filters log lines by text match)
- Filters are additive (selecting "tools" shows only tool-tagged lines)

**Auto-scroll:** Log auto-scrolls to bottom when new events arrive, UNLESS the user has scrolled up. Scrolling up pauses auto-scroll; a "jump to latest" button appears at bottom.

**Branch interleaving:** When fork branches run concurrently, their log entries interleave chronologically. Branch identity is encoded in the chapter header (purple color + "fork" label). This matches how SSE events arrive — multiplexed by `thread_id`.

### 4.4 ContextPanel (right panel)

Three tab views. The panel always shows the score chart at the top (fixed height 200px) regardless of active tab. Below the chart, the active tab content renders.

**Tabs:** `Score Chart` | `Diff` | `Test Output`

**4.4.1 Score Chart (always visible, top 200px)**

SVG line chart: x-axis = iteration, y-axis = accuracy.

- Main branch: green line + dots
- Fork branch: purple line + dots, diverging from fork point
- Baseline: dashed horizontal reference line at 0.62
- Rejected candidates: red dots (on the line but marked differently)
- Best candidate: cyan dot with glow, larger radius
- Y-axis: 0.60–0.90 range (auto-scales to data)

**4.4.2 Diff Viewer (below chart)**

Activated by:
- Clicking a `patch` log line
- Clicking a tree node (shows that candidate's full diff vs parent)

Renders unified diff format:
- File header: filename + `+N / −M` stats
- Line-by-line: line numbers, context (gray), additions (green bg), deletions (red bg)
- Monospace, 11px

Data source: mock diffs initially. In production, reads `agents/<name>.py` content and diffs against parent via the REST API.

**4.4.3 Test Output (below chart)**

Activated by clicking a `verify` log line.

Shows:
- Header: test file name + pass/fail summary
- Full pytest output with:
  - `PASSED` lines in green
  - `FAILED` lines in red with full traceback
  - Scrollable, max-height 400px

Data source: `verify.json` from trace artifacts.

### 4.5 StatusBar

Static bar at bottom: SSE connection status, active branch count, current checkpoint ID, version.

---

## 5. Data Flow

### 5.1 Mock Data Layer (v1 — what we build now)

```
frontend/
  lib/
    mock/
      evolution.ts      — evolution_summary.jsonl rows as TypeScript array
      events.ts         — SSE events as typed array, replayed on a timer
      diffs.ts          — candidate diffs as Record<string, string>
      test-output.ts    — verify.json content per iteration
    sse.ts              — MockSSEClient that replays events from events.ts
    api.ts              — functions that return mock data (same signatures as real API calls)
    types.ts            — TypeScript types matching INTERFACES.md §1-2 exactly
```

The mock SSE client replays events from `events.ts` with realistic timing (configurable speed: 1x for realism, 10x for dev iteration). It emits the same 11 event types defined in INTERFACES.md §7.2.

### 5.2 Real Data Layer (v2 — wired to backend)

Replace `mock/` imports with real fetch calls and `EventSource`:

```typescript
// lib/api.ts — v2
export async function getRun(runId: string): Promise<RunInfo> {
  const res = await fetch(`http://localhost:8000/runs/${runId}`);
  return res.json();
}

// lib/sse.ts — v2
export function subscribeToRun(runId: string): EventSource {
  return new EventSource(`http://localhost:8000/runs/${runId}/stream`);
}
```

The component layer doesn't change. Only the data layer swaps.

### 5.3 State Management

```typescript
// lib/state.ts
type DashboardState = {
  run: RunInfo | null;
  iterations: IterationChapter[];    // outer loop chapters
  logEntries: LogEntry[];            // inner loop lines
  tree: TreeNode[];                  // trajectory tree nodes
  frontier: FrontierCandidate[];     // Pareto frontier
  selectedNode: string | null;       // candidate name
  selectedLogLine: string | null;    // log entry ID
  filters: LogFilters;
  sseConnected: boolean;
};

type SSEAction =
  | { type: 'state-update'; payload: StateUpdateEvent }
  | { type: 'candidate-created'; payload: CandidateCreatedEvent }
  | { type: 'validate-result'; payload: ValidateResultEvent }
  | { type: 'eval-result'; payload: EvalResultEvent }
  | { type: 'frontier-updated'; payload: FrontierUpdatedEvent }
  | { type: 'iteration-complete'; payload: IterationCompleteEvent }
  | { type: 'fork-created'; payload: ForkCreatedEvent }
  | { type: 'branch-cancelled'; payload: BranchCancelledEvent }
  | { type: 'memory-pattern-stored'; payload: MemoryPatternEvent }
  | { type: 'checkpoint-written'; payload: CheckpointEvent }
  | { type: 'error'; payload: ErrorEvent };

function dashboardReducer(state: DashboardState, action: SSEAction): DashboardState {
  // Each SSE event type maps to a state transition
}
```

React context provides `state` + `dispatch`. SSE client dispatches actions on each event. Components read from context.

---

## 6. SSE Event → UI Mapping

How each of the 11 SSE event types (INTERFACES.md §7.2) drives UI updates:

| SSE Event | Tree | Log | Context | TopBar |
|-----------|------|-----|---------|--------|
| `state-update` | — | Update active phase in current chapter | — | Update iteration counter |
| `checkpoint-written` | — | — | — | Update checkpoint ID in status bar |
| `candidate-created` | Add new node to tree | Add new chapter header | — | — |
| `validate-result` | Update node status if failed | Add validate log line | — | — |
| `eval-result` | Update node score + delta | Add score bar | Update chart with new point | Update cost |
| `frontier-updated` | Re-color nodes (best/accepted/rejected) | — | Redraw Pareto markers on chart | Update best score |
| `iteration-complete` | — | Set chapter status badge | — | — |
| `fork-created` | Add fork zone + new branch in tree | Add fork event card | Add fork branch to chart | Update branch count |
| `branch-cancelled` | Gray out cancelled branch | Add cancellation log line | — | Update branch count |
| `memory-pattern-stored` | — | Add memory log line | — | — |
| `error` | — | Add error log line (red) | — | — |

---

## 7. Mock Data Spec

The mock data tells the demo story from DEFINITION_OF_DONE.md:

### 7.1 Timeline

| Time | Event | SSE Events |
|------|-------|------------|
| 0:00 | Run starts, baseline seed | `state-update` (propose) |
| 0:05 | Iter 1 proposed: retry-on-schema-drift | `candidate-created`, log lines |
| 0:15 | Iter 1 validated + benchmarked | `validate-result`, `eval-result` (0.70) |
| 0:20 | Iter 1 accepted | `frontier-updated`, `iteration-complete` |
| 0:25 | Iter 2 proposed: stricter-tool-hashing | `candidate-created`, log lines |
| 0:40 | Iter 2 benchmarked: regression | `eval-result` (0.66) |
| 0:45 | Iter 2 rejected | `frontier-updated`, `iteration-complete` |
| 0:50 | **Fork from iter 1 checkpoint** | `fork-created` |
| 0:55 | Iter 3 proposed: early-exit-on-auth | `candidate-created` (main) |
| 0:55 | Iter 2' proposed: rewrite-tool-desc | `candidate-created` (fork) |
| 1:10 | Iter 3 benchmarked: 0.74 | `eval-result` |
| 1:15 | Iter 2' benchmarked: 0.78 | `eval-result` |
| 1:20 | Iter 4 proposed: more-specific-desc | `candidate-created` (main) |
| 1:20 | Iter 3' proposed: few-shot-demos | `candidate-created` (fork) |
| 1:35 | Iter 4 benchmarked: 0.80 | `eval-result` |
| 1:40 | Iter 3' benchmarked: 0.85 — NEW BEST | `eval-result`, `frontier-updated` |
| 1:45 | Memory pattern stored | `memory-pattern-stored` |

### 7.2 Candidates

```typescript
const MOCK_CANDIDATES: EvolutionRow[] = [
  { iteration: 0, candidate: "baseline", parent_candidate_name: null, scores: { accuracy: 0.62 }, delta: null, outcome: "seed" },
  { iteration: 1, candidate: "retry-on-schema-drift", parent_candidate_name: "baseline", scores: { accuracy: 0.70 }, delta: 0.08, outcome: "70.0% (+8.0%)" },
  { iteration: 2, candidate: "stricter-tool-hashing", parent_candidate_name: "retry-on-schema-drift", scores: { accuracy: 0.66 }, delta: -0.04, outcome: "66.0% (−4.0%)" },
  { iteration: 3, candidate: "early-exit-on-auth", parent_candidate_name: "retry-on-schema-drift", scores: { accuracy: 0.74 }, delta: 0.04, outcome: "74.0% (+4.0%)" },
  { iteration: 4, candidate: "more-specific-descriptions", parent_candidate_name: "early-exit-on-auth", scores: { accuracy: 0.80 }, delta: 0.06, outcome: "80.0% (+6.0%)" },
  // Fork branch
  { iteration: 2, candidate: "rewrite-tool-descriptions", parent_candidate_name: "retry-on-schema-drift", scores: { accuracy: 0.78 }, delta: 0.16, outcome: "78.0% (+16.0%)", thread_id: "demo.fork.c7a1e3f0" },
  { iteration: 3, candidate: "few-shot-demos", parent_candidate_name: "rewrite-tool-descriptions", scores: { accuracy: 0.85 }, delta: 0.07, outcome: "85.0% (+7.0%)", thread_id: "demo.fork.c7a1e3f0" },
];
```

### 7.3 Diffs

Each candidate has a mock diff against its parent. The diffs should be realistic Python — actual `CodingAgentHarness` subclass modifications matching the 11 override points from INTERFACES.md §4.

### 7.4 Test Output

Each `verify` event has mock pytest output. Include:
- Passing iterations: `5 passed in 2.1s`
- Failing iterations: full traceback for 1-2 failures (e.g., `test_median_empty`, `test_median_even`)

---

## 8. File Structure

```
frontend/
├── DESIGN.md                      # This file
├── mockup.html                    # Static HTML mockup (reference only)
├── package.json
├── next.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.mjs
├── app/
│   ├── layout.tsx                 # Root layout: JetBrains Mono font, dark bg
│   ├── page.tsx                   # Redirect to /runs/demo
│   └── runs/
│       └── [runId]/
│           └── page.tsx           # Main dashboard page
├── components/
│   ├── TopBar.tsx
│   ├── TrajectoryTree.tsx         # D3-based SVG tree
│   ├── DecisionLog.tsx            # Scrolling log with chapters
│   ├── ContextPanel.tsx           # Tabs: chart, diff, test
│   ├── ScoreChart.tsx             # SVG convergence chart
│   ├── DiffViewer.tsx             # Unified diff renderer
│   ├── TestOutput.tsx             # Pytest output renderer
│   ├── ForkEvent.tsx              # Fork event card
│   ├── StatusBar.tsx
│   └── ui/                        # Shared primitives
│       ├── FilterBar.tsx
│       ├── Badge.tsx
│       └── PhasePipeline.tsx
├── lib/
│   ├── types.ts                   # All TypeScript types (mirrors INTERFACES.md)
│   ├── state.ts                   # DashboardState, reducer, context
│   ├── sse.ts                     # SSE client (mock in v1, real in v2)
│   ├── api.ts                     # REST client (mock in v1, real in v2)
│   └── mock/
│       ├── evolution.ts           # Mock candidate data
│       ├── events.ts              # Mock SSE event sequence
│       ├── diffs.ts               # Mock code diffs
│       └── test-output.ts         # Mock pytest output
└── public/
    └── fonts/                     # JetBrains Mono (self-hosted for reliability)
```

---

## 9. Color System

All colors as CSS variables / Tailwind theme extensions:

```
Background:
  --bg-void:    #050508    (body)
  --bg-panel:   #0a0a0f    (panel bodies)
  --bg-header:  #0d0d14    (headers, toolbars)
  --bg-hover:   #14141e    (hover states)
  --bg-active:  #18182a    (selected states)

Borders:
  --border:     #1a1a24    (default)
  --border-act: #2a2a3a    (active/hover)

Text:
  --text-hi:    #e8e8f0    (primary)
  --text-mid:   #8888a0    (secondary)
  --text-lo:    #4a4a5e    (tertiary)
  --text-ghost: #2a2a3a    (timestamps, line numbers)

Accents:
  --cyan:       #00ffc8    (best candidate, active phases, primary accent)
  --green:      #39ff14    (accepted, passing tests, positive deltas)
  --red:        #ff3b5c    (rejected, failing tests, negative deltas)
  --amber:      #ffb800    (verify, memory, warnings)
  --purple:     #a855f7    (fork branches, fork events)
  --blue:       #5ca0f0    (plan phase)
```

---

## 10. Typography

```
Font:        JetBrains Mono (self-hosted woff2)
Fallback:    IBM Plex Mono, monospace

Hierarchy:
  Iteration headers:  14px, weight 700, letter-spacing 1px
  Candidate names:    11px, weight 500
  Log lines:          12px, weight 400
  Tags/badges:        8-9px, weight 700, uppercase, letter-spacing 0.5-1px
  Timestamps:         9px, weight 400, ghost color
  Scores (in nodes):  13-14px, weight 700
  Status bar:         8px, weight 400, letter-spacing 0.5px
```

---

## 11. Interaction Model

### Click interactions:
- **Tree node** → selects node, scrolls log to that iteration, shows diff in context panel
- **Log line (patch)** → selects line (cyan left border), shows diff in context panel
- **Log line (verify)** → expands inline to show pytest output, also shows in context panel
- **Log line (read)** → expands inline to show file preview
- **Chapter header** → collapses/expands that iteration's log lines
- **Fork event card** → selects the fork point in the tree

### Keyboard:
- `↑/↓` — navigate log lines
- `Enter` — expand/collapse selected line
- `1/2/3` — switch context panel tabs
- `f` — toggle "winning path" filter on tree

### Auto-scroll:
- Log auto-scrolls to newest entry while streaming
- Scrolling up pauses auto-scroll
- "↓ Jump to latest" button appears when paused
- Clicking it resumes auto-scroll

---

## 12. Rewiring to Real Backend (v2)

When backend steps 7-10 are complete, the switch is:

1. Replace `lib/mock/` imports in `lib/sse.ts` and `lib/api.ts` with real `fetch` / `EventSource` calls
2. Point at `http://localhost:8000`
3. No component changes needed — the types and state shape are identical

**API endpoints consumed** (from INTERFACES.md §6):
- `GET /runs` — run list for selector
- `GET /runs/{runId}` — run detail (initial load)
- `GET /runs/{runId}/stream` — SSE subscription
- `GET /runs/{runId}/checkpoints` — checkpoint list (for fork modal, future)
- `POST /runs/{runId}/fork` — create fork (future)

**SSE events consumed** (from INTERFACES.md §7.2):
All 11 event types. The `thread_id` field on each event determines which branch the entry belongs to.

---

## 13. Out of Scope (v1)

- Fork modal (right-click → create fork). The mock data includes a pre-existing fork; creating new forks requires the backend.
- Run comparison / A-B side-by-side. Deferred to post-backend.
- Memory panel sidebar. Memory events appear in the log; dedicated panel is post-MVP.
- Resizable panels. Fixed widths in v1.
- Mobile/responsive. Desktop-only, 1920×1080 target.
- Authentication. None.
- Dark/light theme toggle. Dark only.

---

## 14. Implementation Notes

- **No `use client` everywhere.** The dashboard page is a client component (SSE requires it). Layout and routing are server components.
- **D3 in React:** Use `useRef` + `useEffect` for D3 rendering. D3 owns the SVG; React owns the data. Don't fight React's reconciliation — let D3 draw into a ref'd SVG element.
- **Self-host JetBrains Mono.** Don't rely on Google Fonts CDN during a demo. Download woff2 files into `public/fonts/`.
- **SSE reconnection.** The mock client doesn't need it, but structure the code so adding `Last-Event-ID` reconnection for the real client is trivial.
- **Performance.** The log will have at most ~200 lines for a 5-iteration demo. No virtualization needed. If scaling to 40+ iterations, add `react-window`.
