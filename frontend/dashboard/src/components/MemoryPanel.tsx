'use client';
import { useDashboard } from '@/lib/state';

type MemoryPattern = {
  id: string;
  timestamp: string;
  pattern: string;
  source: string;
};

export function MemoryPanel() {
  const { logEntries } = useDashboard();

  const memoryEntries = logEntries.filter(e => e.tag === 'memory');

  // Also add some static mock patterns that would have been stored from "previous runs"
  const priorPatterns: MemoryPattern[] = [
    { id: 'mem-1', timestamp: '14:15:00', pattern: 'Schema validation errors correlate with tool description ambiguity', source: 'run-2026-04-24' },
    { id: 'mem-2', timestamp: '14:20:00', pattern: 'Retry logic improves accuracy by 5-8% on schema-sensitive tasks', source: 'run-2026-04-24' },
    { id: 'mem-3', timestamp: '14:25:00', pattern: 'Tool hashing causes regressions when tool signatures collide', source: 'run-2026-04-24' },
  ];

  return (
    <div className="flex flex-col h-full">
      <div className="px-5 py-3 border-b border-border">
        <span className="text-[10px] font-semibold text-text-hi uppercase tracking-wide">Cross-Run Memory</span>
        <span className="ml-2 text-[9px] text-text-mid">{priorPatterns.length + memoryEntries.length} patterns</span>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {/* Prior run patterns */}
        <div className="mb-5">
          <span className="text-[9px] text-text-mid uppercase tracking-wide font-semibold">From previous runs</span>
          <div className="mt-3 flex flex-col gap-3">
            {priorPatterns.map(p => (
              <div key={p.id} className="p-3 rounded bg-header border-l-2 border-amber">
                <div className="text-[11px] text-text-hi leading-[1.6]">{p.pattern}</div>
                <div className="mt-1.5 text-[9px] text-text-ghost">{p.source} · {p.timestamp}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Current run patterns */}
        {memoryEntries.length > 0 && (
          <div>
            <span className="text-[9px] text-text-mid uppercase tracking-wide font-semibold">This run</span>
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

        {memoryEntries.length === 0 && (
          <div className="text-[9px] text-text-ghost uppercase tracking-wide mt-4">
            Waiting for memory patterns from current run...
          </div>
        )}
      </div>
    </div>
  );
}
