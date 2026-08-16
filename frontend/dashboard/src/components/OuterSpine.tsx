"use client";

import { useEffect, useRef, useState } from "react";
import { useDashboard } from "@/lib/state";
import { PhasePipeline } from "./ui/PhasePipeline";
import { AnimatedNumber } from "./ui/AnimatedNumber";
import { DeltaChip } from "./ui/MonoStat";
import { cn } from "@/lib/cn";

/**
 * The living spine of mission control: the outer-loop pipeline plus the
 * headline readouts. A single restrained shimmer sweeps it when an
 * iteration completes.
 */
export function OuterSpine() {
  const { run, tree, iterations } = useDashboard();

  const latest = iterations.at(-1);
  const running = latest?.status === "running";
  const phases = latest?.phases ?? {
    propose: false,
    validate: false,
    benchmark: false,
    frontier: false,
  };

  const best = tree.find((n) => n.status === "best");
  const bestScore = best?.scores.accuracy ?? run?.bestScore ?? null;
  const latestDelta =
    tree.length > 0
      ? [...tree].sort((a, b) => b.iteration - a.iteration)[0]?.delta ?? null
      : null;
  const frontierSize = tree.filter((n) => n.status === "accepted" || n.status === "best").length;

  // One shimmer per sealed iteration — never a loop.
  const sealedCount = iterations.filter((i) => i.status !== "running").length;
  const prevSealed = useRef(sealedCount);
  const [shimmerKey, setShimmerKey] = useState(0);
  useEffect(() => {
    if (sealedCount > prevSealed.current) setShimmerKey((k) => k + 1);
    prevSealed.current = sealedCount;
  }, [sealedCount]);

  return (
    <div className="relative z-10 h-12 flex items-center justify-between gap-4 px-4 border-b border-white/6 bg-white/[0.014] backdrop-blur-[14px] shrink-0 overflow-hidden">
      {shimmerKey > 0 && <span key={shimmerKey} className="spine-shimmer" aria-hidden="true" />}

      <div className="flex items-center gap-4 min-w-0">
        <span className="hidden xl:block text-label uppercase text-ink-ghost shrink-0">Outer loop</span>
        <PhasePipeline variant="spine" phases={phases} running={running} />
        {latest && (
          <span className="hidden 2xl:block font-mono text-[11px] text-ink-low truncate max-w-[26ch]">
            {latest.candidateName}
          </span>
        )}
      </div>

      <div className="flex items-center gap-5 shrink-0 font-mono tabular-nums">
        <SpineStat label="iter">
          <AnimatedNumber
            value={run?.iteration ?? 0}
            format={(v) => String(Math.round(v)).padStart(2, "0")}
            className="text-[15px] font-medium text-ink"
          />
        </SpineStat>
        <SpineStat label="best">
          {bestScore === null ? (
            <span className="text-[15px] text-ink-ghost">—</span>
          ) : (
            <AnimatedNumber
              value={bestScore}
              className={cn("text-[15px] font-medium", best ? "text-frost-bright" : "text-ink")}
            />
          )}
        </SpineStat>
        <SpineStat label="Δ">
          {latestDelta === null ? (
            <span className="text-[15px] text-ink-ghost">—</span>
          ) : (
            <DeltaChip delta={latestDelta} />
          )}
        </SpineStat>
        <SpineStat label="frontier" className="hidden md:flex">
          <AnimatedNumber
            value={frontierSize}
            format={(v) => String(Math.round(v))}
            className="text-[15px] font-medium text-ink"
          />
        </SpineStat>
      </div>
    </div>
  );
}

function SpineStat({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span className={cn("flex items-baseline gap-1.5", className)}>
      <span className="text-label uppercase text-ink-ghost">{label}</span>
      {children}
    </span>
  );
}
