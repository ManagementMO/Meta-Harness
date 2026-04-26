'use client';
import {
  ReactFlow,
  Background,
  type Node,
  type Edge,
  Position,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

const nodeDefaults = {
  style: {
    background: '#16161e',
    color: '#c8c8d0',
    border: '1px solid #22222e',
    borderRadius: '4px',
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: '11px',
    padding: '8px 14px',
  },
};

const activeNodeStyle = {
  ...nodeDefaults.style,
  border: '1px solid #7ab8ad',
  boxShadow: '0 0 8px rgba(122,184,173,0.1)',
};

const innerNodeStyle = {
  ...nodeDefaults.style,
  border: '1px solid #32323e',
  fontSize: '10px',
};

const initialNodes: Node[] = [
  // Outer loop
  { id: 'propose', position: { x: 50, y: 50 }, data: { label: 'PROPOSE' }, style: activeNodeStyle, sourcePosition: Position.Right, targetPosition: Position.Left },
  { id: 'validate', position: { x: 220, y: 50 }, data: { label: 'VALIDATE' }, ...nodeDefaults, sourcePosition: Position.Right, targetPosition: Position.Left },
  { id: 'benchmark', position: { x: 390, y: 50 }, data: { label: 'BENCHMARK' }, ...nodeDefaults, sourcePosition: Position.Right, targetPosition: Position.Left },
  { id: 'frontier', position: { x: 560, y: 50 }, data: { label: 'UPDATE FRONTIER' }, ...nodeDefaults, sourcePosition: Position.Right, targetPosition: Position.Left },
  { id: 'fork-check', position: { x: 730, y: 43 }, data: { label: '⑂' }, style: { ...nodeDefaults.style, border: '1px solid #8878a8', background: '#141218', width: 36, height: 36, padding: '4px', textAlign: 'center' as const, fontSize: '14px' }, sourcePosition: Position.Bottom, targetPosition: Position.Left },

  // Inner loop (below benchmark)
  { id: 'orient', position: { x: 320, y: 160 }, data: { label: 'Orient' }, style: innerNodeStyle, sourcePosition: Position.Right, targetPosition: Position.Left },
  { id: 'plan', position: { x: 420, y: 160 }, data: { label: 'Plan' }, style: innerNodeStyle, sourcePosition: Position.Right, targetPosition: Position.Left },
  { id: 'act', position: { x: 510, y: 160 }, data: { label: 'Act' }, style: innerNodeStyle, sourcePosition: Position.Right, targetPosition: Position.Left },
  { id: 'verify', position: { x: 600, y: 160 }, data: { label: 'Verify' }, style: innerNodeStyle, sourcePosition: Position.Right, targetPosition: Position.Left },
  { id: 'submit', position: { x: 700, y: 160 }, data: { label: 'Submit' }, style: innerNodeStyle, sourcePosition: Position.Right, targetPosition: Position.Left },

  // Labels
  { id: 'label-outer', position: { x: 50, y: 10 }, data: { label: 'OUTER LOOP' }, style: { background: 'transparent', border: 'none', color: '#707084', fontSize: '9px', fontFamily: "'JetBrains Mono', monospace", letterSpacing: '1px' }, draggable: false },
  { id: 'label-inner', position: { x: 320, y: 130 }, data: { label: 'INNER LOOP (per candidate)' }, style: { background: 'transparent', border: 'none', color: '#707084', fontSize: '9px', fontFamily: "'JetBrains Mono', monospace", letterSpacing: '1px' }, draggable: false },
];

const edgeDefaults = {
  style: { stroke: '#32323e', strokeWidth: 1.5 },
  markerEnd: { type: MarkerType.ArrowClosed, color: '#32323e', width: 12, height: 12 },
  animated: false,
};

const initialEdges: Edge[] = [
  // Outer loop flow
  { id: 'e-propose-validate', source: 'propose', target: 'validate', ...edgeDefaults },
  { id: 'e-validate-benchmark', source: 'validate', target: 'benchmark', ...edgeDefaults },
  { id: 'e-benchmark-frontier', source: 'benchmark', target: 'frontier', ...edgeDefaults },
  { id: 'e-frontier-fork', source: 'frontier', target: 'fork-check', ...edgeDefaults },
  // Loop back
  { id: 'e-fork-propose', source: 'fork-check', target: 'propose', style: { stroke: '#8878a8', strokeWidth: 1.5, strokeDasharray: '4 4' }, markerEnd: { type: MarkerType.ArrowClosed, color: '#8878a8', width: 12, height: 12 }, type: 'smoothstep', label: 'fork', labelStyle: { fill: '#8878a8', fontSize: 8, fontFamily: "'JetBrains Mono', monospace" } },
  { id: 'e-frontier-propose', source: 'frontier', target: 'propose', style: { stroke: '#6a9e78', strokeWidth: 1.5 }, markerEnd: { type: MarkerType.ArrowClosed, color: '#6a9e78', width: 12, height: 12 }, type: 'smoothstep', label: 'next iter', labelStyle: { fill: '#6a9e78', fontSize: 8, fontFamily: "'JetBrains Mono', monospace" } },

  // Benchmark → inner loop
  { id: 'e-benchmark-orient', source: 'benchmark', target: 'orient', style: { stroke: '#32323e', strokeWidth: 1, strokeDasharray: '3 3' }, markerEnd: { type: MarkerType.ArrowClosed, color: '#32323e', width: 10, height: 10 } },

  // Inner loop flow
  { id: 'e-orient-plan', source: 'orient', target: 'plan', ...edgeDefaults },
  { id: 'e-plan-act', source: 'plan', target: 'act', ...edgeDefaults },
  { id: 'e-act-verify', source: 'act', target: 'verify', ...edgeDefaults },
  { id: 'e-verify-submit', source: 'verify', target: 'submit', ...edgeDefaults },
  // Retry loop
  { id: 'e-verify-act', source: 'verify', target: 'act', style: { stroke: '#b09868', strokeWidth: 1, strokeDasharray: '3 3' }, markerEnd: { type: MarkerType.ArrowClosed, color: '#b09868', width: 10, height: 10 }, type: 'smoothstep', label: 'retry', labelStyle: { fill: '#b09868', fontSize: 8, fontFamily: "'JetBrains Mono', monospace" } },
];

export function StateGraph() {
  return (
    <div className="w-full h-full" style={{ minHeight: 250 }}>
      <ReactFlow
        nodes={initialNodes}
        edges={initialEdges}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#1c1c26" gap={20} size={1} />
      </ReactFlow>
    </div>
  );
}
