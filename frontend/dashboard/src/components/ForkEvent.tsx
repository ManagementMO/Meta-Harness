import type { ForkEvent as ForkEventType } from '@/lib/types';

export function ForkEventCard({ fork }: { fork: ForkEventType }) {
  return (
    <div className="rounded bg-purple-bg border border-purple/50 border-l-4 border-l-purple p-5 mb-5 shadow-[0_0_0_1px_rgba(136,120,168,0.15)]">
      <div className="flex items-center gap-2 mb-2">
        <span className="inline-flex items-center gap-1 text-purple text-xs font-semibold uppercase tracking-wide">
          <span className="text-[13px]">{'⑂'}</span>
          Fork Created
        </span>
        <span className="text-text-ghost text-[10px]">{fork.timestamp}</span>
      </div>
      <div className="text-text-mid text-xs leading-relaxed">
        <div>From: <span className="text-text-hi">{fork.parentCandidate}</span> <span className="text-text-ghost">(checkpoint {fork.checkpointId})</span></div>
        <div>Prior: <span className="text-text-hi">{fork.prior}</span></div>
        <div className="mt-2">
          <span className="text-purple text-[10px] font-semibold uppercase tracking-wide">Why this fork:</span>{' '}
          <span className="text-text-hi">{fork.rationale}</span>
        </div>
      </div>
    </div>
  );
}
