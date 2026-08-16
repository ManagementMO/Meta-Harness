'use client';

import { useEffect, useCallback, useRef } from 'react';
import { useParams } from 'next/navigation';
import { DashboardProvider, useDashboardDispatch } from '@/lib/state';
import { startSSE, startMockSSE } from '@/lib/sse';
import { fetchCheckpointCandidateMap, getRunDetail, isBackendAvailable, toRunInfo, toTreeNodesFromRunDetail } from '@/lib/api';
import { TopBar } from '@/components/TopBar';
import { OuterSpine } from '@/components/OuterSpine';
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
    dispatch({ type: 'SET_MODE', payload: 'live' });
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
    <div className="h-full flex flex-col overflow-hidden">
      <TopBar onReplay={replayRunProgression} />
      <OuterSpine />
      <main className="flex-1 grid gap-3 p-3 min-h-0 min-w-0 grid-cols-[15rem_minmax(0,1fr)_minmax(0,21.5rem)] xl:grid-cols-[17.5rem_minmax(0,1fr)_minmax(0,26rem)] 2xl:grid-cols-[19rem_minmax(0,1fr)_minmax(0,30rem)]">
        <TrajectoryTree />
        <DecisionLog />
        <ContextPanel />
      </main>
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
