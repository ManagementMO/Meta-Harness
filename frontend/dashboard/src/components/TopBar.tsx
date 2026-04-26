'use client';
import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useDashboard, useDashboardDispatch } from '@/lib/state';
import { startMockSSE } from '@/lib/sse';

export function TopBar() {
  const { run, sseConnected, tree, iterations } = useDashboard();
  const dispatch = useDashboardDispatch();
  const [elapsed, setElapsed] = useState(0);
  const [mockCleanup, setMockCleanup] = useState<(() => void) | null>(null);
  const [mockRunning, setMockRunning] = useState(false);

  useEffect(() => {
    if (!mockRunning) return;
    const interval = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(interval);
  }, [mockRunning]);

  const formatElapsed = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}m${sec.toString().padStart(2, '0')}s`;
  };

  const handleMock = useCallback(() => {
    if (mockCleanup) mockCleanup();
    setElapsed(0);
    setMockRunning(true);
    const cleanup = startMockSSE(dispatch, 1);
    setMockCleanup(() => cleanup);
  }, [dispatch, mockCleanup]);

  const bestScore = run?.bestScore ?? (tree.length > 0
    ? Math.max(...tree.map(n => n.scores.accuracy))
    : null);

  const iterCount = iterations.length;
  const accepted = tree.filter(n => n.status === 'accepted' || n.status === 'best').length;
  const rejected = tree.filter(n => n.status === 'rejected').length;

  return (
    <div className="h-12 flex items-center justify-between px-6 bg-header border-b border-border">
      <div className="flex items-center gap-6">
        <Link href="/" className="text-cyan text-sm font-semibold tracking-[3px] uppercase hover:text-text-hi transition-colors">
          META-HARNESS
        </Link>

        {run && (
          <div className="flex items-center gap-5 text-[10px] uppercase tracking-wide">
            <span className="text-text-mid">
              <span className="text-text-ghost mr-1">RUN</span>
              <span className="text-text-hi">{run.runId}</span>
            </span>

            {bestScore !== null && (
              <span className="text-text-mid">
                <span className="text-text-ghost mr-1">BEST</span>
                <span className="text-cyan font-semibold">{(bestScore * 100).toFixed(0)}%</span>
              </span>
            )}

            <span className="text-text-mid">
              <span className="text-text-ghost mr-1">ITER</span>
              <span className="text-text-hi">{iterCount}</span>
            </span>

            {(accepted > 0 || rejected > 0) && (
              <span className="text-text-mid">
                <span className="text-green">{accepted}</span>
                <span className="text-text-ghost mx-0.5">/</span>
                <span className="text-red">{rejected}</span>
              </span>
            )}

            {mockRunning && (
              <span className="text-text-mid">
                <span className="text-text-ghost mr-1">TIME</span>
                <span className="text-text-hi">{formatElapsed(elapsed)}</span>
              </span>
            )}
          </div>
        )}
      </div>

      <div className="flex items-center gap-4">
        {sseConnected && (
          <span className="flex items-center gap-1.5 text-[9px] text-green font-semibold uppercase tracking-wide">
            <span
              className="w-1.5 h-1.5 rounded-full bg-green"
              style={{ animation: 'pulse-dot 2s ease-in-out infinite' }}
            />
            LIVE
          </span>
        )}

        <button
          onClick={handleMock}
          className="px-3 py-1.5 text-[9px] font-semibold uppercase tracking-wider rounded border border-purple/40 text-purple hover:bg-purple/10 hover:border-purple transition-colors cursor-pointer"
        >
          {mockRunning ? 'Restart Mock' : 'Mock'}
        </button>
      </div>
    </div>
  );
}
