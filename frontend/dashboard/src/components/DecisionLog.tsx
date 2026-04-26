'use client';
import { useRef, useEffect, useState } from 'react';
import { useDashboard, useDashboardDispatch } from '@/lib/state';
import { FilterBar } from './ui/FilterBar';
import { Badge } from './ui/Badge';
import { PhasePipeline } from './ui/PhasePipeline';
import { ForkEventCard } from './ForkEvent';
import type { LogTag } from '@/lib/types';

const TAG_COLORS: Record<LogTag, string> = {
  orient: 'text-[#606888]',
  plan: 'text-blue',
  'tool/read': 'text-green',
  'tool/patch': 'text-green',
  act: 'text-cyan',
  verify: 'text-amber',
  score: 'text-green',
  fail: 'text-red',
  fork: 'text-purple',
  memory: 'text-amber',
};

export function DecisionLog() {
  const { iterations, logEntries, forkEvents, filters, selectedLogLine } = useDashboard();
  const dispatch = useDashboardDispatch();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [expandedLines, setExpandedLines] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logEntries.length, autoScroll]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 50);
  };

  const filteredEntries = logEntries.filter(e => {
    if (filters.activeFilter === 'all') return true;
    if (filters.activeFilter === 'tools') return e.tag.startsWith('tool/');
    if (filters.activeFilter === 'verify') return e.tag === 'verify';
    if (filters.activeFilter === 'scores') return e.tag === 'score';
    if (filters.activeFilter === 'forks') return e.tag === 'fork' || e.tag === 'memory';
    return true;
  }).filter(e => !filters.searchQuery || e.text.toLowerCase().includes(filters.searchQuery.toLowerCase()));

  const toggleExpand = (id: string) => {
    setExpandedLines(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  return (
    <div className="flex-1 flex flex-col bg-panel rounded overflow-hidden min-h-0">
      <div className="flex items-center justify-between px-6 py-3 bg-header border-b border-border">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-text-hi uppercase tracking-wide">Decision Log</span>
          <span className="flex items-center gap-1.5 text-[9px] text-green font-semibold uppercase">
            <span className="w-1.5 h-1.5 rounded-full bg-green" />
            Live
          </span>
        </div>
        <FilterBar
          filters={['all', 'tools', 'verify', 'scores', 'forks']}
          active={filters.activeFilter}
          onSelect={f => dispatch({ type: 'SET_FILTER', payload: { activeFilter: f as any } })}
        />
      </div>

      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-6 py-5">
        {forkEvents.map((fork, i) => (
          <ForkEventCard key={i} fork={fork} />
        ))}

        {iterations.map(chapter => {
          const chapterEntries = filteredEntries.filter(e => e.candidateName === chapter.candidateName);
          return (
            <div key={chapter.candidateName} className="mb-6">
              <div className={`border-l-[3px] ${chapter.isForkBranch ? 'border-purple' : 'border-border-active'} pl-4 py-3 mb-4`}>
                <div className="flex items-center gap-3 mb-1.5">
                  <span className={`text-[13px] font-semibold ${chapter.isForkBranch ? 'text-purple' : 'text-text-hi'}`}>
                    ITER {chapter.iteration}{chapter.isForkBranch ? "'" : ''} — {chapter.candidateName}
                  </span>
                  {chapter.status === 'accepted' && <Badge label="Accepted" color="green" />}
                  {chapter.status === 'rejected' && <Badge label="Rejected" color="red" />}
                </div>
                <PhasePipeline phases={chapter.phases} />
                <p className="text-text-mid text-xs italic mt-2 leading-relaxed">{chapter.hypothesis}</p>
              </div>

              <div className="flex flex-col gap-[14px]">
                {chapterEntries.map(entry => (
                  <div key={entry.id}>
                    <div
                      className={`flex items-start gap-3 cursor-pointer group ${
                        selectedLogLine === entry.id ? 'border-l-2 border-cyan pl-2 -ml-2' : ''
                      }`}
                      onClick={() => {
                        dispatch({ type: 'SELECT_LOG_LINE', payload: entry.id });
                        if (entry.expandable) toggleExpand(entry.id);
                      }}
                    >
                      <span className="text-text-ghost text-[10px] w-14 shrink-0 pt-0.5">{entry.timestamp}</span>
                      <span className={`px-2 py-0.5 bg-hover rounded text-[9px] font-semibold uppercase tracking-wide shrink-0 ${TAG_COLORS[entry.tag]}`}>
                        {entry.tag}
                      </span>
                      <span className="text-text-hi text-[13px] leading-[1.7]">{entry.text}</span>
                      {entry.expandable && (
                        <span className="text-text-ghost text-xs ml-auto shrink-0">
                          {expandedLines.has(entry.id) ? '▾' : '▸'}
                        </span>
                      )}
                    </div>
                    {entry.expandable && expandedLines.has(entry.id) && entry.expandedContent && (
                      <pre className="mt-2 ml-[78px] p-3 bg-header rounded text-[11px] text-text-mid overflow-x-auto">{entry.expandedContent}</pre>
                    )}
                  </div>
                ))}
              </div>

              {chapter.status !== 'running' && chapterEntries.some(e => e.tag === 'score') && (
                <div className={`mt-4 flex items-center justify-between px-4 py-3 rounded border-l-[3px] ${
                  chapter.status === 'accepted' ? 'border-green bg-green-bg' : 'border-red bg-red-bg'
                }`}>
                  <span className={`text-[10px] font-semibold uppercase tracking-wide ${chapter.status === 'accepted' ? 'text-green' : 'text-red'}`}>
                    Accuracy — {chapter.status}
                  </span>
                  <div className="flex items-center gap-2">
                    <span className="text-text-hi text-base font-semibold">
                      {chapterEntries.find(e => e.tag === 'score')?.text.match(/[\d.]+/)?.[0] ?? '—'}
                    </span>
                    <span className={`text-xs ${chapter.status === 'accepted' ? 'text-cyan' : 'text-red'}`}>
                      {chapterEntries.find(e => e.tag === 'score')?.text.match(/[+-][\d.]+/)?.[0] ?? ''}
                    </span>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {!autoScroll && (
          <button
            onClick={() => {
              setAutoScroll(true);
              scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
            }}
            className="fixed bottom-12 left-1/2 -translate-x-1/2 px-4 py-2 bg-header border border-border rounded text-xs text-text-mid hover:text-text-hi"
          >
            {'↓'} Jump to latest
          </button>
        )}
      </div>
    </div>
  );
}
