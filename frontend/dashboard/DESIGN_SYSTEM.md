# Meta-Harness — "Obsidian Glass" Design System

Mission-control research instrument for an autonomous harness-evolution loop.
Financial-terminal density, luxury-product finish. Supersedes `frontend/DESIGN.md`.

Design read: research observability dashboard for ML/agent researchers; obsidian
black-glass surfaces, one electric accent, mono for data, grotesk for UI, quiet
physical motion. No light mode. No emojis. Real domain language only.

---

## 1. Foundations

### 1.1 Canvas (the void)
The app floats on a near-black obsidian void — never pure `#000`, always dimensional.

| Token | Value | Use |
|---|---|---|
| `--color-void` | `#05070A` | page base |
| `--color-abyss` | `#080B10` | recessed wells (consoles, code) |
| `--color-node` | `#0C1016` | opaque fills inside canvases (ReactFlow nodes; NO blur there) |

Atmosphere (body backdrop, fixed, `pointer-events-none`):
- radial glow top-center: `radial-gradient(1200px 800px at 50% -10%, rgba(105,227,213,0.05), transparent 60%)`
- counter-glow bottom-left: `radial-gradient(900px 600px at 8% 110%, rgba(255,255,255,0.025), transparent 55%)`
- vignette: `radial-gradient(ellipse at 50% 50%, transparent 55%, rgba(0,0,0,0.35) 100%)`

### 1.2 Glass surfaces
Two glass tiers max. Specular top edge is the signature — every panel reads as polished glass.

| Recipe | Fill | Border | Specular | Blur |
|---|---|---|---|---|
| `glass-panel` (main panels) | `rgba(255,255,255,0.028)` | `1px rgba(255,255,255,0.07)` | `inset 0 1px 0 rgba(255,255,255,0.06)` | `backdrop-blur(14px)` |
| `glass-raised` (modal, popover, floating chrome) | `rgba(20,26,34,0.72)` | `1px rgba(255,255,255,0.10)` | `inset 0 1px 0 rgba(255,255,255,0.09)` | `backdrop-blur(20px)` |
| `glass-inset` (cards inside panels) | `rgba(255,255,255,0.025)` | `1px rgba(255,255,255,0.05)` | none | **none** |
| `well` (code/console inset) | `rgba(3,5,8,0.55)` | `1px rgba(255,255,255,0.04)` | `inset 0 1px 2px rgba(0,0,0,0.5)` | **none** |

Panel header sheen: `linear-gradient(180deg, rgba(255,255,255,0.04), transparent)`.
Hover light-sweep (primary interactive cards ONLY): a 60% translucent-white diagonal
gradient swept via `transform`, 500ms, once per hover.

**Blur budget: ≤ 6 blurred surfaces per viewport.** Run detail uses 5 (TopBar,
Spine, 3 panels). Never `backdrop-filter` inside the ReactFlow canvas, inside
scrolling list items, or nested more than 2 glass layers deep.

### 1.3 Ink
| Token | Value | Use |
|---|---|---|
| `--color-ink` | `#E9EDF2` | primary text |
| `--color-ink-mid` | `#8E99A8` | secondary text, labels |
| `--color-ink-low` | `#5A6473` | tertiary, axis labels |
| `--color-ink-ghost` | `#39414D` | watermarks, disabled |

### 1.4 The accent — Frost (monochrome light)
No hue accent at all — the signature accent is **white light on black glass**,
Apple-style. Frost is reserved exclusively for: live/streaming state, the Pareto
frontier, best candidate, primary actions, focus rings. Nothing "AI-vibey";
the instrument reads pure black-and-white.

| Token | Value | Use |
|---|---|---|
| `--color-frost` | `#E8EEF5` | lines, borders, icons |
| `--color-frost-bright` | `#FFFFFF` | text on dark, hover, glows |
| `--color-frost-dim` | `#B9C2CD` | quiet accent edges |
| glow | `rgba(255,255,255,0.10–0.35)` | shadows/halos, never stacked |

### 1.5 Semantic whisper tones
Barely-there hue over gray — the UI reads monochrome at a glance; meaning
surfaces on inspection. Used as text/border at low alpha, ~8–10% alpha fills.

| Meaning | Token | Value |
|---|---|---|
| accepted / pass | `--color-moss` | `#8CA396` |
| rejected / fail | `--color-ember` | `#B39199` |
| pending / synthetic | `--color-sand` | `#B3A78F` |
| fork / branch | `--color-iris` | `#9E9BB3` |

Rule: semantic hues never appear as large fills; chips are `color/12%` fill +
`color/25%` border + full-color text.

### 1.6 Typography
- UI: **Geist Sans** (`next/font/google`), the confident grotesk.
- Data: **Geist Mono** — ALL ids, scores, timestamps, code, log text, stats. Data is monospace.

Scale (dense instrument, nothing below 10px):
| Role | Size/leading | Font | Notes |
|---|---|---|---|
| `display` | 30/34 | Geist 600 | home brand, tracking -0.02em |
| `stat-lg` | 22/26 | Mono 500 | big numbers, tabular-nums |
| `title` | 14/20 | Geist 600 | panel titles |
| `body` | 13/20 | Geist 400 | prose, hypotheses |
| `data` | 12/18 | Mono 400 | log lines, table cells |
| `label` | 10/14 | Geist 500 | uppercase, tracking 0.14em |
| `micro` | 10/14 | Mono 400 | axis ticks, timestamps |

`font-variant-numeric: tabular-nums` globally on mono.

### 1.7 Radius, space, borders
- Radius family (concentric): panel `14px`, inner card `10px`, chip/control `7px`, pill `999px`.
- Space: 4px grid. Panel padding 20px; inner card padding 12px; dense rows 8px.
- Borders always 1px, white-alpha. No colored borders except semantic chips + focus.

### 1.8 Focus & a11y
- Focus ring: `2px solid var(--color-frost)` offset 2px, on `:focus-visible` only.
- All text ≥ 4.5:1 on its surface (ink-mid on glass ≈ 7:1; whisper tones verified ≥ 4.6:1).
- Hit targets ≥ 24px; interactive rows get full-row targets.
- `prefers-reduced-motion`: all non-essential motion off, final states rendered instantly.

---

## 2. Motion vocabulary
Fast, physical, quiet. Animate only `transform`/`opacity` (+ SVG path draw).

| Name | Spec | Use |
|---|---|---|
| `hover` | 150ms `cubic-bezier(0.32,0.72,0,1)` | color/border/sheen |
| `enter` | 220ms same ease, `y: 6→0, opacity 0→1` | cards, chapters |
| `spring-in` | spring `stiffness 420, damping 32` | log entries, fork cards |
| `count` | 300ms number morph (framer `animate`) | scores, deltas |
| `breathe` | 2.4s ease-in-out infinite, opacity 0.55↔1 | live dot only |
| `draw` | 400ms pathLength 0→1 | tree edges, chart lines |
| `shimmer` | 600ms single light sweep across the spine | iteration-complete only |
| `flash-edge` | 800ms border-glow decay | panel receiving an SSE update |

Never more than one infinite animation per viewport region (the live dot).

---

## 3. Data-viz themes

### Chart (ScoreChart / Pareto)
- Grid: `rgba(255,255,255,0.045)` hairlines; axes text `--color-ink-low` mono 10px.
- Main series: `--color-ink-mid` thin line, dots 3px.
- Fork series: `--color-iris` whisper.
- Rejected points: `--color-ember` at 45% opacity.
- **Pareto frontier: frost step-line, 1.5px, subtle glow** `drop-shadow(0 0 6px rgba(255,255,255,0.3))` — the only glow.
- Best point: frost dot with halo ring.
- Hover crosshair: hairline + mono readout chip (`glass-raised`, no blur — solid fill).

### TrajectoryTree (ReactFlow)
- Nodes: opaque `--color-node` fill (no blur in canvas), 1px status border at 35% alpha,
  specular top edge via inset gradient, mono data. Selected: frost border + halo.
- Best node: frost border + `0 0 24px rgba(255,255,255,0.12)` glow.
- Edges: 1.5px; accepted `moss/60`, rejected `ember/35`, fork `iris/60`; draw-in animated.
- Background: faint dot matrix `rgba(255,255,255,0.035)`.

### Monaco `obsidian` theme
- bg `#080B10`, fg `#C9D2DD`, line numbers `#39414D`,
  inserted `rgba(140,163,150,0.13)`, removed `rgba(179,145,153,0.11)`,
  selection `rgba(255,255,255,0.12)`, cursor `#FFFFFF`.
- Syntax: keywords `#8E99A8` 600, strings `#8CA396`, numbers `#E9EDF2`, comments `#5A6473` italic.

### Console (TestOutput)
`well` recipe, mono 12px, pass lines `moss`, fail lines `ember`, summary row pinned.

---

## 4. State matrix

### Run status (StatusPill)
| Status | Treatment |
|---|---|
| `running` + SSE open | frost pill, breathing dot, "LIVE" |
| `running` + SSE lost | sand pill, hollow dot, "RECONNECTING" |
| `completed` | moss whisper pill, solid dot |
| `failed` | ember whisper pill |
| mock/demo | sand whisper pill "DEMO REPLAY" |
| synthetic data | sand chip "SYNTHETIC" persistent in StatusBar |

### SSE events (closed set — every one has a designed reaction)
| Event | Reaction |
|---|---|
| `state-update` | header MonoStats morph (`count`) |
| `checkpoint-written` | StatusBar ckpt id morphs; log entry (memory tag) |
| `candidate-created` | tree node scale/fade in + edge `draw`; chapter appears, propose stage lit |
| `validate-result` | validate stage lights moss tick / ember cross; log entry |
| `eval-result` | benchmark stage lit; node score `count`s up; per-task rows stream in |
| `frontier-updated` | frontier path re-`draw`s; best node gains glow; best-score stat morphs |
| `iteration-complete` | single `shimmer` across the spine; chapter seals with status chip |
| `fork-created` | iris edge draw-in; fork card `spring-in`; branch chip appears |
| `branch-cancelled` | branch nodes dim to 40%, "CANCELLED" chip |
| `memory-pattern-stored` | memory tab count ticks; log entry |
| `error` | ember chip in StatusBar with message; log entry; pill → RECONNECTING if closed |

---

## 5. Layout

### Run detail (mission control)
```
┌ TopBar (glass, 52px): brand ⋅ run-id mono ⋅ StatusPill ⋅ replay ⋅ auth ┐
├ Spine (glass, 44px): propose→validate→benchmark→frontier ⋅ iter ⋅ best ⋅ Δ ┤
├───────────────┬──────────────────────────┬───────────────────────┤
│ Trajectory    │ Decision Log             │ Context               │
│ (ReactFlow)   │ (chapters + entries)     │ (chart/diff/test/     │
│ 300px         │ 1fr                      │  evidence/memory)     │
│               │                          │ 30rem, 26rem @1024    │
├───────────────┴──────────────────────────┴───────────────────────┤
└ StatusBar (glass, 30px): SSE ⋅ data class ⋅ persistence ⋅ ckpt ⋅ branches ┘
```
Panels are floating glass islands over the void with 12px gutters, not a flat splitter grid.

### Home (launch pad)
Obsidian void + atmosphere; brand lockup (Geist display + mono eyebrow);
launch console = one `glass-panel` bezel: proposer/bench segmented controls,
preset cards (hover sweep), primary "Initialize run" frost action;
recent-runs rail (mono table) when backend live; quiet auth links; status readout bottom-left.

Grid/scan-line/typing-title effects die. One page-load stagger (80ms steps), then still.

---

## 6. Icons
Single coherent set: **Phosphor (light/regular)** via inline SVG components
(`src/components/ui/icons.tsx`). 1.5px stroke equivalents; 14–16px sizes. No emoji,
no unicode glyph icons (◆ ⑂ ✓ ★ die). Fork glyph = `git-branch`, memory = `brain`,
checkpoint = `floppy-disk-back`, frontier = `chart-line-up`, live = `broadcast`.

## 7. What dies (audit summary)
Typing-title + blinking cursor; SVG gridline background; scanline; rainbow tag pills;
7–9px type; JetBrains-for-everything; flat `#111118` panels + solid header strips;
unicode icons; vs-dark Monaco; borders-on-everything cards; 220px unusable tree column;
purple `#8878a8` and teal `#7ab8ad` as quasi-accents; uppercase 10px walls in StatusBar.
