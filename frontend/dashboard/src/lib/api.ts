import type { CandidateStatus, MemoryEntry, RunSummary, Scores, TreeNode } from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// ── Availability check ──

export async function isBackendAvailable(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/health`, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

// ── Run list (home page) ──

export type RunListItem = {
  run_id: string;
  status: string;
  best_score: number | null;
  iteration: number;
};

export type CreateRunRequest = {
  run_name?: string;
  proposer?: "claude" | "mock";
  mock_bench?: boolean;
  budget?: number;
  fresh?: boolean;
  trials?: number;
  workers?: number;
};

export type CreateRunResponse = {
  run_id: string;
  thread_id: string;
  status: string;
  current_iteration: number;
};

export async function listRuns(): Promise<RunListItem[]> {
  const res = await fetch(`${BASE_URL}/runs`);
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data) ? data : data.runs ?? [];
}

export async function createRun(payload: CreateRunRequest): Promise<CreateRunResponse> {
  const res = await fetch(`${BASE_URL}/runs`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`failed to create run (${res.status})`);
  }
  return (await res.json()) as CreateRunResponse;
}

// ── Run detail ──

export async function fetchRunInfo(runId: string): Promise<unknown> {
  const res = await fetch(`${BASE_URL}/runs/${runId}`);
  if (!res.ok) throw new Error(`run ${runId} not found`);
  return res.json();
}

type RunDetail = {
  run_id?: string;
  runId?: string;
  thread_id?: string;
  threadId?: string;
  branches?: number;
  checkpoint_id?: string | null;
  checkpointId?: string | null;
  best_score?: number | null;
  bestScore?: number | null;
  status?: string;
  current_iteration?: number;
  iteration?: number;
  summary_rows?: EvolutionRow[];
  frontier_val?: FrontierVal | null;
  manifest?: {
    mock_proposer?: boolean;
    mock_bench?: boolean;
  };
};

type EvolutionRow = {
  candidate?: string;
  candidate_name?: string;
  parent_candidate_name?: string | null;
  iteration?: number;
  status?: CandidateStatus;
  scores?: Scores;
  hypothesis?: string;
  axis?: "exploration" | "exploitation";
  delta?: number | null;
  is_fork_branch?: boolean;
  thread_id?: string;
  checkpoint_id?: string;
};

type FrontierVal = {
  _best?: {
    name?: string;
  };
  _pareto_names?: string[];
};

function asRunDetail(value: unknown): RunDetail {
  return value && typeof value === "object" ? (value as RunDetail) : {};
}

export async function getRunDetail(runId: string): Promise<RunDetail> {
  return asRunDetail(await fetchRunInfo(runId));
}

export function toRunInfo(value: RunDetail): RunSummary {
  const detail = asRunDetail(value);
  return {
    runId: detail.run_id ?? detail.runId ?? "",
    threadId: detail.thread_id ?? detail.threadId ?? detail.run_id ?? "",
    branches: detail.branches ?? 0,
    checkpointId: detail.checkpoint_id ?? detail.checkpointId ?? null,
    bestScore: detail.best_score ?? detail.bestScore ?? null,
    status: detail.status ?? "unknown",
    iteration: detail.current_iteration ?? detail.iteration ?? 0,
    isMock: Boolean(detail.manifest?.mock_proposer || detail.manifest?.mock_bench),
  };
}

export function toTreeNodes(rows: EvolutionRow[]): TreeNode[] {
  return rows.map((r) => {
    const candidate = r.candidate ?? r.candidate_name ?? "";
    return {
      candidate,
      parent_candidate_name: r.parent_candidate_name ?? null,
      iteration: r.iteration ?? 0,
      status: r.status ?? "seed",
      scores: r.scores ?? { accuracy: 0 },
      hypothesis: r.hypothesis,
      axis: r.axis,
      delta: r.delta ?? null,
      isForkBranch: r.is_fork_branch ?? false,
      threadId: r.thread_id,
      checkpointId: r.checkpoint_id,
    };
  });
}

export function toTreeNodesFromRunDetail(detail: RunDetail): TreeNode[] {
  const nodes = toTreeNodes(detail.summary_rows ?? []);
  const best = detail.frontier_val?._best?.name;
  const frontier = new Set(detail.frontier_val?._pareto_names ?? []);
  return nodes.map((node) => ({
    ...node,
    status:
      best && node.candidate === best
        ? "best"
        : frontier.has(node.candidate)
          ? "accepted"
          : node.status,
  }));
}

// ── Checkpoints ──

export async function fetchCheckpoints(runId: string): Promise<unknown> {
  const res = await fetch(`${BASE_URL}/runs/${runId}/checkpoints`);
  if (!res.ok) throw new Error(`checkpoints for ${runId} not found`);
  return res.json();
}

type CheckpointRow = {
  checkpoint_id?: string;
  thread_id?: string;
  iteration?: number;
  values_summary?: {
    best_candidate?: string;
    iteration?: number;
  };
};

export async function fetchCheckpointCandidateMap(runId: string): Promise<Map<string, string>> {
  const raw = await fetchCheckpoints(runId);
  const rows = (raw as { checkpoints?: unknown }).checkpoints;
  const map = new Map<string, string>();
  if (!Array.isArray(rows)) return map;
  for (const item of rows.toReversed()) {
    const row = item as CheckpointRow;
    const candidate = row.values_summary?.best_candidate;
    if (row.checkpoint_id && candidate) map.set(candidate, row.checkpoint_id);
  }
  return map;
}

export async function resolveCheckpointForNode(
  runId: string,
  node: { candidate: string; iteration: number; threadId?: string },
): Promise<string | null> {
  const raw = await fetchCheckpoints(runId);
  const rows = (raw as { checkpoints?: unknown }).checkpoints;
  if (!Array.isArray(rows)) return null;

  const typed = rows as CheckpointRow[];

  // Prefer exact LangGraph thread lineage match.
  if (node.threadId) {
    const byThreadAndIter = typed
      .toReversed()
      .find((row) => row.thread_id === node.threadId && row.iteration === node.iteration);
    if (byThreadAndIter?.checkpoint_id) return byThreadAndIter.checkpoint_id;

    const byThread = typed.toReversed().find((row) => row.thread_id === node.threadId);
    if (byThread?.checkpoint_id) return byThread.checkpoint_id;
  }

  // Fallback for older payloads that only expose best candidate summaries.
  const byCandidate = typed.toReversed().find(
    (row) => row.values_summary?.best_candidate === node.candidate,
  );
  if (byCandidate?.checkpoint_id) return byCandidate.checkpoint_id;

  // Final fallback by iteration summary when candidate labels drift.
  const bySummaryIteration = typed
    .toReversed()
    .find((row) => row.values_summary?.iteration === node.iteration);
  if (bySummaryIteration?.checkpoint_id) return bySummaryIteration.checkpoint_id;

  return null;
}

// ── Forking ──

export async function postFork(
  runId: string,
  body: {
    parent_checkpoint_id: string;
    parent_thread_id?: string;
    mods?: Record<string, unknown>;
    name?: string;
  },
): Promise<unknown> {
  const res = await fetch(`${BASE_URL}/runs/${runId}/fork`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`fork failed for run ${runId}`);
  return res.json();
}

export async function forkRun(
  runId: string,
  body: {
    parent_checkpoint_id: string;
    parent_thread_id?: string;
    mods?: Record<string, unknown>;
    name?: string;
  },
): Promise<{ branch_id?: string; thread_id?: string }> {
  const result = await postFork(runId, body);
  return result as { branch_id?: string; thread_id?: string };
}

// ── Memory ──

export async function fetchMemory(namespace: string, limit = 50): Promise<unknown> {
  const res = await fetch(
    `${BASE_URL}/memory/${encodeURIComponent(namespace)}?limit=${limit}`,
  );
  if (!res.ok) throw new Error(`memory namespace ${namespace} not found`);
  return res.json();
}

export async function listMemory(namespace: string, limit = 50): Promise<MemoryEntry[]> {
  const raw = await fetchMemory(namespace, limit);
  if (!raw || typeof raw !== "object") return [];
  const entries = (raw as { entries?: unknown }).entries;
  if (!Array.isArray(entries)) return [];
  return entries.flatMap((entry) => {
    if (!entry || typeof entry !== "object") return [];
    const value = entry as Partial<MemoryEntry>;
    return typeof value.key === "string" && typeof value.pattern === "string"
      ? [value as MemoryEntry]
      : [];
  });
}

export async function getDiff(runId: string, candidate: string): Promise<string | null> {
  const res = await fetch(
    `${BASE_URL}/runs/${encodeURIComponent(runId)}/candidates/${encodeURIComponent(candidate)}/diff`,
  );
  if (!res.ok) return null;
  const data = await res.json();
  return typeof data.diff === "string" && data.diff.length > 0 ? data.diff : null;
}

export async function getTestOutput(runId: string, candidate: string): Promise<string | null> {
  const res = await fetch(
    `${BASE_URL}/runs/${encodeURIComponent(runId)}/candidates/${encodeURIComponent(candidate)}/test-output`,
  );
  if (!res.ok) return null;
  const data = await res.json();
  return typeof data.output === "string" && data.output.length > 0 ? data.output : null;
}

export const API_BASE_URL = BASE_URL;
