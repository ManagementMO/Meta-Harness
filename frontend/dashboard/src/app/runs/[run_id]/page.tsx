'use client';

import { useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { DashboardProvider, useDashboardDispatch } from '@/lib/state';
import { startSSE, startMockSSE } from '@/lib/sse';
import { fetchCheckpointCandidateMap, getRunDetail, isBackendAvailable, toRunInfo, toTreeNodesFromRunDetail } from '@/lib/api';
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
    dispatch({ type: 'SET_MODE', payload: live ? 'live' : 'mock' });

    if (live) {
      try {
        const detail = await getRunDetail(runId);
        const runInfo = toRunInfo(detail);
        dispatch({ type: 'SET_RUN', payload: runInfo });
        if (runInfo.isMock) dispatch({ type: 'SET_MODE', payload: 'mock' });
        for (const node of toTreeNodesFromRunDetail(detail)) {
          dispatch({ type: 'ADD_TREE_NODE', payload: node });
        }
        const checkpoints = await fetchCheckpointCandidateMap(runId);
        for (const [candidate, checkpointId] of checkpoints) {
          dispatch({ type: 'SET_CHECKPOINT_ID', payload: { candidate, checkpointId } });
        }
      } catch {
        dispatch({ type: 'SET_SSE_CONNECTED', payload: false });
        return undefined;
      }
      return startSSE(runId, dispatch);
    }

    if (runId === 'demo-2026-04-25') {
      return startMockSSE(dispatch, 3);
    }

    dispatch({ type: 'SET_SSE_CONNECTED', payload: false });
    return undefined;
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
