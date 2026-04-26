'use client';
import { useDashboard } from '@/lib/state';

export function StatusBar() {
  const { sseConnected, run, mode } = useDashboard();
  return (
    <div className="h-7 flex items-center gap-6 px-6 bg-header border-t border-border text-[10px] tracking-wide text-text-lo uppercase">
      <span className="flex items-center gap-1.5">
        <span className={`w-1.5 h-1.5 rounded-full ${sseConnected ? 'bg-green' : 'bg-red'}`} />
        {sseConnected ? 'SSE connected' : 'Disconnected'}
      </span>
      <span className={mode === 'mock' ? 'text-amber' : 'text-green'}>
        {run?.isMock ? 'Mock run data' : mode === 'mock' ? 'Mock mode' : 'Live data'}
      </span>
      <span>{run?.branches ?? 0} branches</span>
      <span>ckpt: {run?.checkpointId ?? '—'}</span>
      <span className="ml-auto">v0.1.0</span>
    </div>
  );
}
