import type { ForkEvent as ForkEventType } from "@/lib/types";
import { IconGitBranch } from "./ui/icons";

export function ForkEventCard({ fork }: { fork: ForkEventType }) {
  return (
    <div className="relative glass-inset rounded-[var(--radius-card)] p-4 mb-3 overflow-hidden">
      <span aria-hidden="true" className="absolute left-0 top-0 bottom-0 w-0.5 bg-iris/60" />
      <div className="flex items-center gap-2 mb-2">
        <span className="inline-flex items-center gap-1.5 text-iris font-mono text-[10px] font-medium uppercase tracking-[0.1em]">
          <IconGitBranch size={12} />
          Fork created
        </span>
        <span className="text-ink-ghost font-mono text-[10px]">{fork.timestamp}</span>
        <span className="ml-auto font-mono text-[10px] text-ink-ghost truncate max-w-[16ch]" title={fork.branchId}>
          {fork.branchId}
        </span>
      </div>
      <dl className="grid grid-cols-[3.5rem_1fr] gap-x-3 gap-y-1 font-mono text-[11px] leading-[1.6]">
        <dt className="text-ink-ghost uppercase text-[10px] pt-px">From</dt>
        <dd className="text-ink truncate">
          {fork.parentCandidate}
          <span className="text-ink-ghost"> @ {fork.checkpointId}</span>
        </dd>
        <dt className="text-ink-ghost uppercase text-[10px] pt-px">Prior</dt>
        <dd className="text-ink-mid">{fork.prior}</dd>
        <dt className="text-ink-ghost uppercase text-[10px] pt-px">Why</dt>
        <dd className="text-ink-mid">{fork.rationale}</dd>
      </dl>
    </div>
  );
}
