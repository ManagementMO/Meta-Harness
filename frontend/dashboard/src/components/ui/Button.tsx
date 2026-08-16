"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "ghost" | "quiet";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  // The one loud action on a surface — glacier, reserved.
  primary:
    "bg-glacier/12 border border-glacier/35 text-glacier-bright " +
    "hover:bg-glacier/18 hover:border-glacier/55 active:scale-[0.98]",
  ghost:
    "bg-white/[0.03] border border-white/8 text-ink-mid " +
    "hover:text-ink hover:border-white/14 hover:bg-white/[0.05] active:scale-[0.98]",
  quiet:
    "border border-transparent text-ink-mid hover:text-ink hover:bg-white/[0.04] active:scale-[0.98]",
};

const SIZES: Record<Size, string> = {
  sm: "h-7 px-2.5 gap-1.5 text-[11px]",
  md: "h-9 px-4 gap-2 text-data",
};

export function Button({
  variant = "ghost",
  size = "sm",
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
}) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-[var(--radius-control)] font-mono uppercase tracking-[0.08em]",
        "transition-[color,background-color,border-color,transform] duration-150 ease-[var(--ease-glass)]",
        "disabled:opacity-40 disabled:pointer-events-none cursor-pointer select-none whitespace-nowrap",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
