// Dashboard type contracts. Mirrors backend INTERFACES.md §1, §6, §7
// shapes; the SSE event types match streaming.REGISTERED_EVENT_TYPES.

export type CandidateStatus = "seed" | "accepted" | "rejected" | "best" | "fork";

export type LogTag =
  | "orient"
  | "plan"
  | "tool/read"
  | "tool/patch"
  | "act"
  | "verify"
  | "score"
  | "fail"
  | "fork"
  | "memory";

export type ContextTab = "chart" | "diff" | "test" | "memory" | "graph";

export type LogFilter = "all" | "tools" | "verify" | "scores" | "forks";

export type Phase = "orient" | "plan" | "act" | "verify" | "submit";

export type OuterPhaseFlags = {
  propose: boolean;
  validate: boolean;
  benchmark: boolean;
  frontier: boolean;
};

export type Scores = {
  accuracy: number;
  per_task?: Record<string, { pass_rate: number; trials: boolean[] }>;
};

export type TreeNode = {
  candidate: string;
  parent_candidate_name: string | null;
  iteration: number;
  checkpointId?: string;
  status: CandidateStatus;
  scores: Scores;
  hypothesis?: string;
  axis?: "exploration" | "exploitation";
  delta: number | null;
  isForkBranch?: boolean;
  threadId?: string;
};

export type LogEntry = {
  id: string;
  timestamp: string;
  tag: LogTag;
  text: string;
  candidateName: string;
  details?: string;
  expandable?: boolean;
  expandedContent?: string;
  threadId?: string;
};

export type ForkEvent = {
  timestamp: string;
  parentCandidate: string;
  checkpointId: string;
  prior: string;
  branchId: string;
  rationale: string;
};

export type IterationChapter = {
  iteration: number;
  candidateName: string;
  status: CandidateStatus | "running";
  phases: OuterPhaseFlags;
  isForkBranch?: boolean;
  hypothesis?: string;
  threadId?: string;
};

export type RunSummary = {
  runId: string;
  threadId: string;
  branches: number;
  checkpointId: string | null;
  bestScore: number | null;
  status: string;
  iteration: number;
  isMock?: boolean;
};

export type MemoryEntry = {
  key: string;
  pattern: string;
  mechanism_axis?: string;
  score_delta?: number;
  evidence_run_ids?: string[];
  created_at?: string;
};

export type DashboardFilters = {
  activeFilter: LogFilter;
  searchQuery: string;
};

export type DashboardState = {
  mode: "live" | "mock";
  run: RunSummary | null;
  tree: TreeNode[];
  iterations: IterationChapter[];
  logEntries: LogEntry[];
  forkEvents: ForkEvent[];
  filters: DashboardFilters;
  contextTab: ContextTab;
  selectedNode: string | null;
  selectedLogLine: string | null;
  sseConnected: boolean;
};

export type RunInfo = RunSummary;

export type EvolutionRow = {
  iteration: number;
  candidate: string;
  parent_candidate_name: string | null;
  scores: Scores;
  delta: number | null;
  outcome: string;
  thread_id?: string;
};

export type DashboardAction =
  | { type: "SET_MODE"; payload: DashboardState["mode"] }
  | { type: "SET_RUN"; payload: RunSummary | null }
  | { type: "SET_TREE"; payload: TreeNode[] }
  | { type: "ADD_TREE_NODE"; payload: TreeNode }
  | { type: "SET_CHECKPOINT_ID"; payload: { candidate: string; checkpointId: string } }
  | {
      type: "APPLY_FRONTIER_UPDATE";
      payload: {
        frontier: string[];
        bestCandidate: string | null;
        delta: number | null;
      };
    }
  | { type: "SET_ITERATIONS"; payload: IterationChapter[] }
  | { type: "ADD_LOG_ENTRY"; payload: LogEntry }
  | { type: "SET_LOG_ENTRIES"; payload: LogEntry[] }
  | { type: "ADD_FORK_EVENT"; payload: ForkEvent }
  | { type: "SET_FILTER"; payload: Partial<DashboardFilters> }
  | { type: "SET_CONTEXT_TAB"; payload: ContextTab }
  | { type: "SELECT_NODE"; payload: string | null }
  | { type: "SELECT_LOG_LINE"; payload: string | null }
  | { type: "SET_SSE_CONNECTED"; payload: boolean };
