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
  const selected = selectedNode ?? tree.find(n => n.status === 'best')?.candidate ?? tree[0]?.candidate ?? null;
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

        {contextTab === 'diff' && diff && (
          <div>
            <div className="flex items-center gap-2 mb-4 text-xs">
              <span className="text-text-hi font-semibold">agents/{selected ?? 'candidate'}.py</span>
              <span className="text-green">+18</span>
              <span className="text-red">-3</span>
            </div>
            <DiffViewer diff={diff} />
          </div>
        )}
        {contextTab === 'diff' && !diff && (
          <div className="text-text-mid text-xs">
            {selected ? `No diff available for ${selected}` : 'No candidate selected yet.'}
          </div>
        )}

        {contextTab === 'test' && testOut && <TestOutput output={testOut} />}
        {contextTab === 'test' && !testOut && (
          <div className="text-text-mid text-xs">
            {selected ? `No test output available for ${selected}` : 'No candidate selected yet.'}
          </div>
        )}

        {contextTab === 'memory' && <MemoryPanel />}
      </div>
    </div>
  );
}
