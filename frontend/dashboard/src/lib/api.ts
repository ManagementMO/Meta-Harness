import type { CandidateStatus, MemoryEntry, RunSummary, Scores, TreeNode } from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";

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
  iteration?: number;
  current_iteration?: number;
  mode?: "research" | "autonomous";
  synthetic?: boolean;
};

export type CreateRunRequest = {
  run_name?: string;
  proposer?: "claude" | "mock";
  mock_bench?: boolean;
  budget?: number;
  fresh?: boolean;
  trials?: number;
  workers?: number;
  mode?: "research" | "autonomous";
  parent_policy?: "best_accuracy" | "pareto_sample";
  inner_model?: string;
  proposer_model?: string;
  global_memory?: boolean;
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
  mode?: "research" | "autonomous";
  synthetic?: boolean;
  manifest?: {
    mock_proposer?: boolean;
    mock_bench?: boolean;
    synthetic?: boolean;
    mode?: "research" | "autonomous";
    persistence_backend?: "postgres" | "memory";
    security_profile?: string;
  };
};

type EvolutionRow = {
  candidate?: string;
  candidate_name?: string;
  candidate_id?: string;
  parent_candidate_name?: string | null;
  parent_ids?: string[];
  iteration?: number;
  status?: string;
  scores?: unknown;
  synthetic?: boolean;
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
    candidate_id?: string;
  };
  _pareto_names?: string[];
  _pareto_ids?: string[];
};

function asRunDetail(value: unknown): RunDetail {
  return value && typeof value === "object" ? (value as RunDetail) : {};
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function metricNumber(value: unknown): number {
  if (typeof value === "number") return value;
  const metric = asRecord(value);
  return typeof metric.value === "number" ? metric.value : 0;
}

function normalizeCandidateStatus(value: unknown): CandidateStatus {
  if (value === "best" || value === "rejected" || value === "fork") return value;
  if (value === "accepted" || value === "frontier") return "accepted";
  return "seed";
}

function normalizeScores(value: unknown, synthetic = false): Scores {
  const scores = asRecord(value);
  const tokens = asRecord(scores.tokens);
  const perTask = scores.per_task;
  return {
    accuracy: metricNumber(scores.accuracy_value ?? scores.accuracy),
    per_task: perTask && typeof perTask === "object" ? (perTask as Scores["per_task"]) : undefined,
    synthetic: Boolean(scores.synthetic ?? synthetic),
    tokenMeasurementStatus:
      typeof tokens.measurement_status === "string"
        ? (tokens.measurement_status as Scores["tokenMeasurementStatus"])
        : undefined,
  };
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
    isSynthetic: Boolean(detail.synthetic ?? detail.manifest?.synthetic ?? detail.manifest?.mock_bench),
    mode: detail.mode ?? detail.manifest?.mode ?? "research",
    persistence: detail.manifest?.persistence_backend,
    securityProfile: detail.manifest?.security_profile ?? "trusted-local-process-isolation",
  };
}

export function toTreeNodes(rows: EvolutionRow[]): TreeNode[] {
  return rows.map((r) => {
    const candidate = r.candidate ?? r.candidate_name ?? "";
    return {
      candidate,
      candidateId: r.candidate_id,
      parent_candidate_name: r.parent_candidate_name ?? null,
      parentIds: r.parent_ids,
      iteration: r.iteration ?? 0,
      status: normalizeCandidateStatus(r.status),
      scores: normalizeScores(r.scores, r.synthetic),
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
  const best = detail.frontier_val?._best?.candidate_id ?? detail.frontier_val?._best?.name;
  const frontier = new Set(
    detail.frontier_val?._pareto_ids?.length
      ? detail.frontier_val._pareto_ids
      : detail.frontier_val?._pareto_names ?? [],
  );
  return nodes.map((node) => {
    const key = node.candidateId ?? node.candidate;
    return {
      ...node,
      status:
        best && key === best
          ? "best"
          : frontier.has(key)
            ? "accepted"
            : node.status,
    };
  });
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
    best_candidate_id?: string;
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
    const candidate = row.values_summary?.best_candidate_id ?? row.values_summary?.best_candidate;
    if (row.checkpoint_id && candidate) map.set(candidate, row.checkpoint_id);
  }
  return map;
}

export async function resolveCheckpointForNode(
  runId: string,
  node: { candidate: string; candidateId?: string; iteration: number; threadId?: string },
): Promise<string | null> {
  let raw: unknown;
  try {
    raw = await fetchCheckpoints(runId);
  } catch {
    // Some runs (especially dry-runs) may not expose checkpoint history yet.
    // Returning null lets callers surface a graceful "no checkpoint" message
    // instead of throwing an unhandled rejection from click handlers.
    return null;
  }
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
    (row) =>
      (node.candidateId && row.values_summary?.best_candidate_id === node.candidateId) ||
      row.values_summary?.best_candidate === node.candidate,
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

export async function getCandidateManifest(
  runId: string,
  candidate: string,
): Promise<Record<string, unknown> | null> {
  const res = await fetch(
    `${BASE_URL}/runs/${encodeURIComponent(runId)}/candidates/${encodeURIComponent(candidate)}/manifest`,
  );
  return res.ok ? ((await res.json()) as Record<string, unknown>) : null;
}

export async function getRunReport(runId: string): Promise<Record<string, unknown> | null> {
  const res = await fetch(`${BASE_URL}/runs/${encodeURIComponent(runId)}/report`);
  return res.ok ? ((await res.json()) as Record<string, unknown>) : null;
}

export async function getEvidenceEvents(
  runId: string,
  candidateId?: string,
): Promise<unknown[]> {
  const params = new URLSearchParams();
  if (candidateId) params.set('candidate_id', candidateId);
  const query = params.size > 0 ? `?${params.toString()}` : '';
  const res = await fetch(`${BASE_URL}/runs/${encodeURIComponent(runId)}/events${query}`);
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data.events) ? data.events : [];
}

export function artifactUrl(runId: string, digest: string): string {
  return `${BASE_URL}/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(digest)}`;
}

export async function finalizeRun(
  runId: string,
  candidateIds?: string[],
): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE_URL}/runs/${encodeURIComponent(runId)}/finalize`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ candidate_ids: candidateIds }),
  });
  if (!res.ok) throw new Error(`finalization failed (${res.status})`);
  return (await res.json()) as Record<string, unknown>;
}

export const API_BASE_URL = BASE_URL;
