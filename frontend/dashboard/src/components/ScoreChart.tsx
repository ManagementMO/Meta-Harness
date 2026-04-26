'use client';
import { useMemo, useState } from 'react';
import { useDashboard } from '@/lib/state';

function barColor(score: number) {
  if (score >= 0.8) return '#6a9e78';
  if (score >= 0.6) return '#b09868';
  return '#b06068';
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

export function ScoreChart() {
  const { tree } = useDashboard();
  const [hovered, setHovered] = useState<string | null>(null);

  const mainNodes = tree.filter(n => !n.isForkBranch).sort((a, b) => a.iteration - b.iteration);
  const forkNodes = tree.filter(n => n.isForkBranch).sort((a, b) => a.iteration - b.iteration);
  const rejectedNodes = tree.filter(n => n.status === 'rejected');
  const bestNode = tree.find(n => n.status === 'best');
  const plottedNodes = useMemo(
    () => [...mainNodes, ...forkNodes, ...rejectedNodes],
    [mainNodes, forkNodes, rejectedNodes],
  );
  const taskBreakdown = useMemo(() => {
    const tasks = bestNode?.scores.per_task ?? plottedNodes.at(-1)?.scores.per_task ?? {};
    return Object.entries(tasks)
      .map(([key, info]) => ({
        key,
        label: key.replace(/^task-/, '').replace(/_/g, '-'),
        score: info.pass_rate,
      }))
      .sort((a, b) => b.score - a.score || a.key.localeCompare(b.key))
      .slice(0, 8);
  }, [bestNode, plottedNodes]);

  const width = 500;
  const chartHeight = 300;
  const barSectionHeight = taskBreakdown.length > 0 ? 38 + taskBreakdown.length * 20 : 76;
  const totalHeight = chartHeight + barSectionHeight;
  const pad = { top: 20, right: 20, bottom: 40, left: 55 };
  const w = width - pad.left - pad.right;
  const h = chartHeight - pad.top - pad.bottom;

  const maxIteration = Math.max(1, ...plottedNodes.map(n => n.iteration));
  const xMin = 0, xMax = maxIteration;
  const yDomain = scoreDomain(plottedNodes.map(n => n.scores.accuracy));
  const x = (v: number) => pad.left + ((v - xMin) / Math.max(1, xMax - xMin)) * w;
  const y = (v: number) => pad.top + h - ((v - yDomain.min) / Math.max(0.01, yDomain.max - yDomain.min)) * h;
  const yTicks = Array.from({ length: 5 }, (_, i) => yDomain.min + ((yDomain.max - yDomain.min) * i) / 4);
  const xTicks = Array.from({ length: maxIteration + 1 }, (_, i) => i);

  const toPath = (nodes: typeof mainNodes) =>
    nodes.map((n, i) => `${i === 0 ? 'M' : 'L'} ${x(n.iteration)} ${y(n.scores.accuracy)}`).join(' ');

  // Fork line starts from the parent node on the main branch
  const forkParent = mainNodes.find(n => n.candidate === forkNodes[0]?.parent_candidate_name);
  const forkPath = forkParent
    ? `M ${x(forkParent.iteration)} ${y(forkParent.scores.accuracy)} ` + forkNodes.map(n => `L ${x(n.iteration)} ${y(n.scores.accuracy)}`).join(' ')
    : '';

  // Pareto frontier: stepped line connecting accepted/best nodes in iteration order
  const paretoEligible = tree
    .filter(n => n.status === 'accepted' || n.status === 'best')
    .sort((a, b) => a.iteration - b.iteration);

  let paretoPath = '';
  if (paretoEligible.length > 0) {
    let bestSoFar = -Infinity;
    const frontier: { iteration: number; accuracy: number }[] = [];
    for (const n of paretoEligible) {
      if (n.scores.accuracy >= bestSoFar) {
        bestSoFar = n.scores.accuracy;
        frontier.push({ iteration: n.iteration, accuracy: n.scores.accuracy });
      }
    }
    if (frontier.length > 0) {
      const segments: string[] = [`M ${x(frontier[0].iteration)} ${y(frontier[0].accuracy)}`];
      for (let i = 1; i < frontier.length; i++) {
        // Stepped: horizontal then vertical
        segments.push(`L ${x(frontier[i].iteration)} ${y(frontier[i - 1].accuracy)}`);
        segments.push(`L ${x(frontier[i].iteration)} ${y(frontier[i].accuracy)}`);
      }
      // Extend to right edge
      segments.push(`L ${x(xMax)} ${y(frontier[frontier.length - 1].accuracy)}`);
      paretoPath = segments.join(' ');
    }
  }

  const hoveredNode = hovered ? plottedNodes.find(n => n.candidate === hovered) : null;

  // Bar chart layout
  const barTop = chartHeight + 10;
  const barLeft = pad.left + 80;
  const barRight = width - pad.right;
  const barMaxW = barRight - barLeft;
  const barH = 14;
  const barGap = 6;

  return (
    <svg
      viewBox={`0 0 ${width} ${totalHeight}`}
      className="w-full"
      preserveAspectRatio="xMidYMin meet"
      style={{ maxHeight: '100%' }}
    >
      {/* ── Main Chart ── */}

      {/* Grid */}
      {yTicks.map(v => (
        <line key={v} x1={pad.left} x2={width - pad.right} y1={y(v)} y2={y(v)} stroke="#1c1c26" strokeWidth={1} />
      ))}

      {/* Baseline */}
      {mainNodes[0] && (
        <line x1={pad.left} x2={width - pad.right} y1={y(mainNodes[0].scores.accuracy)} y2={y(mainNodes[0].scores.accuracy)} stroke="#303040" strokeWidth={1} strokeDasharray="4 4" />
      )}

      {/* Pareto frontier */}
      {paretoPath && (
        <path d={paretoPath} fill="none" stroke="#7ab8ad" strokeWidth={1.5} strokeDasharray="6 4" opacity={0.3} />
      )}

      {/* Y axis labels */}
      {yTicks.map(v => (
        <text key={v} x={pad.left - 8} y={y(v) + 3} textAnchor="end" fill="#4e4e5c" fontSize={9} fontFamily="monospace">{v.toFixed(2)}</text>
      ))}

      {/* Y axis title */}
      <text
        x={12}
        y={pad.top + h / 2}
        textAnchor="middle"
        fill="#4e4e5c"
        fontSize={8}
        fontFamily="monospace"
        letterSpacing="0.08em"
        transform={`rotate(-90, 12, ${pad.top + h / 2})`}
      >
        ACCURACY
      </text>

      {/* X axis labels */}
      {xTicks.map(v => (
        <text key={v} x={x(v)} y={chartHeight - 18} textAnchor="middle" fill="#4e4e5c" fontSize={9} fontFamily="monospace">{v}</text>
      ))}

      {/* X axis title */}
      <text
        x={pad.left + w / 2}
        y={chartHeight - 2}
        textAnchor="middle"
        fill="#4e4e5c"
        fontSize={8}
        fontFamily="monospace"
        letterSpacing="0.08em"
      >
        ITERATION
      </text>

      {/* Main line */}
      {mainNodes.length > 1 && <path d={toPath(mainNodes)} fill="none" stroke="#6a9e78" strokeWidth={1.5} />}
      {mainNodes.map(n => (
        <circle
          key={n.candidate}
          cx={x(n.iteration)}
          cy={y(n.scores.accuracy)}
          r={3.5}
          fill="#6a9e78"
          style={{ cursor: 'pointer' }}
          onMouseEnter={() => setHovered(n.candidate)}
          onMouseLeave={() => setHovered(null)}
        />
      ))}

      {/* Fork line */}
      {forkPath && <path d={forkPath} fill="none" stroke="#8878a8" strokeWidth={1.5} />}
      {forkNodes.map(n => (
        <circle
          key={n.candidate}
          cx={x(n.iteration)}
          cy={y(n.scores.accuracy)}
          r={3.5}
          fill="#8878a8"
          style={{ cursor: 'pointer' }}
          onMouseEnter={() => setHovered(n.candidate)}
          onMouseLeave={() => setHovered(null)}
        />
      ))}

      {/* Rejected dots */}
      {rejectedNodes.map(n => (
        <circle
          key={n.candidate}
          cx={x(n.iteration)}
          cy={y(n.scores.accuracy)}
          r={3.5}
          fill="#b06068"
          style={{ cursor: 'pointer' }}
          onMouseEnter={() => setHovered(n.candidate)}
          onMouseLeave={() => setHovered(null)}
        />
      ))}

      {/* Best dot with glow */}
      {bestNode && (
        <>
          <circle cx={x(bestNode.iteration)} cy={y(bestNode.scores.accuracy)} r={8} fill="#7ab8ad" opacity={0.1} />
          <circle
            cx={x(bestNode.iteration)}
            cy={y(bestNode.scores.accuracy)}
            r={4.5}
            fill="#7ab8ad"
            style={{ cursor: 'pointer' }}
            onMouseEnter={() => setHovered(bestNode.candidate)}
            onMouseLeave={() => setHovered(null)}
          />
        </>
      )}

      {/* Hover tooltip */}
      {hoveredNode && (() => {
        const tx = x(hoveredNode.iteration);
        const ty = y(hoveredNode.scores.accuracy);
        const name = hoveredNode.candidate.length > 20
          ? hoveredNode.candidate.slice(0, 18) + '...'
          : hoveredNode.candidate;
        const label = `${name}  ${hoveredNode.scores.accuracy.toFixed(3)}`;
        const flipped = tx > width - 140;
        const anchor = flipped ? 'end' : 'start';
        const dx = flipped ? -10 : 10;
        return (
          <g>
            <rect
              x={tx + dx + (flipped ? -label.length * 5.2 - 8 : -4)}
              y={ty - 18}
              width={label.length * 5.2 + 12}
              height={18}
              rx={3}
              fill="#16161e"
              stroke="#22222e"
              strokeWidth={1}
            />
            <text
              x={tx + dx}
              y={ty - 6}
              textAnchor={anchor}
              fill="#c8c8d0"
              fontSize={8.5}
              fontFamily="monospace"
            >
              {label}
            </text>
          </g>
        );
      })()}

      {/* Legend */}
      <circle cx={width - 130} cy={12} r={3} fill="#6a9e78" />
      <text x={width - 123} y={15} fill="#707084" fontSize={8} fontFamily="monospace">MAIN</text>
      <circle cx={width - 88} cy={12} r={3} fill="#8878a8" />
      <text x={width - 81} y={15} fill="#707084" fontSize={8} fontFamily="monospace">FORK</text>
      <line x1={width - 55} x2={width - 40} y1={12} y2={12} stroke="#7ab8ad" strokeWidth={1.5} strokeDasharray="4 3" opacity={0.5} />
      <text x={width - 36} y={15} fill="#707084" fontSize={8} fontFamily="monospace">PARETO</text>

      {/* ── Per-Task Breakdown Bar Chart ── */}

      {/* Section title */}
      <text
        x={pad.left}
        y={barTop + 4}
        fill="#707084"
        fontSize={8}
        fontFamily="monospace"
        letterSpacing="0.06em"
      >
        TASK BREAKDOWN{bestNode ? ` — ${bestNode.candidate}` : ''}
      </text>

      {taskBreakdown.length === 0 && (
        <text
          x={pad.left}
          y={barTop + 26}
          fill="#4e4e5c"
          fontSize={9}
          fontFamily="monospace"
        >
          No per-task scores emitted for this run yet.
        </text>
      )}

      {taskBreakdown.map((task, i) => {
        const by = barTop + 18 + i * (barH + barGap);
        const bw = task.score * barMaxW;
        return (
          <g key={task.key}>
            {/* Label */}
            <text
              x={barLeft - 6}
              y={by + barH / 2 + 3}
              textAnchor="end"
              fill="#707084"
              fontSize={8}
              fontFamily="monospace"
            >
              {task.label}
            </text>
            {/* Background bar */}
            <rect x={barLeft} y={by} width={barMaxW} height={barH} rx={2} fill="#1c1c26" />
            {/* Value bar */}
            <rect x={barLeft} y={by} width={bw} height={barH} rx={2} fill={barColor(task.score)} />
            {/* Score label */}
            <text
              x={barLeft + bw + 6}
              y={by + barH / 2 + 3}
              fill="#4e4e5c"
              fontSize={8}
              fontFamily="monospace"
            >
              {task.score.toFixed(1)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
