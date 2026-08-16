import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** An empty screen is an invitation, not an apology. */
export function EmptyState({
  icon,
  title,
  children,
  className,
}: {
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 px-6 py-10 text-center", className)}>
      {icon && <span className="text-ink-ghost mb-1">{icon}</span>}
      <p className="text-label uppercase text-ink-low">{title}</p>
      {children && <div className="text-data font-mono text-ink-ghost max-w-[36ch]">{children}</div>}
    </div>
  );
}
