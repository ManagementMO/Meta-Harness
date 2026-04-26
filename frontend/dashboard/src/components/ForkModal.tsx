'use client';
import { useState } from 'react';
import { useDashboardDispatch } from '@/lib/state';

type ForkModalProps = {
  candidateName: string;
  checkpointId: string;
  onClose: () => void;
};

export function ForkModal({ candidateName, checkpointId, onClose }: ForkModalProps) {
  const dispatch = useDashboardDispatch();
  const [prior, setPrior] = useState('');

  const handleCreate = () => {
    if (!prior.trim()) return;
    dispatch({
      type: 'ADD_FORK_EVENT',
      payload: {
        timestamp: new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        parentCandidate: candidateName,
        checkpointId,
        prior: prior.trim(),
        branchId: `fork.${Math.random().toString(36).slice(2, 10)}`,
        rationale: 'Manual fork from dashboard',
      },
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative w-[420px] bg-header border border-border rounded p-6"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <span className="text-sm font-semibold text-text-hi">⑂ Create Fork</span>
          <button onClick={onClose} className="text-text-mid hover:text-text-hi text-sm">✕</button>
        </div>

        <div className="mb-4">
          <label className="text-[9px] text-text-mid uppercase tracking-wide font-semibold">Fork from</label>
          <div className="mt-1.5 px-3 py-2 bg-panel rounded border border-border text-xs text-text-hi">
            {candidateName}
            <span className="text-text-ghost ml-2">checkpoint {checkpointId}</span>
          </div>
        </div>

        <div className="mb-5">
          <label className="text-[9px] text-text-mid uppercase tracking-wide font-semibold">New prior / hypothesis</label>
          <textarea
            value={prior}
            onChange={e => setPrior(e.target.value)}
            placeholder="e.g. Explore few-shot examples instead of tool rewrites"
            className="mt-1.5 w-full px-3 py-2.5 bg-panel rounded border border-border text-xs text-text-hi placeholder:text-text-ghost resize-none h-24 focus:outline-none focus:border-cyan"
          />
        </div>

        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-[10px] font-semibold uppercase tracking-wide text-text-mid hover:text-text-hi rounded bg-hover"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={!prior.trim()}
            className="px-4 py-2 text-[10px] font-semibold uppercase tracking-wide rounded bg-purple text-white disabled:opacity-30 disabled:cursor-not-allowed hover:opacity-90"
          >
            Create Fork
          </button>
        </div>
      </div>
    </div>
  );
}
