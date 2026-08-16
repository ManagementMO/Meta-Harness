"use client";

import { cn } from "@/lib/cn";

export function FilterBar<T extends string>({
  filters,
  active,
  onSelect,
}: {
  filters: readonly T[];
  active: T;
  onSelect: (f: T) => void;
}) {
  return (
    <div role="group" aria-label="Log filters" className="flex items-center gap-0.5">
      {filters.map((f) => {
        const isActive = active === f;
        return (
          <button
            key={f}
            aria-pressed={isActive}
            onClick={() => onSelect(f)}
            className={cn(
              "h-6 px-2 rounded-[6px] font-mono text-[10px] uppercase tracking-[0.08em] cursor-pointer",
              "transition-colors duration-150 ease-[var(--ease-glass)]",
              isActive
                ? "glass-inset text-ink border-white/10"
                : "text-ink-low hover:text-ink-mid",
            )}
          >
            {f}
          </button>
        );
      })}
    </div>
  );
}
