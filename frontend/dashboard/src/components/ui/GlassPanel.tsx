import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Floating glass island — the primary surface of the instrument. */
export function GlassPanel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "glass-panel rounded-[var(--radius-panel)] flex flex-col min-h-0 min-w-0 overflow-hidden",
        className,
      )}
    >
      {children}
    </section>
  );
}

/** Panel header with a specular sheen — reads as the polished top of the glass. */
export function PanelHeader({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "panel-sheen flex items-center gap-3 h-10 px-4 border-b border-white/6 shrink-0",
        className,
      )}
    >
      {children}
    </header>
  );
}

export function PanelTitle({
  children,
  icon,
}: {
  children: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      {icon && <span className="text-ink-low shrink-0">{icon}</span>}
      <h2 className="text-label uppercase text-ink-mid truncate">{children}</h2>
    </div>
  );
}
