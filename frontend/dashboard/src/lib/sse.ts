// EventSource wrapper for the multiplexed SSE channel that the backend
// exposes at GET /runs/{run_id}/stream. The 11 event types are the
// closed allowlist from streaming.py; backend rejects unknowns with a
// 500 so dashboard typings can stay tight.

import { API_BASE_URL } from "./api";

export type StreamingEventType =
  | "state-update"
  | "checkpoint-written"
  | "candidate-created"
  | "validate-result"
  | "eval-result"
  | "frontier-updated"
  | "iteration-complete"
  | "fork-created"
  | "branch-cancelled"
  | "memory-pattern-stored"
  | "error";

export type StreamingEvent<T = Record<string, unknown>> = {
  type: StreamingEventType;
  id: string;
  data: T;
};

export type StreamHandle = {
  close: () => void;
};

export function subscribeToRun(
  runId: string,
  handlers: Partial<Record<StreamingEventType, (e: StreamingEvent) => void>> &
  { onOpen?: () => void; onError?: (e: Event) => void },
): StreamHandle {
  const url = `${API_BASE_URL}/runs/${encodeURIComponent(runId)}/stream`;
  const source = new EventSource(url);
  if (handlers.onOpen) source.addEventListener("open", handlers.onOpen);
  if (handlers.onError) source.addEventListener("error", handlers.onError);

  for (const [type, handler] of Object.entries(handlers) as [
    string,
    (e: StreamingEvent) => void,
  ][]) {
    if (type === "onOpen" || type === "onError") continue;
    source.addEventListener(type, (raw) => {
      const evt = raw as MessageEvent<string>;
      try {
        handler({
          type: type as StreamingEventType,
          id: evt.lastEventId,
          data: JSON.parse(evt.data),
        });
      } catch {
        /* malformed payload — drop */
      }
    });
  }
  return { close: () => source.close() };
}

// ── Convenience wrappers used by the dashboard page ──

import type { Dispatch } from "react";
import { demoFixtureState } from "./state";
import type { DashboardAction } from "./types";
import type { TreeNode, LogEntry, ForkEvent, RunSummary } from "./types";

type RunEventData = {
  candidate?: string;
  checkpoint_id?: string | number;
  node?: string | number;
  valid?: boolean;
  iteration?: string | number;
  status?: string | number;
  thread_id?: string | number;
  key?: string | number;
  message?: string | number;
  run?: RunSummary;
  tree?: TreeNode[];
  log?: LogEntry;
  import_path?: string;
  parent?: string | null;
  accuracy?: number;
  per_task?: TreeNode["scores"]["per_task"];
  frontier?: string[];
  best_candidate?: string | null;
  delta?: number | null;
  parent_thread_id?: string;
  parent_checkpoint_id?: string;
};

function eventLogEntry(e: StreamingEvent, text: string, tag: LogEntry["tag"]): LogEntry {
  const data = e.data as RunEventData;
  return {
    id: e.id || `${e.type}-${Date.now()}`,
    timestamp: new Date().toISOString(),
    tag,
    text,
    candidateName: typeof data.candidate === "string" ? data.candidate : "outer-loop",
    details: JSON.stringify(e.data, null, 2),
    expandable: true,
  };
}

function valueLabel(value: unknown): string | null {
  return typeof value === "string" || typeof value === "number" ? String(value) : null;
}

function candidateNodeFromEvent(data: RunEventData): TreeNode | null {
  if (typeof data.candidate !== "string") return null;
  const iterationValue = typeof data.iteration === "number" ? data.iteration : 0;
  return {
    candidate: data.candidate,
    parent_candidate_name: data.parent ?? null,
    iteration: iterationValue,
    checkpointId: valueLabel(data.checkpoint_id) ?? undefined,
    status: "seed",
    scores: { accuracy: 0 },
    delta: null,
  };
}

function evalNodeFromEvent(data: RunEventData): TreeNode | null {
  if (typeof data.candidate !== "string") return null;
  const accuracy = typeof data.accuracy === "number" ? data.accuracy : 0;
  return {
    candidate: data.candidate,
    parent_candidate_name: data.parent ?? null,
    iteration: typeof data.iteration === "number" ? data.iteration : 0,
    checkpointId: valueLabel(data.checkpoint_id) ?? undefined,
    status: "accepted",
    scores: { accuracy, per_task: data.per_task },
    delta: null,
  };
}

function forkEventFromEvent(data: RunEventData): ForkEvent {
  const threadId = valueLabel(data.thread_id) ?? "branch";
  return {
    timestamp: new Date().toISOString(),
    parentCandidate: valueLabel(data.parent_thread_id) ?? "run",
    checkpointId: valueLabel(data.parent_checkpoint_id) ?? "checkpoint",
    prior: "backend fork",
    branchId: threadId,
    rationale: "Fork created from checkpoint",
  };
}

export function startSSE(
  runId: string,
  dispatch: Dispatch<DashboardAction>,
): () => void {
  const handle = subscribeToRun(runId, {
    onOpen: () => dispatch({ type: "SET_SSE_CONNECTED", payload: true }),
    onError: () => dispatch({ type: "SET_SSE_CONNECTED", payload: false }),
    "state-update": (e) => {
      const data = e.data as RunEventData;
      if (data.run) dispatch({ type: "SET_RUN", payload: data.run });
    },
    "checkpoint-written": (e) => {
      const data = e.data as RunEventData;
      const checkpoint = valueLabel(data.checkpoint_id) ?? "unknown";
      const node = valueLabel(data.node) ?? "graph";
      dispatch({
        type: "ADD_LOG_ENTRY",
        payload: eventLogEntry(e, `checkpoint ${checkpoint} written at ${node}`, "memory"),
      });
    },
    "candidate-created": (e) => {
      const node = candidateNodeFromEvent(e.data as RunEventData);
      if (node) dispatch({ type: "ADD_TREE_NODE", payload: node });
    },
    "validate-result": (e) => {
      const data = e.data as RunEventData;
      const candidate = valueLabel(data.candidate) ?? "candidate";
      const valid = Boolean(data.valid);
      dispatch({
        type: "ADD_LOG_ENTRY",
        payload: eventLogEntry(
          e,
          `${candidate} ${valid ? "validated" : "failed validation"}`,
          valid ? "verify" : "fail",
        ),
      });
    },
    "eval-result": (e) => {
      const node = evalNodeFromEvent(e.data as RunEventData);
      if (node) dispatch({ type: "ADD_TREE_NODE", payload: node });
    },
    "iteration-complete": (e) => {
      const data = e.data as RunEventData;
      if (data.log) {
        dispatch({ type: "ADD_LOG_ENTRY", payload: data.log });
        return;
      }
      const iteration = valueLabel(data.iteration) ?? "?";
      const status = valueLabel(data.status) ?? "complete";
      dispatch({
        type: "ADD_LOG_ENTRY",
        payload: eventLogEntry(e, `iteration ${iteration} ${status}`, "score"),
      });
    },
    "fork-created": (e) => {
      dispatch({ type: "ADD_FORK_EVENT", payload: forkEventFromEvent(e.data as RunEventData) });
    },
    "branch-cancelled": (e) => {
      const data = e.data as RunEventData;
      const thread = valueLabel(data.thread_id) ?? "branch";
      dispatch({
        type: "ADD_LOG_ENTRY",
        payload: eventLogEntry(e, `${thread} cancelled`, "fork"),
      });
    },
    "memory-pattern-stored": (e) => {
      const data = e.data as RunEventData;
      const key = valueLabel(data.key) ?? "pattern";
      dispatch({
        type: "ADD_LOG_ENTRY",
        payload: eventLogEntry(e, `stored memory pattern for ${key}`, "memory"),
      });
    },
    "frontier-updated": (e) => {
      const data = e.data as RunEventData;
      if (data.tree) dispatch({ type: "SET_TREE", payload: data.tree });
      if (data.frontier || data.best_candidate) {
        dispatch({
          type: "APPLY_FRONTIER_UPDATE",
          payload: {
            frontier: data.frontier ?? [],
            bestCandidate: data.best_candidate ?? null,
            delta: data.delta ?? null,
          },
        });
      }
    },
    "error": (e) => {
      const data = e.data as RunEventData;
      const message = valueLabel(data.message) ?? "stream error";
      dispatch({
        type: "ADD_LOG_ENTRY",
        payload: eventLogEntry(e, message, "fail"),
      });
    },
  });
  return handle.close;
}

import { MOCK_EVENTS, type MockSSEEvent } from "./mock/events";

export function startMockSSE(
  dispatch: Dispatch<DashboardAction>,
  seconds: number,
): () => void {
  void seconds;
  dispatch({ type: "SET_MODE", payload: "mock" });
  if (demoFixtureState.run) {
    dispatch({ type: "SET_RUN", payload: demoFixtureState.run });
  }
  if (demoFixtureState.tree) {
    dispatch({ type: "SET_TREE", payload: demoFixtureState.tree });
  }
  if (demoFixtureState.iterations) {
    dispatch({ type: "SET_ITERATIONS", payload: demoFixtureState.iterations });
  }
  if (demoFixtureState.logEntries) {
    dispatch({ type: "SET_LOG_ENTRIES", payload: demoFixtureState.logEntries });
  }
  for (const fork of demoFixtureState.forkEvents ?? []) {
    dispatch({ type: "ADD_FORK_EVENT", payload: fork });
  }
  if (demoFixtureState.selectedNode) {
    dispatch({ type: "SELECT_NODE", payload: demoFixtureState.selectedNode });
  }
  dispatch({ type: "SET_SSE_CONNECTED", payload: true });

  const timers: ReturnType<typeof setTimeout>[] = [];
  const speed = 1 / speedMultiplier;
  const treeState = new Map<string, TreeNode>();

  const PARENT_MAP: Record<string, string> = {
    "retry-on-schema-drift": "baseline",
    "stricter-tool-hashing": "retry-on-schema-drift",
    "early-exit-on-auth": "retry-on-schema-drift",
    "more-specific-descriptions": "early-exit-on-auth",
    "rewrite-tool-descriptions": "retry-on-schema-drift",
    "few-shot-demos": "rewrite-tool-descriptions",
  };

  const ITERATION_MAP: Record<string, number> = {
    "retry-on-schema-drift": 1,
    "stricter-tool-hashing": 2,
    "early-exit-on-auth": 3,
    "more-specific-descriptions": 4,
    "rewrite-tool-descriptions": 2,
    "few-shot-demos": 3,
  };

  const FORK_CANDIDATES = new Set(["rewrite-tool-descriptions", "few-shot-demos"]);

  const handleEvent = (evt: MockSSEEvent) => {
    switch (evt.type) {
      case "init": {
        const seed: TreeNode = {
          candidate: "baseline",
          parent_candidate_name: null,
          iteration: 0,
          status: "seed",
          scores: { accuracy: 0.62 },
          hypothesis: "starting harness",
          axis: "exploration",
          delta: 0,
        };
        treeState.set(seed.candidate, seed);
        dispatch({ type: "ADD_TREE_NODE", payload: seed });
        dispatch({ type: "SET_RUN", payload: evt.run });
        break;
      }

      case "chapter":
        dispatch({ type: "ADD_ITERATION", payload: evt.chapter });
        break;

      case "log":
        dispatch({ type: "ADD_LOG_ENTRY", payload: evt.entry });
        dispatch({ type: "SELECT_NODE", payload: evt.entry.candidateName });
        break;

      case "fork":
        dispatch({ type: "ADD_FORK_EVENT", payload: evt.fork });
        break;

      case "score-update": {
        const isFork = FORK_CANDIDATES.has(evt.candidate);
        const node: TreeNode = {
          candidate: evt.candidate,
          parent_candidate_name: PARENT_MAP[evt.candidate] ?? null,
          iteration: ITERATION_MAP[evt.candidate] ?? 0,
          status: evt.accepted ? "accepted" : "rejected",
          scores: { accuracy: evt.score },
          delta: evt.delta,
          isForkBranch: isFork,
          threadId: isFork ? "demo.fork.c7a1e3f0" : undefined,
        };
        treeState.set(node.candidate, node);
        dispatch({ type: "ADD_TREE_NODE", payload: node });
        dispatch({
          type: "SET_RUN",
          payload: {
            runId: "demo-2026-04-25",
            threadId: "demo-2026-04-25",
            branches: treeState.size > 4 ? 2 : 1,
            checkpointId: `ckpt_${evt.candidate.slice(0, 8)}`,
            bestScore: Math.max(...Array.from(treeState.values()).map(n => n.scores.accuracy)),
            status: "running",
            iteration: ITERATION_MAP[evt.candidate] ?? 0,
          },
        });
        break;
      }

      case "best-update": {
        const existing = treeState.get(evt.candidate);
        if (existing) {
          const updated = { ...existing, status: "best" as const };
          treeState.set(evt.candidate, updated);
          dispatch({ type: "ADD_TREE_NODE", payload: updated });
        }
        dispatch({
          type: "SET_RUN",
          payload: {
            runId: "demo-2026-04-25",
            threadId: "demo-2026-04-25",
            branches: 2,
            checkpointId: "ckpt_best",
            bestScore: evt.score,
            status: "running",
            iteration: treeState.size - 1,
          },
        });
        break;
      }
    }
  };

  for (const evt of MOCK_EVENTS) {
    timers.push(setTimeout(() => handleEvent(evt), evt.delay * speed));
  }

  return () => {
    for (const t of timers) clearTimeout(t);
    dispatch({ type: "SET_SSE_CONNECTED", payload: false });
  };
}
