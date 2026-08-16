"use client";

import { cn } from "@/lib/cn";

/** Machined segmented switch — options sit in a recessed well. */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  className,
}: {
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel: string;
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cn("well inline-flex items-center gap-0.5 p-0.5 rounded-[9px]", className)}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "h-6 px-2.5 rounded-[7px] font-mono text-[10px] uppercase tracking-[0.08em] cursor-pointer whitespace-nowrap",
              "transition-colors duration-150 ease-[var(--ease-glass)]",
              active
                ? "glass-inset specular-top text-glacier-bright border-white/10"
                : "text-ink-low hover:text-ink-mid",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
