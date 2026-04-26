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
import type { DashboardAction } from "./types";
import type { TreeNode, LogEntry, ForkEvent, RunSummary } from "./types";

export function startSSE(
  runId: string,
  dispatch: Dispatch<DashboardAction>,
): () => void {
  const handle = subscribeToRun(runId, {
    onOpen: () => dispatch({ type: "SET_SSE_CONNECTED", payload: true }),
    onError: () => dispatch({ type: "SET_SSE_CONNECTED", payload: false }),
    "state-update": (e) => {
      if (e.data.run) dispatch({ type: "SET_RUN", payload: e.data.run as RunSummary });
    },
    "candidate-created": (e) => {
      dispatch({ type: "ADD_TREE_NODE", payload: e.data as unknown as TreeNode });
    },
    "eval-result": (e) => {
      dispatch({ type: "ADD_TREE_NODE", payload: e.data as unknown as TreeNode });
    },
    "iteration-complete": (e) => {
      if (e.data.log) dispatch({ type: "ADD_LOG_ENTRY", payload: e.data.log as LogEntry });
    },
    "fork-created": (e) => {
      dispatch({ type: "ADD_FORK_EVENT", payload: e.data as unknown as ForkEvent });
    },
    "frontier-updated": (e) => {
      if (e.data.tree) dispatch({ type: "SET_TREE", payload: e.data.tree as TreeNode[] });
    },
    "checkpoint-written": (e) => {
      if (e.data.checkpoint_id) dispatch({ type: "SET_CHECKPOINT", payload: e.data.checkpoint_id as string });
    },
    "validate-result": (e) => {
      if (e.data.log) dispatch({ type: "ADD_LOG_ENTRY", payload: e.data.log as LogEntry });
    },
    "branch-cancelled": (e) => {
      if (e.data.thread_id) dispatch({ type: "CANCEL_BRANCH", payload: e.data.thread_id as string });
    },
    "memory-pattern-stored": (e) => {
      const entry: LogEntry = {
        id: `mem-${Date.now()}`,
        timestamp: new Date().toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        tag: "memory",
        text: (e.data.pattern as string) ?? "pattern stored",
        candidateName: (e.data.candidate as string) ?? "",
      };
      dispatch({ type: "ADD_LOG_ENTRY", payload: entry });
    },
    "error": (e) => {
      dispatch({ type: "SET_ERROR", payload: (e.data.message as string) ?? "Unknown error" });
    },
  });
  return handle.close;
}

import { MOCK_EVENTS, type MockSSEEvent } from "./mock/events";

export function startMockSSE(
  dispatch: Dispatch<DashboardAction>,
  speedMultiplier = 1,
): () => void {
  dispatch({ type: "RESET" });
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
