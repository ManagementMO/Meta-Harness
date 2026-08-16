"use client";

import { useDashboard } from "@/lib/state";
import { cn } from "@/lib/cn";

function Divider() {
  return <span aria-hidden="true" className="h-3 w-px bg-white/6 shrink-0" />;
}

export function StatusBar() {
  const { sseConnected, run, mode, latestCheckpointId, lastError } = useDashboard();
  const ckpt = latestCheckpointId ?? run?.checkpointId;

  return (
    <div className="relative z-10 h-8 flex items-center gap-3 px-4 border-t border-white/6 bg-white/[0.014] backdrop-blur-[14px] shrink-0 font-mono text-[10px] tracking-[0.05em] text-ink-low whitespace-nowrap overflow-hidden">
      <span className="flex items-center gap-1.5 shrink-0">
        <span
          aria-hidden="true"
          className={cn(
            "w-1.5 h-1.5 rounded-full",
            sseConnected
              ? "bg-glacier shadow-[0_0_6px_rgba(105,227,213,0.5)] animate-breathe"
              : "bg-ember",
          )}
        />
        <span className={sseConnected ? "text-ink-mid" : "text-ember"}>
          {sseConnected ? "SSE connected" : "Disconnected"}
        </span>
      </span>

      <Divider />
      <span className={cn("shrink-0", run?.isSynthetic || mode === "mock" ? "text-sand" : "text-moss")}>
        {run?.isSynthetic
          ? "Synthetic fixture — not a research result"
          : mode === "mock"
            ? "Mock mode"
            : `${run?.mode ?? "research"} data`}
      </span>

      <span className="hidden lg:flex items-center gap-3 min-w-0">
        <Divider />
        <span>{run?.persistence === "postgres" ? "durable checkpoints" : "degraded memory checkpoints"}</span>
        <Divider />
        <span className="hidden xl:inline">{run?.securityProfile ?? "trusted-local-process-isolation"}</span>
      </span>

      <Divider />
      <span className="shrink-0">{run?.branches ?? 0} branches</span>
      <Divider />
      <span className="shrink-0 text-ink-mid" title={ckpt ?? undefined}>
        ckpt {ckpt ? `${ckpt.slice(0, 8)}…${ckpt.slice(-4)}` : "—"}
      </span>

      {lastError && (
        <>
          <Divider />
          <span className="text-ember truncate" title={lastError}>
            err: {lastError}
          </span>
        </>
      )}

      <span className="ml-auto text-ink-ghost shrink-0">v0.1.0</span>
    </div>
  );
}
