"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { motion, useReducedMotion } from "framer-motion";
import { useDashboardDispatch } from "@/lib/state";
import { forkRun } from "@/lib/api";
import { Button } from "./ui/Button";
import { IconGitBranch, IconX } from "./ui/icons";

type ForkModalProps = {
  candidateName: string;
  checkpointId: string;
  parentThreadId?: string;
  onClose: () => void;
};

export function ForkModal({ candidateName, checkpointId, parentThreadId, onClose }: ForkModalProps) {
  const params = useParams<{ run_id: string }>();
  const dispatch = useDashboardDispatch();
  const [prior, setPrior] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    textareaRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleCreate = async () => {
    if (!prior.trim() || submitting) return;
    setSubmitting(true);

    const fallbackBranchId = `fork.${Math.random().toString(36).slice(2, 10)}`;
    const timestamp = new Date().toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });

    let branchId = fallbackBranchId;
    try {
      const result = await forkRun(params.run_id, {
        parent_checkpoint_id: checkpointId,
        parent_thread_id: parentThreadId,
        // Pin fork proposer lineage to the selected node so the new
        // candidate branches from the exact error/source point in the tree.
        mods: { proposer_prior: prior.trim(), best_candidate: candidateName },
        name: fallbackBranchId,
      });
      branchId = result.branch_id ?? fallbackBranchId;
      dispatch({
        type: "ADD_LOG_ENTRY",
        payload: {
          id: `fork-started-${Date.now()}`,
          timestamp,
          tag: "fork",
          text: `fork ${branchId} launched from ${parentThreadId ?? params.run_id}@${checkpointId.slice(0, 8)}…`,
          candidateName,
          threadId: result.thread_id,
        },
      });
    } catch {
      dispatch({
        type: "ADD_LOG_ENTRY",
        payload: {
          id: `fork-failed-${Date.now()}`,
          timestamp,
          tag: "fork",
          text: `fork request failed for ${parentThreadId ?? params.run_id}@${checkpointId.slice(0, 8)}; recording local fork intent`,
          candidateName,
        },
      });
    }

    dispatch({
      type: "ADD_FORK_EVENT",
      payload: {
        timestamp,
        parentCandidate: candidateName,
        checkpointId,
        prior: prior.trim(),
        branchId,
        rationale: "Manual fork rerun from dashboard",
      },
    });

    setSubmitting(false);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="fork-modal-title"
      onClick={onClose}
    >
      <motion.div
        className="absolute inset-0 bg-black/55 backdrop-blur-[6px]"
        initial={reduced ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.18 }}
      />
      <motion.div
        className="relative w-[440px] max-w-full glass-raised rounded-[var(--radius-panel)] overflow-hidden"
        initial={reduced ? false : { opacity: 0, scale: 0.96, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 460, damping: 34 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="panel-sheen flex items-center gap-2.5 h-11 px-4 border-b border-white/6">
          <IconGitBranch size={14} className="text-iris" />
          <h2 id="fork-modal-title" className="text-title text-ink">
            Create fork
          </h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="ml-auto flex items-center justify-center w-6 h-6 rounded-[6px] text-ink-low hover:text-ink hover:bg-white/6 transition-colors duration-150 cursor-pointer"
          >
            <IconX size={12} />
          </button>
        </div>

        <div className="p-4 flex flex-col gap-4">
          <div>
            <label className="text-label uppercase text-ink-low">Fork from</label>
            <div className="mt-1.5 well rounded-[var(--radius-control)] px-3 py-2 font-mono text-[11.5px] text-ink flex items-baseline gap-2 min-w-0">
              <span className="truncate">{candidateName}</span>
              <span className="text-ink-ghost text-[10px] truncate shrink-0">@ {checkpointId}</span>
            </div>
          </div>

          <div>
            <label htmlFor="fork-prior" className="text-label uppercase text-ink-low">
              New prior / hypothesis
            </label>
            <textarea
              id="fork-prior"
              ref={textareaRef}
              value={prior}
              onChange={(e) => setPrior(e.target.value)}
              placeholder="e.g. Explore few-shot examples instead of tool rewrites"
              className="mt-1.5 w-full well rounded-[var(--radius-control)] px-3 py-2.5 font-mono text-[11.5px] leading-[1.6] text-ink placeholder:text-ink-ghost resize-none h-24 focus:outline-none focus-visible:outline-2 focus-visible:outline-frost"
            />
          </div>

          <div className="flex justify-end items-center gap-2">
            <Button variant="quiet" size="md" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" size="md" onClick={handleCreate} disabled={!prior.trim() || submitting}>
              <IconGitBranch size={12} />
              {submitting ? "Forking…" : "Create fork"}
            </Button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
