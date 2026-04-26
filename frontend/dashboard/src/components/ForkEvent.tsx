import type { ForkEvent as ForkEventType } from '@/lib/types';

export function ForkEventCard({ fork }: { fork: ForkEventType }) {
  return (
    <div className="rounded bg-purple-bg border-l-[3px] border-purple p-5 mb-5">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-purple text-xs font-semibold">{'⑂'} FORK CREATED</span>
        <span className="text-text-ghost text-[10px]">{fork.timestamp}</span>
      </div>
      <div className="text-text-mid text-xs leading-relaxed">
        <div>From: <span className="text-text-hi">{fork.parentCandidate}</span> <span className="text-text-ghost">(checkpoint {fork.checkpointId})</span></div>
        <div>Prior: <span className="text-text-hi">{fork.prior}</span></div>
      </div>
    </div>
  );
}
