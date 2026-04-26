"use client";

import {
  createContext,
  useContext,
  useReducer,
  type Dispatch,
  type ReactNode,
} from "react";
import { createElement } from "react";
import type {
  DashboardAction,
  DashboardState,
  IterationChapter,
  LogEntry,
  TreeNode,
} from "./types";

const initialTree: TreeNode[] = [
  {
    candidate: "baseline",
    parent_candidate_name: null,
    iteration: 0,
    status: "seed",
    scores: { accuracy: 0.62, per_task: {
      "fix-typo": { pass_rate: 0.8, trials: [true, true, true, true, false] },
      "add-function": { pass_rate: 0.6, trials: [true, true, true, false, false] },
      "refactor": { pass_rate: 0.4, trials: [true, true, false, false, false] },
      "handle-error": { pass_rate: 0.6, trials: [true, false, true, true, false] },
      "implement-spec": { pass_rate: 0.6, trials: [true, true, true, false, false] },
    }},
    hypothesis: "starting harness",
    axis: "exploration",
    delta: 0,
  },
  {
    candidate: "retry-on-schema-drift",
    parent_candidate_name: "baseline",
    iteration: 1,
    status: "accepted",
    scores: { accuracy: 0.7, per_task: {
      "fix-typo": { pass_rate: 1.0, trials: [true, true, true, true, true] },
      "add-function": { pass_rate: 0.6, trials: [true, true, true, false, false] },
      "refactor": { pass_rate: 0.4, trials: [true, true, false, false, false] },
      "handle-error": { pass_rate: 0.8, trials: [true, true, true, true, false] },
      "implement-spec": { pass_rate: 0.6, trials: [true, true, true, false, false] },
    }},
    hypothesis: "retry on schema_drift errors",
    axis: "exploitation",
    delta: 0.08,
  },
  {
    candidate: "tighter-tool-hashing",
    parent_candidate_name: "retry-on-schema-drift",
    iteration: 2,
    status: "rejected",
    scores: { accuracy: 0.66, per_task: {
      "fix-typo": { pass_rate: 1.0, trials: [true, true, true, true, true] },
      "add-function": { pass_rate: 0.6, trials: [true, true, true, false, false] },
      "refactor": { pass_rate: 0.2, trials: [true, false, false, false, false] },
      "handle-error": { pass_rate: 0.6, trials: [true, false, true, true, false] },
      "implement-spec": { pass_rate: 0.6, trials: [true, true, true, false, false] },
    }},
    hypothesis: "stricter tool-description hashing",
    axis: "exploration",
    delta: -0.04,
  },
  {
    candidate: "early-exit-on-auth",
    parent_candidate_name: "retry-on-schema-drift",
    iteration: 3,
    status: "accepted",
    scores: { accuracy: 0.74, per_task: {
      "fix-typo": { pass_rate: 1.0, trials: [true, true, true, true, true] },
      "add-function": { pass_rate: 0.6, trials: [true, true, true, false, false] },
      "refactor": { pass_rate: 0.6, trials: [true, true, true, false, false] },
      "handle-error": { pass_rate: 0.8, trials: [true, true, true, true, false] },
      "implement-spec": { pass_rate: 0.6, trials: [true, true, true, false, false] },
    }},
    hypothesis: "early-exit on auth failures",
    axis: "exploitation",
    delta: 0.04,
  },
  {
    candidate: "more-specific-descriptions",
    parent_candidate_name: "early-exit-on-auth",
    iteration: 4,
    status: "best",
    scores: { accuracy: 0.8, per_task: {
      "fix-typo": { pass_rate: 1.0, trials: [true, true, true, true, true] },
      "add-function": { pass_rate: 0.8, trials: [true, true, true, true, false] },
      "refactor": { pass_rate: 0.6, trials: [true, true, true, false, false] },
      "handle-error": { pass_rate: 0.8, trials: [true, true, true, true, false] },
      "implement-spec": { pass_rate: 0.8, trials: [true, true, true, true, false] },
    }},
    hypothesis: "more specific tool descriptions",
    axis: "exploitation",
    delta: 0.06,
  },
  {
    candidate: "rewrite-tool-descriptions-with-examples",
    parent_candidate_name: "retry-on-schema-drift",
    iteration: 2,
    status: "accepted",
    scores: { accuracy: 0.78, per_task: {
      "fix-typo": { pass_rate: 1.0, trials: [true, true, true, true, true] },
      "add-function": { pass_rate: 0.8, trials: [true, true, true, true, false] },
      "refactor": { pass_rate: 0.6, trials: [true, true, true, false, false] },
      "handle-error": { pass_rate: 0.8, trials: [true, true, false, true, true] },
      "implement-spec": { pass_rate: 0.6, trials: [true, true, true, false, false] },
    }},
    hypothesis: "rewrite tool descriptions w/ examples",
    axis: "exploration",
    delta: 0.16,
    isForkBranch: true,
    threadId: "demo.fork.abc12345",
  },
  {
    candidate: "few-shot-demos-on-descriptions",
    parent_candidate_name: "rewrite-tool-descriptions-with-examples",
    iteration: 3,
    status: "best",
    scores: { accuracy: 0.85, per_task: {
      "fix-typo": { pass_rate: 1.0, trials: [true, true, true, true, true] },
      "add-function": { pass_rate: 0.8, trials: [true, true, true, true, false] },
      "refactor": { pass_rate: 0.8, trials: [true, true, true, true, false] },
      "handle-error": { pass_rate: 0.8, trials: [true, true, true, true, false] },
      "implement-spec": { pass_rate: 0.8, trials: [true, true, true, true, false] },
    }},
    hypothesis: "add few-shot demos to descriptions",
    axis: "exploitation",
    delta: 0.07,
    isForkBranch: true,
    threadId: "demo.fork.abc12345",
  },
];

const initialIterations: IterationChapter[] = [
  { iteration: 1, candidateName: "retry-on-schema-drift", status: "accepted", phases: { propose: true, validate: true, benchmark: true, frontier: true }, hypothesis: "retry on schema_drift errors" },
  { iteration: 2, candidateName: "tighter-tool-hashing", status: "rejected", phases: { propose: true, validate: true, benchmark: true, frontier: false }, hypothesis: "stricter tool-description hashing" },
  { iteration: 3, candidateName: "early-exit-on-auth", status: "accepted", phases: { propose: true, validate: true, benchmark: true, frontier: true }, hypothesis: "early-exit on auth failures" },
  { iteration: 4, candidateName: "more-specific-descriptions", status: "best", phases: { propose: true, validate: true, benchmark: true, frontier: true }, hypothesis: "more specific tool descriptions" },
];

const initialLogEntries: LogEntry[] = [
  { id: "log-1", timestamp: "14:32:11", tag: "orient", text: "read 8 files in workspace", candidateName: "more-specific-descriptions" },
  { id: "log-2", timestamp: "14:32:14", tag: "plan", text: "submit_plan: rewrite tool descriptions to be more specific", candidateName: "more-specific-descriptions" },
  { id: "log-3", timestamp: "14:32:18", tag: "tool/read", text: "agents/early-exit-on-auth.py", candidateName: "more-specific-descriptions" },
  { id: "log-4", timestamp: "14:32:24", tag: "tool/patch", text: "applied patch to agents/more-specific-descriptions.py", candidateName: "more-specific-descriptions" },
  { id: "log-5", timestamp: "14:32:42", tag: "verify", text: "5 tests passed in 0.04s", candidateName: "more-specific-descriptions" },
  { id: "log-6", timestamp: "14:32:43", tag: "score", text: "accuracy=0.80 (+0.06) NEW BEST", candidateName: "more-specific-descriptions" },
];

const initialState: DashboardState = {
  mode: "live",
  run: null,
  tree: [],
  iterations: [],
  logEntries: [],
  forkEvents: [],
  filters: { activeFilter: "all", searchQuery: "" },
  contextTab: "chart",
  selectedNode: null,
  selectedLogLine: null,
  sseConnected: false,
  latestCheckpointId: null,
  lastError: null,
};

export const demoFixtureState: Partial<DashboardState> = {
  run: {
    runId: "demo-2026-04-25",
    threadId: "demo-2026-04-25",
    branches: 2,
    checkpointId: "ckpt_4af9e21c",
    bestScore: 0.85,
    status: "running",
    iteration: 4,
  },
  tree: initialTree,
  iterations: initialIterations,
  logEntries: initialLogEntries,
  forkEvents: [
    {
      timestamp: "14:31:08",
      parentCandidate: "retry-on-schema-drift",
      checkpointId: "ckpt_2c81ef03",
      prior: "explore example-driven prompts instead of hash-based dedup",
      branchId: "fork.abc12345",
      rationale:
        "iteration 2's hash-strictness regressed; try the orthogonal direction",
    },
  ],
  selectedNode: "more-specific-descriptions",
};

function reducer(state: DashboardState, action: DashboardAction): DashboardState {
  switch (action.type) {
    case "SET_MODE":
      return { ...state, mode: action.payload };
    case "SET_RUN":
      return { ...state, run: action.payload };
    case "SET_TREE":
      return { ...state, tree: action.payload };
    case "ADD_TREE_NODE": {
      const existing = state.tree.find(n => n.candidate === action.payload.candidate);
      const merged: TreeNode = existing
        ? {
            ...existing,
            ...action.payload,
            parent_candidate_name:
              action.payload.parent_candidate_name ?? existing.parent_candidate_name,
            iteration: action.payload.iteration || existing.iteration,
            hypothesis: action.payload.hypothesis ?? existing.hypothesis,
            axis: action.payload.axis ?? existing.axis,
            delta: action.payload.delta ?? existing.delta,
          }
        : action.payload;
      const without = state.tree.filter(n => n.candidate !== action.payload.candidate);
      return { ...state, tree: [...without, merged] };
    }
    case "SET_CHECKPOINT_ID":
      return {
        ...state,
        tree: state.tree.map(node => (
          node.candidate === action.payload.candidate
            ? { ...node, checkpointId: action.payload.checkpointId }
            : node
        )),
      };
    case "APPLY_FRONTIER_UPDATE":
      return {
        ...state,
        tree: state.tree.map(node => ({
          ...node,
          status:
            action.payload.bestCandidate && node.candidate === action.payload.bestCandidate
              ? "best"
              : action.payload.frontier.includes(node.candidate)
                ? "accepted"
                : node.status === "best"
                  ? "rejected"
                  : node.status,
          delta:
            action.payload.bestCandidate && node.candidate === action.payload.bestCandidate
              ? action.payload.delta
              : node.delta,
        })),
      };
    case "SET_ITERATIONS":
      return { ...state, iterations: action.payload };
    case "ADD_LOG_ENTRY":
      return { ...state, logEntries: [...state.logEntries, action.payload] };
    case "SET_LOG_ENTRIES":
      return { ...state, logEntries: action.payload };
    case "ADD_FORK_EVENT":
      return { ...state, forkEvents: [...state.forkEvents, action.payload] };
    case "SET_FILTER":
      return { ...state, filters: { ...state.filters, ...action.payload } };
    case "SET_CONTEXT_TAB":
      return { ...state, contextTab: action.payload };
    case "SELECT_NODE":
      return { ...state, selectedNode: action.payload };
    case "SELECT_LOG_LINE":
      return { ...state, selectedLogLine: action.payload };
    case "SET_SSE_CONNECTED":
      return { ...state, sseConnected: action.payload };
    case "ADD_ITERATION": {
      const without = state.iterations.filter(
        i => !(i.candidateName === action.payload.candidateName && i.iteration === action.payload.iteration),
      );
      return { ...state, iterations: [...without, action.payload] };
    }
    case "SET_CHECKPOINT":
      return { ...state, latestCheckpointId: action.payload };
    case "SET_ERROR":
      return { ...state, lastError: action.payload };
    case "CANCEL_BRANCH": {
      const threadId = action.payload;
      return {
        ...state,
        tree: state.tree.map(n =>
          n.threadId === threadId ? { ...n, status: "rejected" as const } : n,
        ),
      };
    }
    case "RESET":
      return { ...initialState };
    default:
      return state;
  }
}

const StateContext = createContext<DashboardState | undefined>(undefined);
const DispatchContext = createContext<Dispatch<DashboardAction> | undefined>(undefined);

export function DashboardProvider({
  children,
  initial,
}: {
  children: ReactNode;
  initial?: Partial<DashboardState>;
}) {
  const [state, dispatch] = useReducer(reducer, { ...initialState, ...initial });
  return createElement(
    StateContext.Provider,
    { value: state },
    createElement(DispatchContext.Provider, { value: dispatch }, children),
  );
}

export function useDashboard(): DashboardState {
  const ctx = useContext(StateContext);
  if (!ctx) throw new Error("useDashboard must be used inside <DashboardProvider />");
  return ctx;
}

export function useDashboardDispatch(): Dispatch<DashboardAction> {
  const ctx = useContext(DispatchContext);
  if (!ctx) throw new Error("useDashboardDispatch must be used inside <DashboardProvider />");
  return ctx;
}

export { initialState };
export type { DashboardState, DashboardAction } from "./types";
