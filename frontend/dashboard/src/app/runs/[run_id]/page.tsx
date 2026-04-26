'use client';

import { useEffect, useCallback, useRef } from 'react';
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
  const latestDetailRef = useRef<Awaited<ReturnType<typeof getRunDetail>> | null>(null);
  const replayTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const clearReplayTimers = useCallback(() => {
    for (const timer of replayTimersRef.current) clearTimeout(timer);
    replayTimersRef.current = [];
  }, []);

  const replayRunProgression = useCallback(() => {
    const detail = latestDetailRef.current;
    if (!detail) return;
    clearReplayTimers();

    const schedule = (delayMs: number, action: () => void) => {
      const timer = setTimeout(action, delayMs);
      replayTimersRef.current.push(timer);
    };

    const runInfo = toRunInfo(detail);
    const nodes = toTreeNodesFromRunDetail(detail).sort((a, b) => a.iteration - b.iteration);

    dispatch({ type: 'RESET' });
    dispatch({ type: 'SET_MODE', payload: runInfo.isMock ? 'mock' : 'live' });
    dispatch({ type: 'SET_RUN', payload: { ...runInfo, iteration: 0 } });
    dispatch({ type: 'SET_SSE_CONNECTED', payload: true });

    nodes.forEach((node, idx) => {
      schedule(900 + idx * 2200, () => {
        dispatch({ type: 'ADD_TREE_NODE', payload: node });
        if (node.checkpointId) {
          dispatch({
            type: 'SET_CHECKPOINT_ID',
            payload: { candidate: node.candidate, checkpointId: node.checkpointId },
          });
        }
        dispatch({
          type: 'ADD_ITERATION',
          payload: {
            iteration: node.iteration,
            candidateName: node.candidate,
            status: node.status === 'best' ? 'accepted' : node.status,
            phases: { propose: true, validate: true, benchmark: true, frontier: true },
            hypothesis: node.hypothesis ?? `candidate ${node.candidate}`,
            isForkBranch: node.isForkBranch,
            threadId: node.threadId,
          },
        });
        dispatch({
          type: 'ADD_LOG_ENTRY',
          payload: {
            id: `replay-${node.candidate}-${node.iteration}`,
            timestamp: new Date().toISOString(),
            tag: 'score',
            text: `iter ${node.iteration} ${node.candidate} accuracy ${(node.scores.accuracy * 100).toFixed(0)}%`,
            candidateName: node.candidate,
          },
        });
      });
    });
  }, [clearReplayTimers, dispatch]);

  const connect = useCallback(async () => {
    const live = await isBackendAvailable();
    dispatch({ type: 'SET_MODE', payload: live ? 'live' : 'mock' });

    if (live) {
      try {
        const detail = await getRunDetail(runId);
        latestDetailRef.current = detail;
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
      return startMockSSE(dispatch);
    }

    dispatch({ type: 'SET_SSE_CONNECTED', payload: false });
    return undefined;
  }, [runId, dispatch]);

  useEffect(() => {
    let cleanup: (() => void) | undefined;
    connect().then(fn => { cleanup = fn; });
    return () => {
      cleanup?.();
      clearReplayTimers();
    };
  }, [clearReplayTimers, connect]);

  return (
    <div className="h-full flex flex-col bg-panel overflow-hidden">
      <TopBar onReplay={replayRunProgression} />
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
