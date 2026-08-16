"use client";

import { cn } from "@/lib/cn";
import { IconCheck } from "./icons";

type Phases = { propose: boolean; validate: boolean; benchmark: boolean; frontier: boolean };

const STAGES = ["propose", "validate", "benchmark", "frontier"] as const;

/**
 * The outer-loop pipeline: propose → validate → benchmark → frontier.
 * `spine` renders the living pipeline in the command bar; `compact` seals
 * each iteration chapter in the decision log.
 */
export function PhasePipeline({
  phases,
  variant = "compact",
  running = false,
}: {
  phases: Phases;
  variant?: "spine" | "compact";
  running?: boolean;
}) {
  const activeStage = running ? STAGES.find((s) => !phases[s]) : undefined;

  if (variant === "spine") {
    return (
      <ol className="flex items-center" aria-label="Outer loop pipeline">
        {STAGES.map((stage, i) => {
          const done = phases[stage];
          const active = stage === activeStage;
          return (
            <li key={stage} className="flex items-center">
              {i > 0 && (
                <span
                  aria-hidden="true"
                  className={cn(
                    "block w-6 h-px mx-1.5 transition-colors duration-300",
                    done || active ? "bg-frost/40" : "bg-white/8",
                  )}
                />
              )}
              <span
                className={cn(
                  "flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.1em] whitespace-nowrap transition-colors duration-300",
                  done ? "text-frost" : active ? "text-frost-bright" : "text-ink-ghost",
                )}
              >
                <span
                  className={cn(
                    "flex items-center justify-center w-3.5 h-3.5 rounded-full border transition-colors duration-300",
                    done
                      ? "border-frost/50 bg-frost/15"
                      : active
                        ? "border-frost/60 bg-frost/10 animate-breathe"
                        : "border-white/12 bg-transparent",
                  )}
                >
                  {done && <IconCheck size={8} />}
                </span>
                {stage}
              </span>
            </li>
          );
        })}
      </ol>
    );
  }

  return (
    <ol className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.06em]" aria-label="Iteration phases">
      {STAGES.map((stage, i) => {
        const done = phases[stage];
        const active = stage === activeStage;
        return (
          <li key={stage} className="flex items-center gap-1">
            {i > 0 && <span aria-hidden="true" className="w-3 h-px bg-white/8" />}
            <span
              className={cn(
                "flex items-center gap-1 transition-colors duration-300",
                done ? "text-ink-mid" : active ? "text-frost" : "text-ink-ghost",
              )}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "w-1 h-1 rounded-full",
                  done ? "bg-moss" : active ? "bg-frost animate-breathe" : "bg-white/12",
                )}
              />
              {stage}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
