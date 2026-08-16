"use client";

import { memo, useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { useDashboard, useDashboardDispatch } from "@/lib/state";
import { FilterBar } from "./ui/FilterBar";
import { Badge } from "./ui/Badge";
import { PhasePipeline } from "./ui/PhasePipeline";
import { GlassPanel, PanelHeader, PanelTitle } from "./ui/GlassPanel";
import { ForkEventCard } from "./ForkEvent";
import { IconArrowDown, IconCaretDown, IconCaretRight, IconListChecks, IconMagnifyingGlass } from "./ui/icons";
import { cn } from "@/lib/cn";
import type { IterationChapter, LogEntry, LogFilter, LogTag } from "@/lib/types";

const TAG_TONES: Record<LogTag, string> = {
  orient: "text-ink-low border-white/8",
  plan: "text-ink-mid border-white/10",
  "tool/read": "text-ink-mid border-white/10",
  "tool/patch": "text-ink-mid border-white/10",
  act: "text-ink border-white/12",
  verify: "text-sand border-sand/25",
  score: "text-moss border-moss/25",
  fail: "text-ember border-ember/28",
  fork: "text-iris border-iris/28",
  memory: "text-iris border-iris/25",
};

const spring = { type: "spring", stiffness: 420, damping: 32 } as const;

const LogEntryRow = memo(function LogEntryRow({
  entry,
  selected,
  expanded,
  onSelect,
}: {
  entry: LogEntry;
  selected: boolean;
  expanded: boolean;
  onSelect: (entry: LogEntry) => void;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      initial={reduced ? false : { opacity: 0, transform: "translateY(8px)" }}
      animate={{ opacity: 1, transform: "translateY(0px)" }}
      transition={spring}
    >
      <div
        className={cn(
          "group relative flex items-start gap-2 px-2 py-[3px] -mx-2 rounded-[6px] cursor-pointer",
          "transition-colors duration-150 ease-[var(--ease-glass)]",
          selected ? "bg-frost/6" : "hover:bg-white/[0.03]",
        )}
        onClick={() => onSelect(entry)}
      >
        {selected && (
          <span aria-hidden="true" className="absolute left-0 top-1 bottom-1 w-0.5 rounded-full bg-frost/70" />
        )}
        <span className="font-mono text-[10px] text-ink-low w-14 shrink-0 pt-0.5 tabular-nums">
          {entry.timestamp.includes("T") ? entry.timestamp.slice(11, 19) : entry.timestamp}
        </span>
        <span
          className={cn(
            "inline-flex items-center h-4 px-1 mt-px rounded-[4px] border bg-white/[0.02] font-mono text-[9px] uppercase tracking-[0.06em] shrink-0 leading-none",
            TAG_TONES[entry.tag],
          )}
        >
          {entry.tag}
        </span>
        <span className="font-mono text-[11.5px] leading-[1.55] text-ink-mid group-hover:text-ink transition-colors duration-150 break-words min-w-0">
          {entry.text}
        </span>
        {entry.expandable && (
          <span className="text-ink-ghost ml-auto shrink-0 pt-0.5">
            {expanded ? <IconCaretDown size={10} /> : <IconCaretRight size={10} />}
          </span>
        )}
      </div>
      {entry.expandable && expanded && entry.expandedContent && (
        <pre className="mt-1 mb-1.5 ml-16 p-2.5 well rounded-[8px] font-mono text-[10px] leading-[1.6] text-ink-low overflow-x-auto">
          {entry.expandedContent}
        </pre>
      )}
    </motion.div>
  );
});

const ChapterBlock = memo(function ChapterBlock({
  chapter,
  entries,
  memoryNote,
  selectedLogLine,
  expandedLines,
  onSelectEntry,
}: {
  chapter: IterationChapter;
  entries: LogEntry[];
  memoryNote: string | null;
  selectedLogLine: string | null;
  expandedLines: Set<string>;
  onSelectEntry: (entry: LogEntry) => void;
}) {
  const reduced = useReducedMotion();
  const fork = chapter.isForkBranch;
  const scoreEntry = entries.find((e) => e.tag === "score");
  const sealed = chapter.status === "accepted" || chapter.status === "rejected" || chapter.status === "best";

  return (
    <motion.article
      initial={reduced ? false : { opacity: 0, transform: "translateY(10px)" }}
      animate={{ opacity: 1, transform: "translateY(0px)" }}
      transition={{ duration: 0.22, ease: [0.32, 0.72, 0, 1] }}
      className="mb-3"
    >
      <div className="relative glass-inset rounded-[var(--radius-card)] px-4 py-3 overflow-hidden">
        <span
          aria-hidden="true"
          className={cn(
            "absolute left-0 top-0 bottom-0 w-0.5",
            fork
              ? "bg-iris/60"
              : chapter.status === "accepted" || chapter.status === "best"
                ? "bg-moss/50"
                : chapter.status === "rejected"
                  ? "bg-ember/50"
                  : "bg-frost/40",
          )}
        />
        <div className="flex items-center gap-2 flex-wrap">
          <h3 className={cn("font-mono text-[11.5px] font-medium", fork ? "text-iris" : "text-ink")}>
            {`ITER ${chapter.iteration}${fork ? "'" : ""} — ${chapter.candidateName}`}
          </h3>
          {chapter.status === "accepted" && <Badge label="Accepted" tone="moss" />}
          {chapter.status === "best" && <Badge label="Best" tone="frost" />}
          {chapter.status === "rejected" && <Badge label="Rejected" tone="ember" />}
          {chapter.status === "running" && <Badge label="Running" tone="frost" />}
          {fork && <Badge label="Fork" tone="iris" />}
        </div>
        <div className="mt-2">
          <PhasePipeline phases={chapter.phases} running={chapter.status === "running"} />
        </div>
        {chapter.hypothesis && (
          <p className="mt-1.5 text-[12px] leading-[1.55] text-ink-mid">{chapter.hypothesis}</p>
        )}
        {memoryNote && (
          <p className="mt-1.5 font-mono text-[10px] tracking-[0.04em] text-ink-low">
            {memoryNote}
          </p>
        )}
      </div>

      {entries.length > 0 && (
        <div className="flex flex-col gap-px mt-2 pl-2">
          {entries.map((entry) => (
            <LogEntryRow
              key={entry.id}
              entry={entry}
              selected={selectedLogLine === entry.id}
              expanded={expandedLines.has(entry.id)}
              onSelect={onSelectEntry}
            />
          ))}
        </div>
      )}

      {sealed && scoreEntry && (
        <div
          className={cn(
            "mt-2 ml-2 flex items-center justify-between gap-3 px-3 py-1.5 rounded-[8px] border",
            chapter.status === "rejected"
              ? "border-ember/20 bg-ember/6"
              : "border-moss/20 bg-moss/6",
          )}
        >
          <span
            className={cn(
              "font-mono text-[10px] uppercase tracking-[0.1em]",
              chapter.status === "rejected" ? "text-ember" : "text-moss",
            )}
          >
            accuracy — {chapter.status}
          </span>
          <span className="font-mono text-[12px] tabular-nums text-ink flex items-baseline gap-1.5">
            {scoreEntry.text.match(/[\d.]+/)?.[0] ?? "—"}
            <span className={cn("text-[10px]", chapter.status === "rejected" ? "text-ember" : "text-moss")}>
              {scoreEntry.text.match(/[+-][\d.]+/)?.[0] ?? ""}
            </span>
          </span>
        </div>
      )}
    </motion.article>
  );
});

export function DecisionLog() {
  const { iterations, logEntries, forkEvents, filters, selectedLogLine, run } = useDashboard();
  const dispatch = useDashboardDispatch();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [expandedLines, setExpandedLines] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logEntries.length, iterations.length, autoScroll]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 50);
  };

  const filteredEntries = logEntries
    .filter((e) => {
      if (filters.activeFilter === "all") return true;
      if (filters.activeFilter === "tools") return e.tag.startsWith("tool/");
      if (filters.activeFilter === "verify") return e.tag === "verify";
      if (filters.activeFilter === "scores") return e.tag === "score";
      if (filters.activeFilter === "forks") return e.tag === "fork" || e.tag === "memory";
      return true;
    })
    .filter(
      (e) => !filters.searchQuery || e.text.toLowerCase().includes(filters.searchQuery.toLowerCase()),
    );

  const handleSelectEntry = (entry: LogEntry) => {
    dispatch({ type: "SELECT_LOG_LINE", payload: entry.id });
    if (entry.expandable) {
      setExpandedLines((prev) => {
        const next = new Set(prev);
        if (next.has(entry.id)) next.delete(entry.id);
        else next.add(entry.id);
        return next;
      });
    }
  };

  const memoryNoteFor = (chapter: IterationChapter): string | null => {
    if (chapter.iteration < 1) return null;
    return run?.mode === "autonomous"
      ? `global memory eligible: ${Math.min(chapter.iteration + 2, 5)} patterns`
      : "global memory disabled for research validity";
  };

  const filtersForBar: LogFilter[] = ["all", "tools", "verify", "scores", "forks"];
  const isEmpty = iterations.length === 0 && logEntries.length === 0 && forkEvents.length === 0;

  return (
    <GlassPanel className="relative">
      <PanelHeader>
        <PanelTitle icon={<IconListChecks size={13} />}>Decision Log</PanelTitle>
        <span className="ml-auto" />
        <div className="relative hidden xl:block">
          <IconMagnifyingGlass
            size={11}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-ink-ghost pointer-events-none"
          />
          <input
            type="search"
            value={filters.searchQuery}
            onChange={(e) => dispatch({ type: "SET_FILTER", payload: { searchQuery: e.target.value } })}
            placeholder="Filter entries"
            aria-label="Filter log entries"
            className="well h-6 w-36 rounded-[6px] pl-6 pr-2 font-mono text-[10px] text-ink placeholder:text-ink-ghost outline-none [&::-webkit-search-cancel-button]:appearance-none"
          />
        </div>
        <FilterBar
          filters={filtersForBar}
          active={filters.activeFilter}
          onSelect={(f) => dispatch({ type: "SET_FILTER", payload: { activeFilter: f } })}
        />
      </PanelHeader>

      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-4 py-4">
        {isEmpty && (
          <div className="glass-inset rounded-[var(--radius-card)] px-4 py-4">
            <div className="text-label uppercase text-ink-low">Awaiting first candidate</div>
            <p className="text-[12px] leading-[1.55] text-ink-mid mt-1.5">
              {run?.status === "running"
                ? "The proposer is warming up. Decision events stream in once iteration 1 begins."
                : "No streamed decision events yet for this run."}
            </p>
          </div>
        )}

        {forkEvents.length > 0 && (
          <div className="mb-2 flex items-baseline gap-2">
            <span className="text-label uppercase text-iris">Fork timeline</span>
            <span className="font-mono text-[10px] text-ink-ghost">branching decisions and rationale</span>
          </div>
        )}
        {forkEvents.map((fork, i) => (
          <ForkEventCard key={i} fork={fork} />
        ))}

        {iterations.map((chapter, idx) => (
          <ChapterBlock
            key={`${chapter.candidateName}-${chapter.iteration}-${chapter.threadId ?? "thread"}-${idx}`}
            chapter={chapter}
            entries={filteredEntries.filter((e) => e.candidateName === chapter.candidateName)}
            memoryNote={memoryNoteFor(chapter)}
            selectedLogLine={selectedLogLine}
            expandedLines={expandedLines}
            onSelectEntry={handleSelectEntry}
          />
        ))}
      </div>

      {!autoScroll && (
        <button
          onClick={() => {
            setAutoScroll(true);
            scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
          }}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 inline-flex items-center gap-1.5 h-7 px-3 glass-raised rounded-full font-mono text-[10px] uppercase tracking-[0.08em] text-ink-mid hover:text-ink transition-colors duration-150 cursor-pointer"
        >
          <IconArrowDown size={11} />
          Jump to latest
        </button>
      )}
    </GlassPanel>
  );
}
