'use client';
import { useEffect, useState } from 'react';
import { listMemory } from '@/lib/api';
import { useDashboard } from '@/lib/state';
import type { MemoryEntry } from '@/lib/types';

export function MemoryPanel() {
  const { logEntries, mode } = useDashboard();
  const [storedPatterns, setStoredPatterns] = useState<MemoryEntry[]>([]);

  const memoryEntries = logEntries.filter(e => e.tag === 'memory');
  const totalPatterns = storedPatterns.length + memoryEntries.length;

  useEffect(() => {
    if (mode !== 'live') return;
    let cancelled = false;
    listMemory('coding-agent', 20)
      .then(entries => {
        if (!cancelled) setStoredPatterns(entries);
      })
      .catch(() => {
        if (!cancelled) setStoredPatterns([]);
      });
    return () => {
      cancelled = true;
    };
  }, [mode]);

  return (
    <div className="flex flex-col h-full">
      <div className="px-5 py-3 border-b border-border">
        <span className="text-[10px] font-semibold text-text-hi uppercase tracking-wide">Cross-Run Memory</span>
        <span className="ml-2 text-[9px] text-text-mid">{totalPatterns} patterns</span>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {storedPatterns.length > 0 && (
          <div className="mb-5">
            <span className="text-[9px] text-text-mid uppercase tracking-wide font-semibold">From previous runs</span>
            <div className="mt-3 flex flex-col gap-3">
              {storedPatterns.map(p => (
                <div key={p.key} className="p-3 rounded bg-header border-l-2 border-amber">
                  <div className="text-[11px] text-text-hi leading-[1.6]">{p.pattern}</div>
                  <div className="mt-1.5 text-[9px] text-text-ghost">
                    {p.evidence_run_ids?.join(', ') ?? p.mechanism_axis ?? 'memory'}
                    {p.created_at ? ` · ${new Date(p.created_at).toLocaleString()}` : ''}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {memoryEntries.length > 0 && (
          <div>
            <span className={`text-[9px] uppercase tracking-wide font-semibold ${mode === 'mock' ? 'text-amber' : 'text-text-mid'}`}>
              {mode === 'mock' ? 'Mock run fixture' : 'This run'}
            </span>
            <div className="mt-3 flex flex-col gap-3">
              {memoryEntries.map(e => (
                <div key={e.id} className="p-3 rounded bg-header border-l-2 border-cyan">
                  <div className="text-[11px] text-text-hi leading-[1.6]">{e.text}</div>
                  <div className="mt-1.5 text-[9px] text-text-ghost">{e.timestamp} · {e.candidateName}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {totalPatterns === 0 && (
          <div className="text-[9px] text-text-ghost uppercase tracking-wide mt-4">
            No memory patterns available yet.
          </div>
        )}
      </div>
    </div>
  );
}
