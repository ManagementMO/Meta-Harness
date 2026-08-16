"use client";

import { useMemo, useRef, useState } from "react";
import { useDashboard } from "@/lib/state";
import { AnimatedNumber } from "./ui/AnimatedNumber";
import { DeltaChip } from "./ui/MonoStat";
import { EmptyState } from "./ui/EmptyState";
import { IconChartLineUp } from "./ui/icons";
import { cn } from "@/lib/cn";
import type { TreeNode } from "@/lib/types";

const TASK_ESSENCE: Record<string, string> = {
  "fix-typo": "Applies minimal, targeted edits without collateral changes.",
  "add-function": "Implements new behavior while preserving existing interfaces.",
  refactor: "Improves structure while keeping behavior stable.",
  "handle-error": "Adds robust failure handling and safe fallbacks.",
  "implement-spec": "Translates product requirements into correct code changes.",
};

function nodeKey(node: { candidate: string; candidateId?: string }): string {
  return node.candidateId ?? node.candidate;
}

function taskSlug(taskKey: string): string {
  return taskKey.replace(/^task-\d+-/, "").replace(/^task-/, "");
}

function scoreDomain(scores: number[]) {
  if (scores.length === 0) return { min: 0, max: 1 };
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const paddedMin = Math.max(0, min - 0.05);
  const paddedMax = Math.min(1, max + 0.05);
  return paddedMin === paddedMax
    ? { min: Math.max(0, paddedMin - 0.1), max: Math.min(1, paddedMax + 0.1) }
    : { min: paddedMin, max: paddedMax };
}

const W = 520;
const H = 240;
const PAD = { top: 18, right: 16, bottom: 30, left: 42 };

export function ScoreChart() {
  const { tree, selectedNode } = useDashboard();
  const [hovered, setHovered] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const mainNodes = useMemo(
    () => tree.filter((n) => !n.isForkBranch && n.status !== "rejected").sort((a, b) => a.iteration - b.iteration),
    [tree],
  );
  const forkNodes = useMemo(
    () => tree.filter((n) => n.isForkBranch).sort((a, b) => a.iteration - b.iteration),
    [tree],
  );
  const rejectedNodes = useMemo(() => tree.filter((n) => n.status === "rejected"), [tree]);
  const bestNode = tree.find((n) => n.status === "best");
  const plottedNodes = useMemo(
    () => [...mainNodes, ...forkNodes, ...rejectedNodes.filter((n) => !mainNodes.includes(n) && !forkNodes.includes(n))],
    [mainNodes, forkNodes, rejectedNodes],
  );

  const focusNode =
    (selectedNode
      ? tree.find((node) => (node.candidateId ?? node.candidate) === selectedNode || node.candidate === selectedNode)
      : null) ?? bestNode;

  const tasks = focusNode?.scores.per_task
    ? Object.entries(focusNode.scores.per_task)
        .map(([key, val]) => ({
          key,
          slug: taskSlug(key),
          label: taskSlug(key).replace(/-/g, " "),
          score: val.pass_rate,
          trials: val.trials,
        }))
        .sort((a, b) => a.label.localeCompare(b.label))
        .slice(0, 8)
    : [];

  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const maxIteration = Math.max(1, ...plottedNodes.map((n) => n.iteration));
  const yDomain = scoreDomain(plottedNodes.map((n) => n.scores.accuracy));
  const x = (v: number) => PAD.left + (v / maxIteration) * innerW;
  const y = (v: number) =>
    PAD.top + innerH - ((v - yDomain.min) / Math.max(0.01, yDomain.max - yDomain.min)) * innerH;
  const yTicks = Array.from({ length: 5 }, (_, i) => yDomain.min + ((yDomain.max - yDomain.min) * i) / 4);
  const xTicks = Array.from({ length: maxIteration + 1 }, (_, i) => i);

  const toPath = (nodes: TreeNode[]) =>
    nodes.map((n, i) => `${i === 0 ? "M" : "L"} ${x(n.iteration).toFixed(1)} ${y(n.scores.accuracy).toFixed(1)}`).join(" ");

  const forkParent = mainNodes.find(
    (node) =>
      (forkNodes[0]?.parentIds?.[0] && nodeKey(node) === forkNodes[0].parentIds[0]) ||
      node.candidate === forkNodes[0]?.parent_candidate_name,
  );
  const forkPath = forkParent
    ? `M ${x(forkParent.iteration).toFixed(1)} ${y(forkParent.scores.accuracy).toFixed(1)} ` +
      forkNodes.map((n) => `L ${x(n.iteration).toFixed(1)} ${y(n.scores.accuracy).toFixed(1)}`).join(" ")
    : "";

  // Pareto frontier: running max over accepted/best — the accent-lit line.
  const paretoPath = useMemo(() => {
    const eligible = tree
      .filter((n) => n.status === "accepted" || n.status === "best")
      .sort((a, b) => a.iteration - b.iteration);
    if (eligible.length === 0) return "";
    let bestSoFar = -Infinity;
    const frontier: { iteration: number; accuracy: number }[] = [];
    for (const n of eligible) {
      if (n.scores.accuracy >= bestSoFar) {
        bestSoFar = n.scores.accuracy;
        frontier.push({ iteration: n.iteration, accuracy: n.scores.accuracy });
      }
    }
    if (frontier.length === 0) return "";
    const segments: string[] = [`M ${x(frontier[0].iteration).toFixed(1)} ${y(frontier[0].accuracy).toFixed(1)}`];
    for (let i = 1; i < frontier.length; i++) {
      segments.push(`L ${x(frontier[i].iteration).toFixed(1)} ${y(frontier[i - 1].accuracy).toFixed(1)}`);
      segments.push(`L ${x(frontier[i].iteration).toFixed(1)} ${y(frontier[i].accuracy).toFixed(1)}`);
    }
    segments.push(`L ${x(maxIteration).toFixed(1)} ${y(frontier[frontier.length - 1].accuracy).toFixed(1)}`);
    return segments.join(" ");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tree, maxIteration, yDomain.min, yDomain.max]);

  const hoveredNode = hovered ? plottedNodes.find((node) => nodeKey(node) === hovered) : null;
  const acceptedCount = tree.filter((n) => n.status === "accepted" || n.status === "best").length;
  const rejectedCount = rejectedNodes.length;
  const forkCount = tree.filter((n) => n.isForkBranch).length;
  const latestNode =
    plottedNodes.length > 0 ? [...plottedNodes].sort((a, b) => b.iteration - a.iteration)[0] : null;
  const latestDelta = latestNode?.delta ?? null;

  // Crosshair: nearest plotted node to the pointer, in viewBox space.
  const handlePointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg || plottedNodes.length === 0) return;
    const rect = svg.getBoundingClientRect();
    const vx = ((event.clientX - rect.left) / rect.width) * W;
    const vy = ((event.clientY - rect.top) / rect.height) * H;
    let nearest: TreeNode | null = null;
    let bestDist = Infinity;
    for (const n of plottedNodes) {
      const dx = x(n.iteration) - vx;
      const dy = y(n.scores.accuracy) - vy;
      const d = dx * dx + dy * dy;
      if (d < bestDist) {
        bestDist = d;
        nearest = n;
      }
    }
    setHovered(nearest && bestDist < 2400 ? nodeKey(nearest) : null);
  };

  if (tree.length === 0) {
    return (
      <EmptyState icon={<IconChartLineUp size={20} />} title="Awaiting data" className="h-full">
        Scores plot here as candidates come off the benchmark.
      </EmptyState>
    );
  }

  return (
    <div className="h-full flex flex-col gap-3 min-h-0">
      {/* Headline readouts */}
      <div className="glass-inset rounded-[var(--radius-card)] grid grid-cols-4 divide-x divide-white/5">
        <Stat label="best">
          {bestNode ? (
            <AnimatedNumber value={bestNode.scores.accuracy} className="text-[15px] font-medium text-frost-bright" />
          ) : (
            <span className="text-[15px] text-ink-ghost">—</span>
          )}
        </Stat>
        <Stat label="latest Δ">
          {latestDelta === null ? <span className="text-[15px] text-ink-ghost">—</span> : <DeltaChip delta={latestDelta} />}
        </Stat>
        <Stat label="acc / rej">
          <span className="text-[15px] font-medium text-ink tabular-nums">
            {acceptedCount}
            <span className="text-ink-ghost"> / </span>
            {rejectedCount}
          </span>
        </Stat>
        <Stat label="forks">
          <AnimatedNumber
            value={forkCount}
            format={(v) => String(Math.round(v))}
            className="text-[15px] font-medium text-iris"
          />
        </Stat>
      </div>

      {/* Chart */}
      <div className="glass-inset rounded-[var(--radius-card)] p-2 relative">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="w-full h-auto block"
          role="img"
          aria-label="Accuracy per iteration with Pareto frontier"
          onPointerMove={handlePointerMove}
          onPointerLeave={() => setHovered(null)}
        >
          {/* grid */}
          {yTicks.map((v) => (
            <line key={v} x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} stroke="rgba(255,255,255,0.045)" strokeWidth={1} />
          ))}
          {mainNodes[0] && (
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(mainNodes[0].scores.accuracy)}
              y2={y(mainNodes[0].scores.accuracy)}
              stroke="rgba(255,255,255,0.09)"
              strokeWidth={1}
              strokeDasharray="3 5"
            />
          )}

          {/* axes */}
          {yTicks.map((v) => (
            <text key={v} x={PAD.left - 7} y={y(v) + 3} textAnchor="end" fill="#5A6473" fontSize={9} fontFamily="var(--font-geist-mono)">
              {v.toFixed(2)}
            </text>
          ))}
          {xTicks.map((v) => (
            <text key={v} x={x(v)} y={H - 14} textAnchor="middle" fill="#5A6473" fontSize={9} fontFamily="var(--font-geist-mono)">
              {v}
            </text>
          ))}
          <text x={PAD.left + innerW / 2} y={H - 2} textAnchor="middle" fill="#39414D" fontSize={8} fontFamily="var(--font-geist-mono)" letterSpacing="0.1em">
            ITERATION
          </text>

          {/* main lineage */}
          {mainNodes.length > 1 && (
            <path d={toPath(mainNodes)} fill="none" stroke="#8E99A8" strokeWidth={1.25} opacity={0.55} pathLength={1} className="chart-line-draw" />
          )}
          {/* fork lineage */}
          {forkPath && (
            <path d={forkPath} fill="none" stroke="#9E9BB3" strokeWidth={1.25} opacity={0.6} pathLength={1} className="chart-line-draw" />
          )}
          {/* Pareto frontier — the only glow */}
          {paretoPath && (
            <path
              d={paretoPath}
              fill="none"
              stroke="#E8EEF5"
              strokeWidth={1.5}
              pathLength={1}
              className="chart-line-draw"
              style={{ filter: "drop-shadow(0 0 5px rgba(255,255,255,0.3))" }}
            />
          )}

          {/* points */}
          {mainNodes.map((n) => (
            <circle key={nodeKey(n)} data-testid="chart-point" cx={x(n.iteration)} cy={y(n.scores.accuracy)} r={3} fill="#8E99A8" />
          ))}
          {forkNodes.map((n) => (
            <circle key={nodeKey(n)} data-testid="chart-point" cx={x(n.iteration)} cy={y(n.scores.accuracy)} r={3} fill="#9E9BB3" />
          ))}
          {rejectedNodes.map((n) => (
            <circle key={nodeKey(n)} data-testid="chart-point" cx={x(n.iteration)} cy={y(n.scores.accuracy)} r={3} fill="#B39199" opacity={0.45} />
          ))}
          {bestNode && (
            <>
              <circle cx={x(bestNode.iteration)} cy={y(bestNode.scores.accuracy)} r={8} fill="none" stroke="#E8EEF5" strokeWidth={1} opacity={0.35} />
              <circle data-testid="chart-point" cx={x(bestNode.iteration)} cy={y(bestNode.scores.accuracy)} r={3.5} fill="#E8EEF5" style={{ filter: "drop-shadow(0 0 4px rgba(255,255,255,0.45))" }} />
            </>
          )}

          {/* crosshair + readout */}
          {hoveredNode && (
            <g pointerEvents="none">
              <line
                x1={x(hoveredNode.iteration)}
                x2={x(hoveredNode.iteration)}
                y1={PAD.top}
                y2={H - PAD.bottom}
                stroke="rgba(255,255,255,0.12)"
                strokeWidth={1}
                strokeDasharray="2 3"
              />
              <circle cx={x(hoveredNode.iteration)} cy={y(hoveredNode.scores.accuracy)} r={5} fill="none" stroke="#E9EDF2" strokeWidth={1} opacity={0.6} />
              {(() => {
                const name =
                  hoveredNode.candidate.length > 22 ? hoveredNode.candidate.slice(0, 20) + "…" : hoveredNode.candidate;
                const label = `${name}  ${hoveredNode.scores.accuracy.toFixed(3)}`;
                const boxW = label.length * 5.4 + 14;
                const px = x(hoveredNode.iteration);
                const flipped = px > W - boxW - 20;
                const bx = flipped ? px - boxW - 10 : px + 10;
                const by = Math.max(PAD.top, y(hoveredNode.scores.accuracy) - 24);
                return (
                  <g>
                    <rect x={bx} y={by} width={boxW} height={18} rx={5} fill="#0C1016" stroke="rgba(255,255,255,0.12)" strokeWidth={1} />
                    <text x={bx + 7} y={by + 12} fill="#E9EDF2" fontSize={8.5} fontFamily="var(--font-geist-mono)">
                      {label}
                    </text>
                  </g>
                );
              })()}
            </g>
          )}

          {/* legend */}
          <g fontFamily="var(--font-geist-mono)" fontSize={8}>
            <circle cx={W - 158} cy={12} r={2.5} fill="#8E99A8" />
            <text x={W - 151} y={15} fill="#5A6473">MAIN</text>
            <circle cx={W - 114} cy={12} r={2.5} fill="#9E9BB3" />
            <text x={W - 107} y={15} fill="#5A6473">FORK</text>
            <line x1={W - 70} x2={W - 56} y1={12} y2={12} stroke="#E8EEF5" strokeWidth={1.5} />
            <text x={W - 51} y={15} fill="#5A6473">PARETO</text>
          </g>
        </svg>
      </div>

      {/* Focus + benchmark tasks */}
      <div className="flex items-baseline gap-2 min-w-0">
        <span className="text-label uppercase text-ink-ghost shrink-0">Focus</span>
        <span className="font-mono text-[11px] text-ink truncate">{focusNode?.candidate ?? "none selected"}</span>
      </div>

      <div className="glass-inset rounded-[var(--radius-card)] px-3 py-2.5 min-h-0 overflow-y-auto">
        <div className="text-label uppercase text-ink-low mb-2">Benchmark tasks</div>
        {tasks.length === 0 ? (
          <p className="font-mono text-[11px] text-ink-ghost">Waiting for benchmark task results.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {tasks.map((task) => (
              <li key={task.key} className="group" title={TASK_ESSENCE[task.slug] ?? `Evaluates ${task.slug} behavior.`}>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[11px] text-ink-mid w-32 truncate shrink-0">{task.label}</span>
                  <div className="flex items-center gap-[3px] shrink-0" aria-label={`${task.trials.filter(Boolean).length} of ${task.trials.length} trials passed`}>
                    {task.trials.map((pass, i) => (
                      <span
                        key={i}
                        aria-hidden="true"
                        className={cn("w-1.5 h-1.5 rounded-[2px]", pass ? "bg-moss/75" : "bg-ember/55")}
                      />
                    ))}
                  </div>
                  <div className="flex-1 h-px bg-white/5 min-w-2" aria-hidden="true" />
                  <span className="font-mono text-[11px] tabular-nums text-ink shrink-0">
                    {(task.score * 100).toFixed(0)}%
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 px-3 py-2 min-w-0">
      <span className="text-label uppercase text-ink-ghost truncate">{label}</span>
      <span className="font-mono tabular-nums">{children}</span>
    </div>
  );
}
