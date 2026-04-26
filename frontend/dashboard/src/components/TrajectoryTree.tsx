'use client';
import { useRef, useEffect, useState } from 'react';
import * as d3 from 'd3';
import { useDashboard, useDashboardDispatch } from '@/lib/state';
import { ForkModal } from './ForkModal';
import type { TreeNode } from '@/lib/types';

const STATUS_STYLES: Record<string, { border: string; bg: string; text: string }> = {
  seed: { border: '#32323e', bg: '#16161e', text: '#c8c8d0' },
  accepted: { border: '#6a9e78', bg: '#111816', text: '#c8c8d0' },
  rejected: { border: '#b06068', bg: '#181114', text: '#c8c8d0' },
  best: { border: '#7ab8ad', bg: '#111616', text: '#c8c8d0' },
  fork: { border: '#8878a8', bg: '#141218', text: '#c8c8d0' },
};

const NODE_W = 200;
const NODE_H = 72;
const GAP_Y = 32;
const GAP_X = 16;

type LayoutNode = TreeNode & { x: number; y: number };

function layoutTree(nodes: TreeNode[]): LayoutNode[] {
  if (nodes.length === 0) return [];

  const byName = new Map(nodes.map(n => [n.candidate, n]));
  const root = nodes.find(n => !n.parent_candidate_name);
  if (!root) return [];

  const laid: LayoutNode[] = [];
  const colWidth = NODE_W + GAP_X;

  function place(name: string, depth: number, column: number) {
    const node = byName.get(name);
    if (!node) return;

    laid.push({
      ...node,
      x: column * colWidth,
      y: depth * (NODE_H + GAP_Y),
    });

    const children = nodes.filter(n => n.parent_candidate_name === name);
    if (children.length === 1) {
      place(children[0].candidate, depth + 1, column);
    } else if (children.length > 1) {
      const mainChildren = children.filter(c => !c.isForkBranch && c.status !== 'rejected');
      const forkChildren = children.filter(c => c.isForkBranch);
      const rejectedChildren = children.filter(c => c.status === 'rejected');
      const ordered = [...mainChildren, ...forkChildren, ...rejectedChildren];

      ordered.forEach((child, i) => {
        place(child.candidate, depth + 1, column + i);
      });
    }
  }

  place(root.candidate, 0, 0);
  return laid;
}

export function TrajectoryTree() {
  const svgRef = useRef<SVGSVGElement>(null);
  const { tree, selectedNode, forkEvents } = useDashboard();
  const dispatch = useDashboardDispatch();
  const [forkTarget, setForkTarget] = useState<{ candidate: string; checkpointId: string } | null>(null);

  useEffect(() => {
    if (!svgRef.current || tree.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const laid = layoutTree(tree);
    if (laid.length === 0) return;

    const byName = new Map(laid.map(n => [n.candidate, n]));

    const maxX = Math.max(...laid.map(n => n.x)) + NODE_W + 30;

    // Dot grid background
    const defs = svg.append('defs');
    defs.append('pattern')
      .attr('id', 'dot-grid')
      .attr('width', 24)
      .attr('height', 24)
      .attr('patternUnits', 'userSpaceOnUse')
      .append('circle')
      .attr('cx', 12)
      .attr('cy', 12)
      .attr('r', 1.2)
      .attr('fill', '#1c1c26');

    svg.append('rect')
      .attr('width', '100%')
      .attr('height', '100%')
      .attr('fill', 'url(#dot-grid)');

    const g = svg.append('g');

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on('zoom', (event) => {
        g.attr('transform', event.transform.toString());
      });

    svg.call(zoom);

    const containerWidth = svgRef.current.clientWidth || 400;
    const padding = 20;
    const initialScale = Math.min((containerWidth - padding * 2) / maxX, 1.5);
    const tx = (containerWidth - maxX * initialScale) / 2;
    const ty = padding;
    const initialTransform = d3.zoomIdentity.translate(tx, ty).scale(initialScale);
    svg.call(zoom.transform, initialTransform);

    // Draw edges
    for (const node of laid) {
      if (!node.parent_candidate_name) continue;
      const parent = byName.get(node.parent_candidate_name);
      if (!parent) continue;

      const color = node.isForkBranch ? '#8878a8' : node.status === 'rejected' ? '#b06068' : '#6a9e78';
      g.append('line')
        .attr('x1', parent.x + NODE_W / 2)
        .attr('y1', parent.y + NODE_H)
        .attr('x2', node.x + NODE_W / 2)
        .attr('y2', node.y)
        .attr('stroke', color)
        .attr('stroke-width', 1.5)
        .attr('opacity', node.status === 'rejected' ? 0.35 : 0.6);
    }

    // Fork zone
    if (forkEvents.length > 0) {
      const forkNode = laid.find(n => n.candidate === forkEvents[0].parentCandidate);
      if (forkNode) {
        const zy = forkNode.y + NODE_H + GAP_Y / 2 - 12;
        g.append('rect')
          .attr('x', 0).attr('y', zy)
          .attr('width', maxX - 30).attr('height', 24)
          .attr('fill', '#8878a8').attr('opacity', 0.06)
          .attr('rx', 4);
        g.append('text')
          .attr('x', (maxX - 30) / 2).attr('y', zy + 16)
          .attr('text-anchor', 'middle')
          .attr('fill', '#707084').attr('font-size', 9)
          .attr('font-family', 'monospace')
          .text('⑂ FORK');
      }
    }

    // Draw nodes
    for (const node of laid) {
      const style = STATUS_STYLES[node.status] || STATUS_STYLES.seed;
      const isSelected = selectedNode === node.candidate;
      const opacity = node.status === 'rejected' ? 0.35 : 1;

      const nodeG = g.append('g')
        .attr('transform', `translate(${node.x}, ${node.y})`)
        .attr('opacity', opacity)
        .attr('cursor', 'pointer')
        .attr('data-testid', 'trajectory-node')
        .on('click', () => dispatch({ type: 'SELECT_NODE', payload: node.candidate }))
        .on('contextmenu', (event: MouseEvent) => {
          event.preventDefault();
          const checkpointId = node.checkpointId || `demo-${node.candidate}`;
          setForkTarget({ candidate: node.candidate, checkpointId });
        });

      // Best glow
      if (node.status === 'best') {
        nodeG.append('rect')
          .attr('x', -4).attr('y', -4)
          .attr('width', NODE_W + 8).attr('height', NODE_H + 8)
          .attr('rx', 8).attr('fill', '#7ab8ad').attr('opacity', 0.08);
      }

      // Background
      nodeG.append('rect')
        .attr('width', NODE_W).attr('height', NODE_H)
        .attr('rx', 4).attr('fill', style.bg)
        .attr('stroke', isSelected ? '#7ab8ad' : style.border)
        .attr('stroke-width', isSelected ? 2 : 1);

      // Iteration label
      nodeG.append('text')
        .attr('x', 10).attr('y', 16)
        .attr('fill', '#303040').attr('font-size', 8)
        .attr('font-family', 'monospace')
        .text(`ITER ${node.iteration}${node.isForkBranch ? "'" : ''}`);

      // Candidate name
      nodeG.append('text')
        .attr('x', 10).attr('y', 34)
        .attr('fill', style.text).attr('font-size', 12)
        .attr('font-family', 'monospace')
        .attr('font-weight', 500)
        .text(node.candidate.length > 22 ? node.candidate.slice(0, 22) + '…' : node.candidate);

      // Score
      nodeG.append('text')
        .attr('x', 10).attr('y', 56)
        .attr('fill', style.border).attr('font-size', 15)
        .attr('font-family', 'monospace')
        .attr('font-weight', 600)
        .text(node.scores.accuracy.toFixed(2));

      // Delta
      if (node.delta !== null) {
        const deltaColor = node.delta >= 0 ? '#6a9e78' : '#b06068';
        const deltaText = node.delta >= 0 ? `+${node.delta.toFixed(2)}` : node.delta.toFixed(2);
        nodeG.append('text')
          .attr('x', 58).attr('y', 56)
          .attr('fill', deltaColor).attr('font-size', 10)
          .attr('font-family', 'monospace')
          .text(deltaText);
      }

      // Status badge
      if (node.status === 'best') {
        nodeG.append('text')
          .attr('x', NODE_W - 10).attr('y', 16)
          .attr('text-anchor', 'end')
          .attr('fill', '#7ab8ad').attr('font-size', 8)
          .attr('font-family', 'monospace')
          .attr('font-weight', 600)
          .text('★ BEST');
      } else if (node.status === 'rejected') {
        nodeG.append('text')
          .attr('x', NODE_W - 10).attr('y', 16)
          .attr('text-anchor', 'end')
          .attr('fill', '#b06068').attr('font-size', 8)
          .attr('font-family', 'monospace')
          .attr('font-weight', 600)
          .text('REJECTED');
      } else if (node.status === 'accepted') {
        nodeG.append('text')
          .attr('x', NODE_W - 10).attr('y', 16)
          .attr('text-anchor', 'end')
          .attr('fill', '#6a9e78').attr('font-size', 8)
          .attr('font-family', 'monospace')
          .attr('font-weight', 600)
          .text('ACCEPTED');
      }
    }
  }, [tree, selectedNode, forkEvents, dispatch]);

  return (
    <>
      <div className="flex-1 flex flex-col bg-panel rounded overflow-hidden min-h-0">
        <div className="h-11 flex items-center px-6 bg-header border-b border-border shrink-0">
          <span className="text-[10px] font-semibold text-text-hi uppercase tracking-wide">◆ Trajectory</span>
        </div>
        <div className="flex-1 overflow-hidden">
          <svg ref={svgRef} className="w-full h-full" />
        </div>
      </div>
      {forkTarget && (
        <ForkModal
          candidateName={forkTarget.candidate}
          checkpointId={forkTarget.checkpointId}
          onClose={() => setForkTarget(null)}
        />
      )}
    </>
  );
}
