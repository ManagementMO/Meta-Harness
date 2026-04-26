'use client';
import Link from 'next/link';
import { useDashboard } from '@/lib/state';

export function TopBar() {
  const { run, mode } = useDashboard();

  return (
    <div className="h-12 flex items-center justify-between px-6 bg-header border-b border-border">
      <Link href="/" className="text-cyan text-sm font-semibold tracking-[3px] uppercase hover:text-text-hi transition-colors">META-HARNESS</Link>
      {run && (
        <span className="text-[10px] text-text-mid uppercase tracking-wide">
          {run.isMock ? 'mock run' : mode} · {run.status} · iter {run.iteration}
        </span>
      )}
    </div>
  );
}
