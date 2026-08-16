"use client";

import { useEffect, useState } from "react";
import { listMemory } from "@/lib/api";
import { useDashboard } from "@/lib/state";
import { EmptyState } from "./ui/EmptyState";
import { IconBrain } from "./ui/icons";
import type { MemoryEntry } from "@/lib/types";

export function MemoryPanel() {
  const { logEntries, mode, run } = useDashboard();
  const [storedPatterns, setStoredPatterns] = useState<MemoryEntry[]>([]);

  const memoryEntries = logEntries.filter((e) => e.tag === "memory");
  const totalPatterns = storedPatterns.length + memoryEntries.length;

  useEffect(() => {
    if (mode !== "live" || run?.mode === "research") return;
    let cancelled = false;
    listMemory("coding-agent", 20)
      .then((entries) => {
        if (!cancelled) setStoredPatterns(entries);
      })
      .catch(() => {
        if (!cancelled) setStoredPatterns([]);
      });
    return () => {
      cancelled = true;
    };
  }, [mode, run?.mode]);

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-baseline gap-2 pb-3 border-b border-white/5">
        <span className="text-label uppercase text-ink-mid">Cross-run memory</span>
        <span className="font-mono text-[10px] tabular-nums text-ink-ghost">{totalPatterns} patterns</span>
      </div>

      <div className="flex-1 overflow-y-auto pt-3">
        {storedPatterns.length > 0 && (
          <section className="mb-4">
            <h3 className="text-label uppercase text-ink-low mb-2">From previous runs</h3>
            <div className="flex flex-col gap-2">
              {storedPatterns.map((p) => (
                <div key={p.key} className="relative glass-inset rounded-[var(--radius-card)] p-3 overflow-hidden">
                  <span aria-hidden="true" className="absolute left-0 top-0 bottom-0 w-0.5 bg-sand/50" />
                  <p className="text-[12px] leading-[1.6] text-ink">{p.pattern}</p>
                  <p className="mt-1.5 font-mono text-[10px] text-ink-ghost truncate">
                    {p.evidence_run_ids?.join(", ") ?? p.mechanism_axis ?? "memory"}
                    {p.created_at ? ` · ${new Date(p.created_at).toLocaleString()}` : ""}
                  </p>
                </div>
              ))}
            </div>
          </section>
        )}

        {memoryEntries.length > 0 && (
          <section>
            <h3 className={`text-label uppercase mb-2 ${mode === "mock" ? "text-sand" : "text-ink-low"}`}>
              {mode === "mock" ? "Mock run fixture" : "This run"}
            </h3>
            <div className="flex flex-col gap-2">
              {memoryEntries.map((e) => (
                <div key={e.id} className="relative glass-inset rounded-[var(--radius-card)] p-3 overflow-hidden">
                  <span aria-hidden="true" className="absolute left-0 top-0 bottom-0 w-0.5 bg-iris/50" />
                  <p className="text-[12px] leading-[1.6] text-ink">{e.text}</p>
                  <p className="mt-1.5 font-mono text-[10px] text-ink-ghost">
                    {e.timestamp.includes("T") ? e.timestamp.slice(11, 19) : e.timestamp} · {e.candidateName}
                  </p>
                </div>
              ))}
            </div>
          </section>
        )}

        {totalPatterns === 0 && (
          <EmptyState icon={<IconBrain size={20} />} title="No stored patterns" className="mt-6">
            {run?.mode === "research"
              ? "Global memory is disabled in research mode."
              : "Patterns persist here once the loop stores them."}
          </EmptyState>
        )}
      </div>
    </div>
  );
}
