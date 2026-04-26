'use client';
import { useDashboard } from '@/lib/state';

export function TopBar() {
  const { run } = useDashboard();
  const elapsed = '4m32s'; // static for demo

  return (
    <div className="h-12 flex items-center justify-between px-6 bg-header border-b border-border">
      <span className="text-cyan text-sm font-semibold tracking-[3px] uppercase">META-HARNESS</span>
      <div className="flex items-center gap-2 text-text-mid text-xs">
        <span className="w-2 h-2 rounded-full bg-green inline-block" />
        <span className="text-text-hi">{run?.runId ?? '—'}</span>
      </div>
      <div className="flex items-center gap-4 text-xs text-text-mid">
        <span>iter <span className="text-text-hi">{run?.currentIteration ?? 0}/{run?.budget ?? 5}</span></span>
        <span>best <span className="text-cyan font-semibold">{run?.bestScore?.toFixed(2) ?? '—'}</span></span>
        <span>${run?.costUsd?.toFixed(2) ?? '0.00'}</span>
        <span>{elapsed}</span>
      </div>
    </div>
  );
}
