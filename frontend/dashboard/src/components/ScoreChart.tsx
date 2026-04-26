'use client';
import { useDashboard } from '@/lib/state';

export function ScoreChart() {
  const { tree } = useDashboard();

  const mainNodes = tree.filter(n => !n.isForkBranch).sort((a, b) => a.iteration - b.iteration);
  const forkNodes = tree.filter(n => n.isForkBranch).sort((a, b) => a.iteration - b.iteration);
  const rejectedNodes = tree.filter(n => n.status === 'rejected');
  const bestNode = tree.find(n => n.status === 'best');

  const width = 360;
  const height = 200;
  const pad = { top: 20, right: 20, bottom: 30, left: 45 };
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;

  const xMin = 0, xMax = 4;
  const yMin = 0.58, yMax = 0.90;
  const x = (v: number) => pad.left + ((v - xMin) / (xMax - xMin)) * w;
  const y = (v: number) => pad.top + h - ((v - yMin) / (yMax - yMin)) * h;

  const toPath = (nodes: typeof mainNodes) =>
    nodes.map((n, i) => `${i === 0 ? 'M' : 'L'} ${x(n.iteration)} ${y(n.scores.accuracy)}`).join(' ');

  // Fork line starts from the parent node on the main branch
  const forkParent = mainNodes.find(n => n.candidate === forkNodes[0]?.parent_candidate_name);
  const forkPath = forkParent
    ? `M ${x(forkParent.iteration)} ${y(forkParent.scores.accuracy)} ` + forkNodes.map(n => `L ${x(n.iteration)} ${y(n.scores.accuracy)}`).join(' ')
    : '';

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-[200px]">
      {/* Grid */}
      {[0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90].map(v => (
        <line key={v} x1={pad.left} x2={width - pad.right} y1={y(v)} y2={y(v)} stroke="#1c1c26" strokeWidth={1} />
      ))}

      {/* Baseline */}
      <line x1={pad.left} x2={width - pad.right} y1={y(0.62)} y2={y(0.62)} stroke="#303040" strokeWidth={1} strokeDasharray="4 4" />

      {/* Y axis labels */}
      {[0.60, 0.70, 0.80, 0.90].map(v => (
        <text key={v} x={pad.left - 8} y={y(v) + 3} textAnchor="end" fill="#4e4e5c" fontSize={9} fontFamily="monospace">{v.toFixed(2)}</text>
      ))}

      {/* X axis labels */}
      {[0, 1, 2, 3, 4].map(v => (
        <text key={v} x={x(v)} y={height - 8} textAnchor="middle" fill="#4e4e5c" fontSize={9} fontFamily="monospace">{v}</text>
      ))}

      {/* Main line */}
      {mainNodes.length > 1 && <path d={toPath(mainNodes)} fill="none" stroke="#6a9e78" strokeWidth={1.5} />}
      {mainNodes.map(n => (
        <circle key={n.candidate} cx={x(n.iteration)} cy={y(n.scores.accuracy)} r={3.5} fill="#6a9e78" />
      ))}

      {/* Fork line */}
      {forkPath && <path d={forkPath} fill="none" stroke="#8878a8" strokeWidth={1.5} />}
      {forkNodes.map(n => (
        <circle key={n.candidate} cx={x(n.iteration)} cy={y(n.scores.accuracy)} r={3.5} fill="#8878a8" />
      ))}

      {/* Rejected dots */}
      {rejectedNodes.map(n => (
        <circle key={n.candidate} cx={x(n.iteration)} cy={y(n.scores.accuracy)} r={3.5} fill="#b06068" />
      ))}

      {/* Best dot with glow */}
      {bestNode && (
        <>
          <circle cx={x(bestNode.iteration)} cy={y(bestNode.scores.accuracy)} r={8} fill="#7ab8ad" opacity={0.1} />
          <circle cx={x(bestNode.iteration)} cy={y(bestNode.scores.accuracy)} r={4.5} fill="#7ab8ad" />
        </>
      )}

      {/* Legend */}
      <circle cx={width - 90} cy={12} r={3} fill="#6a9e78" />
      <text x={width - 83} y={15} fill="#707084" fontSize={8} fontFamily="monospace">MAIN</text>
      <circle cx={width - 50} cy={12} r={3} fill="#8878a8" />
      <text x={width - 43} y={15} fill="#707084" fontSize={8} fontFamily="monospace">FORK</text>
    </svg>
  );
}
