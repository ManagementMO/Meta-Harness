import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { AnimatedNumber } from "./AnimatedNumber";

/** Labeled monospace figure — the atomic readout of the instrument. */
export function MonoStat({
  label,
  value,
  format,
  fallback = "—",
  tone = "ink",
  size = "md",
  suffix,
  className,
}: {
  label: string;
  value: number | null | undefined;
  format?: (v: number) => string;
  fallback?: string;
  tone?: "ink" | "glacier" | "moss" | "ember" | "iris";
  size?: "md" | "lg";
  suffix?: ReactNode;
  className?: string;
}) {
  const toneClass = {
    ink: "text-ink",
    glacier: "text-glacier-bright",
    moss: "text-moss",
    ember: "text-ember",
    iris: "text-iris",
  }[tone];

  return (
    <div className={cn("flex flex-col gap-0.5 min-w-0", className)}>
      <span className="text-label uppercase text-ink-low whitespace-nowrap">{label}</span>
      <span
        className={cn(
          "font-mono tabular-nums flex items-baseline gap-1.5",
          size === "lg" ? "text-stat" : "text-[15px] leading-5 font-medium",
          toneClass,
        )}
      >
        {value === null || value === undefined ? (
          <span className="text-ink-ghost">{fallback}</span>
        ) : (
          <AnimatedNumber value={value} format={format} />
        )}
        {suffix}
      </span>
    </div>
  );
}

/** Signed delta chip, moss for gains and ember for losses. */
export function DeltaChip({ delta }: { delta: number | null }) {
  if (delta === null) return null;
  const positive = delta >= 0;
  return (
    <span
      className={cn(
        "font-mono tabular-nums text-[11px] leading-none",
        positive ? "text-moss" : "text-ember",
      )}
    >
      {positive ? "+" : ""}
      {delta.toFixed(2)}
    </span>
  );
}
