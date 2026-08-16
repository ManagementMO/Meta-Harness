"use client";

import { cn } from "@/lib/cn";

export type PillState =
  | "live"
  | "reconnecting"
  | "completed"
  | "failed"
  | "demo"
  | "idle";

const STATES: Record<PillState, { label: string; dot: string; pill: string; breathe?: boolean }> = {
  live: {
    label: "Live",
    dot: "bg-frost shadow-[0_0_8px_rgba(255,255,255,0.4)]",
    pill: "text-frost-bright border-frost/35 bg-frost/10",
    breathe: true,
  },
  reconnecting: {
    label: "Reconnecting",
    dot: "bg-transparent border border-sand",
    pill: "text-sand border-sand/30 bg-sand/8",
  },
  completed: {
    label: "Completed",
    dot: "bg-moss",
    pill: "text-moss border-moss/28 bg-moss/8",
  },
  failed: {
    label: "Failed",
    dot: "bg-ember",
    pill: "text-ember border-ember/30 bg-ember/8",
  },
  demo: {
    label: "Demo replay",
    dot: "bg-sand",
    pill: "text-sand border-sand/30 bg-sand/8",
    breathe: true,
  },
  idle: {
    label: "Idle",
    dot: "bg-ink-low",
    pill: "text-ink-mid border-white/10 bg-white/[0.03]",
  },
};

/** Run lifecycle pill — the only element allowed an infinite animation. */
export function StatusPill({
  state,
  label,
  className,
}: {
  state: PillState;
  label?: string;
  className?: string;
}) {
  const spec = STATES[state];
  return (
    <span
      data-testid="status-pill"
      className={cn(
        "inline-flex items-center gap-1.5 h-6 px-2.5 rounded-full border font-mono text-[10px] uppercase tracking-[0.1em] whitespace-nowrap",
        spec.pill,
        className,
      )}
    >
      <span
        className={cn("w-1.5 h-1.5 rounded-full shrink-0", spec.dot, spec.breathe && "animate-breathe")}
      />
      {label ?? spec.label}
    </span>
  );
}
