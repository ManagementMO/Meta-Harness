import type { RunSummary, TreeNode } from "./types";

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

export async function listRuns(): Promise<RunListItem[]> {
  const res = await fetch(`${BASE_URL}/runs`);
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data) ? data : data.runs ?? [];
}

// ── Run detail ──

export async function fetchRunInfo(runId: string): Promise<unknown> {
  const res = await fetch(`${BASE_URL}/runs/${runId}`);
  if (!res.ok) throw new Error(`run ${runId} not found`);
  return res.json();
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function getRunDetail(runId: string): Promise<any> {
  return fetchRunInfo(runId);
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function toRunInfo(detail: any): RunSummary {
  return {
    runId: detail.run_id ?? detail.runId ?? "",
    threadId: detail.thread_id ?? detail.threadId ?? detail.run_id ?? "",
    branches: detail.branches ?? 0,
    checkpointId: detail.checkpoint_id ?? detail.checkpointId ?? null,
    bestScore: detail.best_score ?? detail.bestScore ?? null,
    status: detail.status ?? "unknown",
    iteration: detail.iteration ?? 0,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function toTreeNodes(rows: any[]): TreeNode[] {
  return rows.map((r) => ({
    candidate: r.candidate ?? r.candidate_name ?? "",
    parent_candidate_name: r.parent_candidate_name ?? null,
    iteration: r.iteration ?? 0,
    status: r.status ?? "seed",
    scores: r.scores ?? { accuracy: 0 },
    hypothesis: r.hypothesis,
    axis: r.axis,
    delta: r.delta ?? null,
    isForkBranch: r.is_fork_branch ?? false,
    threadId: r.thread_id,
  }));
}

// ── Checkpoints ──

export async function fetchCheckpoints(runId: string): Promise<unknown> {
  const res = await fetch(`${BASE_URL}/runs/${runId}/checkpoints`);
  if (!res.ok) throw new Error(`checkpoints for ${runId} not found`);
  return res.json();
}

// ── Forking ──

export async function postFork(
  runId: string,
  body: {
    parent_checkpoint_id: string;
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
    mods?: Record<string, unknown>;
    name?: string;
  },
): Promise<{ branch_id?: string }> {
  const result = await postFork(runId, body);
  return result as { branch_id?: string };
}

// ── Memory ──

export async function fetchMemory(namespace: string, limit = 50): Promise<unknown> {
  const res = await fetch(
    `${BASE_URL}/memory/${encodeURIComponent(namespace)}?limit=${limit}`,
  );
  if (!res.ok) throw new Error(`memory namespace ${namespace} not found`);
  return res.json();
}

import { MOCK_DIFFS } from "./mock/diffs";
import { MOCK_TEST_OUTPUT } from "./mock/test-output";

export function getDiff(candidateName: string): string | null {
  return MOCK_DIFFS[candidateName] ?? null;
}

export function getTestOutput(candidateName: string): string | null {
  return MOCK_TEST_OUTPUT[candidateName] ?? null;
}

export const API_BASE_URL = BASE_URL;
