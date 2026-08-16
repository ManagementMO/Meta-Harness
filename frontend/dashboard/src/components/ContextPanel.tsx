"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { motion } from "framer-motion";
import { useDashboard, useDashboardDispatch } from "@/lib/state";
import { ScoreChart } from "./ScoreChart";
import { DiffViewer } from "./DiffViewer";
import { TestOutput } from "./TestOutput";
import { EvidencePanel } from "./EvidencePanel";
import { MemoryPanel } from "./MemoryPanel";
import { GlassPanel } from "./ui/GlassPanel";
import { getDiff, getTestOutput } from "@/lib/api";
import { cn } from "@/lib/cn";

const TABS = ["chart", "diff", "test", "evidence", "memory"] as const;

export function ContextPanel() {
  const params = useParams<{ run_id: string }>();
  const { contextTab, selectedNode, tree, mode } = useDashboard();
  const dispatch = useDashboardDispatch();
  const [diffResult, setDiffResult] = useState<{ candidate: string; value: string | null } | null>(null);
  const [testResult, setTestResult] = useState<{ candidate: string; value: string | null } | null>(null);

  const bestNode = tree.find((node) => node.status === "best");
  const selected =
    selectedNode ?? bestNode?.candidateId ?? bestNode?.candidate ?? tree[0]?.candidateId ?? tree[0]?.candidate ?? null;
  const selectedTreeNode =
    tree.find((node) => (node.candidateId ?? node.candidate) === selected || node.candidate === selected) ?? null;
  const selectedLabel = selectedTreeNode?.candidate ?? selected;
  const diff = diffResult?.candidate === selected ? diffResult.value : null;
  const testOut = testResult?.candidate === selected ? testResult.value : null;
  const perTask = Object.entries(selectedTreeNode?.scores.per_task ?? {});
  const hasMockTaskData = mode === "mock" && perTask.length > 0;

  useEffect(() => {
    let cancelled = false;
    if (!selected || mode !== "live") return;
    getDiff(params.run_id, selected)
      .then((value) => {
        if (!cancelled) setDiffResult({ candidate: selected, value });
      })
      .catch(() => {
        if (!cancelled) setDiffResult({ candidate: selected, value: null });
      });
    getTestOutput(params.run_id, selected)
      .then((value) => {
        if (!cancelled) setTestResult({ candidate: selected, value });
      })
      .catch(() => {
        if (!cancelled) setTestResult({ candidate: selected, value: null });
      });
    return () => {
      cancelled = true;
    };
  }, [mode, params.run_id, selected]);

  const mockDiffPreview = hasMockTaskData
    ? perTask
        .slice(0, 4)
        .map(([taskName, stats]) => {
          const passPct = Math.round(stats.pass_rate * 100);
          return `@@ task:${taskName}
-${taskName}: unstable retries (${passPct - 10}% pass)
+${taskName}: stricter guard + typed fallback (${passPct}% pass)`;
        })
        .join("\n\n")
    : null;

  const mockTestOutput = hasMockTaskData
    ? [
        `mock suite for ${selectedLabel ?? "candidate"}`,
        ...perTask.map(([taskName, stats]) => {
          const passCount = stats.trials.filter(Boolean).length;
          const total = stats.trials.length;
          const status = passCount === total ? "PASS" : passCount === 0 ? "FAIL" : "FLAKY";
          return `${status}  ${taskName}  (${passCount}/${total}, ${Math.round(stats.pass_rate * 100)}%)`;
        }),
        "",
        `summary: ${perTask.reduce((acc, [, stats]) => acc + stats.trials.filter(Boolean).length, 0)}/${perTask.reduce((acc, [, stats]) => acc + stats.trials.length, 0)} checks passed`,
      ].join("\n")
    : null;

  const activeDiff = diff ?? null;
  const diffAdded = activeDiff ? activeDiff.split("\n").filter((l) => l.startsWith("+") && !l.startsWith("+++")).length : 0;
  const diffRemoved = activeDiff ? activeDiff.split("\n").filter((l) => l.startsWith("-") && !l.startsWith("---")).length : 0;

  return (
    <GlassPanel>
      <div role="group" aria-label="Context views" className="panel-sheen flex items-center gap-1 h-10 px-2 border-b border-white/6 shrink-0">
        {TABS.map((tab) => {
          const active = contextTab === tab;
          return (
            <button
              key={tab}
              aria-pressed={active}
              onClick={() => dispatch({ type: "SET_CONTEXT_TAB", payload: tab })}
              className={cn(
                "relative h-full px-2.5 font-mono text-[10px] uppercase tracking-[0.1em] cursor-pointer",
                "transition-colors duration-150 ease-[var(--ease-glass)]",
                active ? "text-frost-bright" : "text-ink-low hover:text-ink-mid",
              )}
            >
              {tab}
              {active && (
                <motion.span
                  layoutId="context-tab-indicator"
                  className="absolute left-1.5 right-1.5 -bottom-px h-px bg-frost shadow-[0_0_8px_rgba(255,255,255,0.4)]"
                  transition={{ type: "spring", stiffness: 500, damping: 40 }}
                />
              )}
            </button>
          );
        })}
      </div>

      <motion.div
        key={contextTab}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.15, ease: "easeOut" }}
        className="flex-1 flex flex-col overflow-y-auto px-4 py-4 min-h-0"
      >
        {contextTab === "chart" && <div className="flex-1 min-h-0"><ScoreChart /></div>}

        {contextTab === "diff" && diff && (
          <div>
            <div className="flex items-center gap-2 mb-3 min-w-0">
              <span className="font-mono text-[11px] text-ink truncate">{selectedLabel ?? "candidate"}</span>
              <span className="text-label uppercase text-ink-ghost shrink-0">immutable source</span>
              <span className="ml-auto font-mono text-[11px] tabular-nums shrink-0">
                <span className="text-moss">+{diffAdded}</span>{" "}
                <span className="text-ember">-{diffRemoved}</span>
              </span>
            </div>
            <DiffViewer diff={diff} />
          </div>
        )}
        {contextTab === "diff" && !diff && mockDiffPreview && (
          <div className="space-y-2">
            <div className="text-label uppercase text-sand">Mock task patch preview</div>
            <pre className="well rounded-[var(--radius-card)] p-3 font-mono text-[11.5px] leading-[1.7] text-ink-mid whitespace-pre-wrap">
              {mockDiffPreview.split("\n").map((line, i) => (
                <div
                  key={i}
                  className={line.startsWith("+") ? "text-moss" : line.startsWith("-") ? "text-ember" : line.startsWith("@@") ? "text-ink-ghost" : undefined}
                >
                  {line || " "}
                </div>
              ))}
            </pre>
          </div>
        )}
        {contextTab === "diff" && !diff && !mockDiffPreview && (
          <p className="font-mono text-[11px] text-ink-low">
            {selectedLabel ? `No diff available for ${selectedLabel}` : "No candidate selected yet."}
          </p>
        )}

        {contextTab === "test" && testOut && <TestOutput output={testOut} />}
        {contextTab === "test" && !testOut && mockTestOutput && <TestOutput output={mockTestOutput} />}
        {contextTab === "test" && !testOut && !mockTestOutput && (
          <p className="font-mono text-[11px] text-ink-low">
            {selectedLabel ? `No test output available for ${selectedLabel}` : "No candidate selected yet."}
          </p>
        )}

        {contextTab === "evidence" && <EvidencePanel />}
        {contextTab === "memory" && <MemoryPanel />}
      </motion.div>
    </GlassPanel>
  );
}
