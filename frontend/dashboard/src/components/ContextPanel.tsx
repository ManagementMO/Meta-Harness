'use client';
import { useDashboard, useDashboardDispatch } from '@/lib/state';
import { ScoreChart } from './ScoreChart';
import { DiffViewer } from './DiffViewer';
import { TestOutput } from './TestOutput';
import { MemoryPanel } from './MemoryPanel';
import { getDiff, getTestOutput } from '@/lib/api';

export function ContextPanel() {
  const { contextTab, selectedNode, tree } = useDashboard();
  const dispatch = useDashboardDispatch();

  const tabs = ['chart', 'diff', 'test', 'memory'] as const;
  const selected = selectedNode ?? tree.find(n => n.status === 'best')?.candidate ?? 'few-shot-demos';
  const diff = getDiff();
  const testOut = getTestOutput();

  return (
    <div className="flex-1 flex flex-col bg-panel rounded overflow-hidden min-h-0">
      <div className="h-11 flex items-center gap-1 px-6 bg-header border-b border-border shrink-0">
        {tabs.map(tab => (
          <button
            key={tab}
            onClick={() => dispatch({ type: 'SET_CONTEXT_TAB', payload: tab })}
            className={`px-3 py-1.5 text-[9px] font-semibold uppercase tracking-wide rounded transition-colors ${contextTab === tab
                ? 'text-cyan border-b-2 border-cyan'
                : 'text-text-mid hover:text-text-hi'
              }`}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="flex-1 flex flex-col overflow-y-auto px-6 py-5 min-h-0">
        {contextTab === 'chart' && <div className="flex-1"><ScoreChart /></div>}

        {contextTab === 'diff' && diff && (() => {
          const added = diff.split('\n').filter(l => l.startsWith('+') && !l.startsWith('+++')).length;
          const removed = diff.split('\n').filter(l => l.startsWith('-') && !l.startsWith('---')).length;
          return (
            <div className="flex-1 flex flex-col min-h-0">
              <div className="flex items-center gap-2 mb-4 text-xs shrink-0">
                <span className="text-text-hi font-semibold">agents/{selected}.py</span>
                <span className="text-green">+{added}</span>
                <span className="text-red">-{removed}</span>
              </div>
              <div className="flex-1 min-h-0">
                <DiffViewer diff={diff} />
              </div>
            </div>
          );
        })()}
        {contextTab === 'diff' && !diff && (
          <div className="text-text-mid text-xs">No diff available for {selected}</div>
        )}

        {contextTab === 'test' && testOut && <TestOutput output={testOut} />}
        {contextTab === 'test' && !testOut && (
          <div className="text-text-mid text-xs">No test output available for {selected}</div>
        )}

        {contextTab === 'memory' && <MemoryPanel />}
      </div>
    </div>
  );
}
