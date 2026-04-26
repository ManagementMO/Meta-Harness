'use client';
import Link from 'next/link';
import { useDashboard } from '@/lib/state';

export function TopBar() {
  const { run } = useDashboard();
  const elapsed = '4m32s'; // static for demo

  return (
    <div className="h-12 flex items-center px-6 bg-header border-b border-border">
      <Link href="/" className="text-cyan text-sm font-semibold tracking-[3px] uppercase hover:text-text-hi transition-colors">META-HARNESS</Link>
    </div>
  );
}
