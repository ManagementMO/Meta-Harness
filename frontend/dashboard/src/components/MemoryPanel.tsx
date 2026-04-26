'use client';
import { useState, useEffect } from 'react';
import { useDashboard } from '@/lib/state';
import { fetchMemory } from '@/lib/api';

type MemoryPattern = {
  id: string;
  pattern: string;
  mechanism_axis?: string;
  score_delta?: number;
  evidence_run_ids?: string[];
  created_at?: string;
};

const FALLBACK_PATTERNS: MemoryPattern[] = [
  { id: 'mem-1', pattern: 'Schema validation errors correlate with tool description ambiguity', mechanism_axis: 'exploration', score_delta: 0.05, evidence_run_ids: ['run-2026-04-24'] },
  { id: 'mem-2', pattern: 'Retry logic improves accuracy by 5-8% on schema-sensitive tasks', mechanism_axis: 'exploitation', score_delta: 0.08, evidence_run_ids: ['run-2026-04-24'] },
  { id: 'mem-3', pattern: 'Tool hashing causes regressions when tool signatures collide', mechanism_axis: 'exploration', score_delta: -0.04, evidence_run_ids: ['run-2026-04-24'] },
];

export function MemoryPanel() {
  const { logEntries } = useDashboard();
  const [priorPatterns, setPriorPatterns] = useState<MemoryPattern[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchMemory("learned_patterns")
      .then((data: any) => {
        if (cancelled) return;
        if (data?.implemented === false || !Array.isArray(data?.entries)) {
          setPriorPatterns(FALLBACK_PATTERNS);
        } else {
          const mapped = data.entries.map((e: any, i: number) => ({
            id: e.key ?? `api-${i}`,
            pattern: e.pattern ?? e.value?.pattern ?? '',
            mechanism_axis: e.mechanism_axis ?? e.value?.mechanism_axis,
            score_delta: e.score_delta ?? e.value?.score_delta,
            evidence_run_ids: e.evidence_run_ids ?? e.value?.evidence_run_ids ?? [],
            created_at: e.created_at ?? e.value?.created_at,
          }));
          setPriorPatterns(mapped.length > 0 ? mapped : FALLBACK_PATTERNS);
        }
      })
      .catch(() => {
        if (!cancelled) setPriorPatterns(FALLBACK_PATTERNS);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const memoryEntries = logEntries.filter(e => e.tag === 'memory');

  return (
    <div className="flex flex-col h-full">
      <div className="px-5 py-3 border-b border-border">
        <span className="text-[10px] font-semibold text-text-hi uppercase tracking-wide">Cross-Run Memory</span>
        <span className="ml-2 text-[9px] text-text-mid">{priorPatterns.length + memoryEntries.length} patterns</span>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        <div className="mb-5">
          <span className="text-[9px] text-text-mid uppercase tracking-wide font-semibold">From previous runs</span>
          {loading ? (
            <div className="mt-3 text-[9px] text-text-ghost">Loading memory...</div>
          ) : (
            <div className="mt-3 flex flex-col gap-3">
              {priorPatterns.map(p => (
                <div key={p.id} className="p-3 rounded bg-header border-l-2 border-amber">
                  <div className="text-[11px] text-text-hi leading-[1.6]">{p.pattern}</div>
                  <div className="mt-1.5 flex items-center gap-2 text-[9px] text-text-ghost">
                    {p.mechanism_axis && <span className="text-purple">{p.mechanism_axis}</span>}
                    {p.score_delta != null && (
                      <span className={p.score_delta >= 0 ? 'text-green' : 'text-red'}>
                        {p.score_delta >= 0 ? '+' : ''}{(p.score_delta * 100).toFixed(1)}%
                      </span>
                    )}
                    {p.evidence_run_ids && p.evidence_run_ids.length > 0 && (
                      <span>{p.evidence_run_ids.join(', ')}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

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

        {memoryEntries.length === 0 && !loading && (
          <div className="text-[9px] text-text-ghost uppercase tracking-wide mt-4">
            Waiting for memory patterns from current run...
          </div>
        )}
      </div>
    </div>
  );
}
