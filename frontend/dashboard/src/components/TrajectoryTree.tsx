"use client";

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getSmoothStepPath,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useDashboard, useDashboardDispatch } from "@/lib/state";
import { ForkModal } from "./ForkModal";
import { resolveCheckpointForNode } from "@/lib/api";
import { GlassPanel, PanelHeader, PanelTitle } from "./ui/GlassPanel";
import { EmptyState } from "./ui/EmptyState";
import { IconGitBranch, IconTreeStructure } from "./ui/icons";
import { cn } from "@/lib/cn";
import type { TreeNode } from "@/lib/types";

const NODE_W = 188;
const NODE_H = 72;
const GAP_X = 24;
const GAP_Y = 40;

type ForkTarget = { candidate: string; checkpointId: string; parentThreadId?: string };

type CandidateData = {
  node: TreeNode;
  isSelected: boolean;
  onFork: (node: TreeNode) => void;
  [key: string]: unknown;
};

type CandidateNode = Node<CandidateData, "candidate">;

type EdgeTone = "seed" | "accepted" | "rejected" | "fork" | "best";

type TraceData = { tone: EdgeTone; [key: string]: unknown };
type TraceEdgeType = Edge<TraceData, "trace">;

function nodeKey(node: TreeNode): string {
  return node.candidateId ?? node.candidate;
}

function layoutTree(nodes: TreeNode[]): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  if (nodes.length === 0) return positions;

  const byKey = new Map(nodes.map((node) => [nodeKey(node), node]));
  const root = nodes.find((node) => !node.parent_candidate_name && !node.parentIds?.length);
  if (!root) return positions;

  const colWidth = NODE_W + GAP_X;

  function place(key: string, depth: number, column: number) {
    const node = byKey.get(key);
    if (!node || positions.has(key)) return;

    positions.set(key, { x: column * colWidth, y: depth * (NODE_H + GAP_Y) });

    const children = nodes.filter(
      (child) =>
        child.parentIds?.includes(key) ||
        (!child.parentIds?.length && child.parent_candidate_name === node.candidate),
    );
    if (children.length === 1) {
      place(nodeKey(children[0]), depth + 1, column);
    } else if (children.length > 1) {
      const mainChildren = children.filter((c) => !c.isForkBranch && c.status !== "rejected");
      const forkChildren = children.filter((c) => c.isForkBranch);
      const rejectedChildren = children.filter((c) => c.status === "rejected" && !c.isForkBranch);
      const ordered = [...mainChildren, ...forkChildren, ...rejectedChildren];
      ordered.forEach((child, i) => {
        place(nodeKey(child), depth + 1, column + i);
      });
    }
  }

  place(nodeKey(root), 0, 0);
  return positions;
}

/** Candidate lineage of the current best — the path that traces with light. */
function bestLineage(nodes: TreeNode[]): Set<string> {
  const byKey = new Map(nodes.map((node) => [nodeKey(node), node]));
  const byName = new Map(nodes.map((node) => [node.candidate, node]));
  const lineage = new Set<string>();
  let cursor = nodes.find((n) => n.status === "best");
  let guard = 0;
  while (cursor && guard < 64) {
    lineage.add(nodeKey(cursor));
    const parent = cursor.parentIds?.[0]
      ? byKey.get(cursor.parentIds[0])
      : cursor.parent_candidate_name
        ? byName.get(cursor.parent_candidate_name)
        : undefined;
    cursor = parent;
    guard += 1;
  }
  return lineage;
}

const STATUS_META: Record<
  TreeNode["status"],
  { border: string; label: string | null; labelClass: string; score: string }
> = {
  seed: { border: "border-white/12", label: "SEED", labelClass: "text-ink-ghost", score: "text-ink" },
  accepted: { border: "border-moss/35", label: "ACCEPTED", labelClass: "text-moss", score: "text-moss" },
  rejected: { border: "border-ember/30", label: "REJECTED", labelClass: "text-ember", score: "text-ember" },
  best: { border: "border-frost/60", label: "BEST", labelClass: "text-frost-bright", score: "text-frost-bright" },
  fork: { border: "border-iris/35", label: "FORK", labelClass: "text-iris", score: "text-iris" },
};

const CandidateNodeView = memo(function CandidateNodeView({ data }: NodeProps<CandidateNode>) {
  const { node, isSelected, onFork } = data;
  const meta = STATUS_META[node.status] ?? STATUS_META.seed;

  return (
    <div
      data-testid="trajectory-node"
      className={cn(
        "group relative rounded-[10px] border bg-node specular-top cursor-pointer select-none",
        "transition-[border-color,box-shadow,opacity] duration-200 ease-[var(--ease-glass)]",
        meta.border,
        node.status === "rejected" && "opacity-45 hover:opacity-80",
        node.status === "best" && "shadow-[0_0_24px_rgba(255,255,255,0.10)]",
        isSelected && "border-frost/80 shadow-[0_0_0_1px_rgba(232,238,245,0.35),0_0_20px_rgba(255,255,255,0.08)]",
      )}
      style={{ width: NODE_W, height: NODE_H }}
    >
      <Handle type="target" position={Position.Top} className="!opacity-0 !pointer-events-none !w-px !h-px !min-w-0 !min-h-0 !border-0 !bg-transparent" />
      <Handle type="source" position={Position.Bottom} className="!opacity-0 !pointer-events-none !w-px !h-px !min-w-0 !min-h-0 !border-0 !bg-transparent" />

      <div className="px-3 pt-2 flex items-start justify-between gap-2">
        <span className="font-mono text-[9px] tracking-[0.12em] text-ink-ghost">
          ITER {node.iteration}
          {node.isForkBranch ? "′" : ""}
        </span>
        {meta.label && node.status !== "seed" && (
          <span className={cn("font-mono text-[8.5px] tracking-[0.14em] font-medium", meta.labelClass)}>
            {meta.label}
          </span>
        )}
      </div>

      <div className="px-3 mt-0.5 font-mono text-[11px] leading-[1.35] text-ink truncate" title={node.candidate}>
        {node.candidate}
      </div>

      <div className="px-3 mt-1 flex items-baseline gap-2 font-mono tabular-nums">
        <span className={cn("text-[14px] font-medium", meta.score)}>{node.scores.accuracy.toFixed(2)}</span>
        {node.delta !== null && (
          <span className={cn("text-[9.5px]", node.delta >= 0 ? "text-moss" : "text-ember")}>
            {node.delta >= 0 ? "+" : ""}
            {node.delta.toFixed(2)}
          </span>
        )}
        {node.scores.synthetic && <span className="text-[8.5px] text-sand/80 tracking-[0.1em]">SYN</span>}
      </div>

      <button
        aria-label={`Fork from ${node.candidate}`}
        onClick={(event) => {
          event.stopPropagation();
          onFork(node);
        }}
        className={cn(
          "absolute right-2 bottom-2 flex items-center justify-center w-6 h-5 rounded-[5px]",
          "border border-iris/30 bg-iris/10 text-iris opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
          "transition-opacity duration-150 cursor-pointer hover:bg-iris/20",
        )}
      >
        <IconGitBranch size={11} />
      </button>
    </div>
  );
});

const EDGE_STYLE: Record<EdgeTone, { stroke: string; opacity: number; width: number; glow?: boolean }> = {
  seed: { stroke: "rgba(233,237,242,0.18)", opacity: 1, width: 1.25 },
  accepted: { stroke: "rgba(233,237,242,0.34)", opacity: 1, width: 1.25 },
  rejected: { stroke: "rgba(179,145,153,0.3)", opacity: 1, width: 1.25 },
  fork: { stroke: "rgba(158,155,179,0.45)", opacity: 1, width: 1.25 },
  best: { stroke: "rgba(255,255,255,0.75)", opacity: 1, width: 1.5, glow: true },
};

const TraceEdgeView = memo(function TraceEdgeView({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps<TraceEdgeType>) {
  const [path] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 10,
  });
  const style = EDGE_STYLE[data?.tone ?? "seed"];
  return (
    <BaseEdge
      path={path}
      className="trace-edge"
      pathLength={1}
      style={{
        stroke: style.stroke,
        strokeWidth: style.width,
        opacity: style.opacity,
        filter: style.glow ? "drop-shadow(0 0 4px rgba(255,255,255,0.35))" : undefined,
      }}
    />
  );
});

const nodeTypes = { candidate: CandidateNodeView };
const edgeTypes = { trace: TraceEdgeView };

function TrajectoryFlow() {
  const params = useParams<{ run_id: string }>();
  const { tree, selectedNode, forkEvents, mode, run } = useDashboard();
  const dispatch = useDashboardDispatch();
  const [forkTarget, setForkTarget] = useState<ForkTarget | null>(null);
  const { fitView, getViewport, setCenter } = useReactFlow();
  const fitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // When a fork lands, focus its branch node.
  useEffect(() => {
    const latestFork = forkEvents.at(-1);
    if (!latestFork) return;
    const rawBranchId = latestFork.branchId.trim();
    const normalizedBranchId = rawBranchId.replace(/^fork\./, "");
    const branchNode = tree.find((node) => {
      const threadId = node.threadId ?? "";
      return threadId.includes(`.fork.${normalizedBranchId}`) || threadId.includes(rawBranchId);
    });
    if (!branchNode || selectedNode === nodeKey(branchNode)) return;
    dispatch({ type: "SELECT_NODE", payload: nodeKey(branchNode) });
  }, [tree, forkEvents, selectedNode, dispatch]);

  const requestFork = useCallback(
    async (node: TreeNode) => {
      let checkpointId = node.checkpointId ?? undefined;
      if (!checkpointId && mode === "mock") {
        checkpointId = run?.checkpointId ?? undefined;
      }
      if (!checkpointId && mode === "live") {
        const resolved = await resolveCheckpointForNode(params.run_id, {
          candidate: node.candidate,
          candidateId: node.candidateId,
          iteration: node.iteration,
          threadId: node.threadId,
        }).catch(() => null);
        checkpointId = resolved ?? undefined;
        if (checkpointId) {
          dispatch({
            type: "SET_CHECKPOINT_ID",
            payload: { candidate: nodeKey(node), checkpointId },
          });
        }
      }
      if (!checkpointId) {
        dispatch({
          type: "ADD_LOG_ENTRY",
          payload: {
            id: `fork-pending-${Date.now()}`,
            timestamp: new Date().toISOString(),
            tag: "fork",
            text: `${node.candidate} has no checkpoint yet; this candidate may not be persisted in checkpoints yet`,
            candidateName: node.candidate,
          },
        });
        return;
      }
      setForkTarget({
        candidate: node.candidate,
        checkpointId,
        parentThreadId: node.threadId,
      });
    },
    [dispatch, mode, params.run_id, run?.checkpointId],
  );

  const { nodes, edges } = useMemo(() => {
    const positions = layoutTree(tree);
    const lineage = bestLineage(tree);
    const byKey = new Map(tree.map((node) => [nodeKey(node), node]));
    const byName = new Map(tree.map((node) => [node.candidate, node]));

    const nodes: CandidateNode[] = tree
      .filter((node) => positions.has(nodeKey(node)))
      .map((node) => {
        const key = nodeKey(node);
        const pos = positions.get(key)!;
        return {
          id: key,
          type: "candidate" as const,
          position: pos,
          width: NODE_W,
          height: NODE_H,
          data: { node, isSelected: selectedNode === key, onFork: requestFork },
        };
      });

    const edges: TraceEdgeType[] = [];
    for (const node of tree) {
      const key = nodeKey(node);
      if (!positions.has(key)) continue;
      const parent = node.parentIds?.[0]
        ? byKey.get(node.parentIds[0])
        : node.parent_candidate_name
          ? byName.get(node.parent_candidate_name)
          : undefined;
      if (!parent) continue;
      const parentKey = nodeKey(parent);
      if (!positions.has(parentKey)) continue;

      const tone: EdgeTone =
        lineage.has(key) && lineage.has(parentKey)
          ? "best"
          : node.isForkBranch
            ? "fork"
            : node.status === "rejected"
              ? "rejected"
              : node.status === "accepted"
                ? "accepted"
                : "seed";

      edges.push({
        id: `${parentKey}->${key}`,
        source: parentKey,
        target: key,
        type: "trace" as const,
        data: { tone },
      });
    }
    return { nodes, edges };
  }, [tree, selectedNode, requestFork]);

  // Refit as the tree grows — debounced so streams don't thrash the camera.
  // Never fit below readable zoom: clamp and recentre on the focus node instead.
  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;
  useEffect(() => {
    if (nodes.length === 0) return;
    if (fitTimer.current) clearTimeout(fitTimer.current);
    fitTimer.current = setTimeout(async () => {
      await fitView({ padding: 0.15, maxZoom: 1.05, duration: 300 });
      const { zoom } = getViewport();
      if (zoom < 0.72) {
        const latest = nodesRef.current;
        const focus =
          latest.find((n) => n.data.isSelected) ??
          latest.find((n) => n.data.node.status === "best") ??
          latest[latest.length - 1];
        if (focus) {
          void setCenter(focus.position.x + NODE_W / 2, focus.position.y + NODE_H / 2, {
            zoom: 0.82,
            duration: 300,
          });
        }
      }
    }, 140);
    return () => {
      if (fitTimer.current) clearTimeout(fitTimer.current);
    };
  }, [nodes.length, fitView, getViewport, setCenter]);

  return (
    <>
      <div className="flex-1 min-h-0 relative">
        {tree.length === 0 && (
          <div className="absolute inset-0 z-10 flex items-center justify-center">
            <EmptyState icon={<IconTreeStructure size={20} />} title="Awaiting first candidate">
              The evolution tree draws itself as candidates stream in.
            </EmptyState>
          </div>
        )}
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodeClick={(_, flowNode) => dispatch({ type: "SELECT_NODE", payload: flowNode.id })}
          onNodeContextMenu={(event, flowNode) => {
            event.preventDefault();
            const data = flowNode.data as CandidateData;
            void requestFork(data.node);
          }}
          fitView
          fitViewOptions={{ padding: 0.18, maxZoom: 1.1 }}
          minZoom={0.25}
          maxZoom={1.75}
          nodesDraggable={false}
          nodesConnectable={false}
          edgesFocusable={false}
          proOptions={{ hideAttribution: true }}
          className="!bg-transparent"
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="rgba(255,255,255,0.05)" />
          <Controls position="bottom-right" showInteractive={false} />
        </ReactFlow>
      </div>
      {forkTarget && (
        <ForkModal
          candidateName={forkTarget.candidate}
          checkpointId={forkTarget.checkpointId}
          parentThreadId={forkTarget.parentThreadId}
          onClose={() => setForkTarget(null)}
        />
      )}
    </>
  );
}

export function TrajectoryTree() {
  const { tree } = useDashboard();
  return (
    <GlassPanel>
      <PanelHeader>
        <PanelTitle icon={<IconTreeStructure size={13} />}>Trajectory</PanelTitle>
        <span className="ml-auto font-mono text-[10px] tabular-nums text-ink-ghost">
          {tree.length} candidates
        </span>
      </PanelHeader>
      <ReactFlowProvider>
        <TrajectoryFlow />
      </ReactFlowProvider>
    </GlassPanel>
  );
}
