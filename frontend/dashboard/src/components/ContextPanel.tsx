'use client';
import { useDashboard, useDashboardDispatch } from '@/lib/state';
import { ScoreChart } from './ScoreChart';
import { DiffViewer } from './DiffViewer';
import { TestOutput } from './TestOutput';
import { MemoryPanel } from './MemoryPanel';
import { getDiff, getTestOutput } from '@/lib/api';

export function ContextPanel() {
  const { contextTab, selectedNode, tree, mode } = useDashboard();
  const dispatch = useDashboardDispatch();

  const tabs = ['chart', 'diff', 'test', 'memory'] as const;
  const selected = selectedNode ?? tree.find(n => n.status === 'best')?.candidate ?? tree[0]?.candidate ?? null;
  const selectedTreeNode = tree.find(n => n.candidate === selected) ?? null;
  const diff = getDiff();
  const testOut = getTestOutput();
  const perTask = Object.entries(selectedTreeNode?.scores.per_task ?? {});
  const hasMockTaskData = mode === 'mock' && perTask.length > 0;

  const mockDiffPreview = hasMockTaskData
    ? perTask
      .slice(0, 4)
      .map(([taskName, stats]) => {
        const passPct = Math.round(stats.pass_rate * 100);
        return `@@ task:${taskName}
-${taskName}: unstable retries (${passPct - 10}% pass)
+${taskName}: stricter guard + typed fallback (${passPct}% pass)`;
      })
      .join('\n\n')
    : null;

  const mockTestOutput = hasMockTaskData
    ? [
      `mock suite for ${selected ?? 'candidate'}`,
      ...perTask.map(([taskName, stats]) => {
        const passCount = stats.trials.filter(Boolean).length;
        const total = stats.trials.length;
        const status = passCount === total ? 'PASS' : passCount === 0 ? 'FAIL' : 'FLAKY';
        return `${status}  ${taskName}  (${passCount}/${total}, ${Math.round(stats.pass_rate * 100)}%)`;
      }),
      '',
      `summary: ${perTask.reduce((acc, [, stats]) => acc + stats.trials.filter(Boolean).length, 0)}/${perTask.reduce((acc, [, stats]) => acc + stats.trials.length, 0)} checks passed`,
    ].join('\n')
    : null;

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
        {contextTab === 'diff' && !diff && mockDiffPreview && (
          <div className="space-y-3">
            <div className="text-[10px] uppercase tracking-wide text-cyan">Mock task patch preview</div>
            <pre className="text-xs leading-5 text-text-hi whitespace-pre-wrap">{mockDiffPreview}</pre>
          </div>
        )}
        {contextTab === 'diff' && !diff && !mockDiffPreview && (
          <div className="text-text-mid text-xs">
            {selected ? `No diff available for ${selected}` : 'No candidate selected yet.'}
          </div>
        )}

        {contextTab === 'test' && testOut && <TestOutput output={testOut} />}
        {contextTab === 'test' && !testOut && mockTestOutput && <TestOutput output={mockTestOutput} />}
        {contextTab === 'test' && !testOut && !mockTestOutput && (
          <div className="text-text-mid text-xs">
            {selected ? `No test output available for ${selected}` : 'No candidate selected yet.'}
          </div>
        )}

        {contextTab === 'memory' && <MemoryPanel />}
      </div>
    </div>
  );
}
