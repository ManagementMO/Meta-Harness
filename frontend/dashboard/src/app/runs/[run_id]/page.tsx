'use client';

import { useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { DashboardProvider, useDashboardDispatch } from '@/lib/state';
import { startSSE, startMockSSE } from '@/lib/sse';
import { isBackendAvailable, getRunDetail, toRunInfo, toTreeNodes } from '@/lib/api';
import { TopBar } from '@/components/TopBar';
import { TrajectoryTree } from '@/components/TrajectoryTree';
import { DecisionLog } from '@/components/DecisionLog';
import { ContextPanel } from '@/components/ContextPanel';
import { StatusBar } from '@/components/StatusBar';

function DashboardShell() {
  const params = useParams<{ run_id: string }>();
  const runId = params.run_id;
  const dispatch = useDashboardDispatch();

  const connect = useCallback(async () => {
    const live = await isBackendAvailable();

    if (live) {
      try {
        const detail = await getRunDetail(runId);
        dispatch({ type: 'SET_RUN', payload: toRunInfo(detail) });
        for (const node of toTreeNodes(detail.summary_rows ?? [])) {
          dispatch({ type: 'ADD_TREE_NODE', payload: node });
        }
      } catch {
        // Run may not exist yet — SSE will populate as events arrive
      }
      return startSSE(runId, dispatch);
    }

    return startMockSSE(dispatch, 3);
  }, [runId, dispatch]);

  useEffect(() => {
    let cleanup: (() => void) | undefined;
    connect().then(fn => { cleanup = fn; });
    return () => cleanup?.();
  }, [connect]);

  return (
    <div className="h-full flex flex-col bg-panel overflow-hidden">
      <TopBar />
      <div className="flex-1 flex gap-4 p-4 min-h-0 w-full">
        <div className="w-[220px] shrink-0 flex flex-col min-h-0 min-w-0">
          <TrajectoryTree />
        </div>
        <div className="flex-[4] flex flex-col min-h-0 min-w-0">
          <DecisionLog />
        </div>
        <div className="flex-[3] flex flex-col min-h-0 min-w-0">
          <ContextPanel />
        </div>
      </div>
      <StatusBar />
    </div>
  );
}

export default function RunPage() {
  return (
    <DashboardProvider>
      <DashboardShell />
    </DashboardProvider>
  );
}
