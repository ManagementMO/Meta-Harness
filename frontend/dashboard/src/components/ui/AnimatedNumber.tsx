"use client";

import { useEffect, useRef } from "react";
import { animate, useReducedMotion } from "framer-motion";

/** Live numbers breathe — values morph instead of snapping. */
export function AnimatedNumber({
  value,
  format = (v: number) => v.toFixed(2),
  className,
}: {
  value: number;
  format?: (v: number) => string;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const prev = useRef(value);
  const reduced = useReducedMotion();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (reduced || prev.current === value) {
      el.textContent = format(value);
      prev.current = value;
      return;
    }
    const from = prev.current;
    prev.current = value;
    const controls = animate(from, value, {
      duration: 0.3,
      ease: "easeOut",
      onUpdate: (v) => {
        el.textContent = format(v);
      },
    });
    return () => controls.stop();
  }, [value, format, reduced]);

  return (
    <span ref={ref} className={className}>
      {format(value)}
    </span>
  );
}
