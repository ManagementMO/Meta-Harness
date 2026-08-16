"use client";

import { cn } from "@/lib/cn";
import { IconTerminalWindow } from "./ui/icons";

/** Embedded glass console — verification output reads like an instrument tape. */
export function TestOutput({ output }: { output: string }) {
  const lines = output.split("\n");

  return (
    <div className="well rounded-[var(--radius-card)] overflow-hidden flex flex-col min-h-0">
      <div className="flex items-center gap-2 h-8 px-3 border-b border-white/5 shrink-0">
        <IconTerminalWindow size={12} className="text-ink-ghost" />
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-low">
          verification output
        </span>
        <span className="ml-auto font-mono text-[10px] text-ink-ghost tabular-nums">
          {lines.length} lines
        </span>
      </div>
      <pre className="flex-1 overflow-auto px-3 py-2.5 font-mono text-[11.5px] leading-[1.7] tabular-nums">
        {lines.map((line, i) => {
          const lower = line.toLowerCase();
          const pass = lower.includes("passed") || line.includes("PASS");
          const fail = lower.includes("failed") || line.includes("FAIL") || line.includes("Error");
          const flaky = line.includes("FLAKY");
          return (
            <div
              key={i}
              className={cn(
                fail ? "text-ember" : flaky ? "text-sand" : pass ? "text-moss" : "text-ink-mid",
              )}
            >
              {line || " "}
            </div>
          );
        })}
      </pre>
    </div>
  );
}
