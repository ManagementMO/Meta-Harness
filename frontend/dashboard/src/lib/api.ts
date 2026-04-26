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

// ── Mock fixtures used by ContextPanel during the build/dry-run.

const SAMPLE_DIFF = `--- a/agents/baseline.py
+++ b/agents/more-specific-descriptions.py
@@ -3,7 +3,7 @@
 from app.meta_harness.harness import CodingAgentHarness


-class BaselineHarness(CodingAgentHarness):
+class MoreSpecificDescriptionsHarness(CodingAgentHarness):
     SYSTEM_PROMPT = """\
 You are a careful coding assistant. You have access to tools to read,
 edit, and execute code in a sandboxed workspace. Solve the user's task
@@ -12,3 +12,9 @@ by:
 1. Reading relevant files first — especially tests, when present.
 2. Following the plan you were given.
 3. Making targeted edits with apply_patch (preferred) or write_file.
+
+    def _format_tool_result(self, name, result):
+        # Specifically describe each tool's output structure so the model
+        # spends fewer turns parsing the JSON shape.
+        return super()._format_tool_result(name, result)
+
`;

const SAMPLE_TEST_OUTPUT = `============================= test session starts ==============================
collected 5 items

tests/test_calculator.py::test_add_basic PASSED                          [ 20%]
tests/test_calculator.py::test_add_zero PASSED                           [ 40%]
tests/test_calculator.py::test_add_negative PASSED                       [ 60%]
tests/test_calculator.py::test_sub_basic PASSED                          [ 80%]
tests/test_calculator.py::test_sub_self PASSED                           [100%]

============================== 5 passed in 0.04s ===============================
`;

export function getDiff(_candidateName: string): string | null {
  return SAMPLE_DIFF;
}

export function getTestOutput(_candidateName: string): string | null {
  return SAMPLE_TEST_OUTPUT;
}

export const API_BASE_URL = BASE_URL;
