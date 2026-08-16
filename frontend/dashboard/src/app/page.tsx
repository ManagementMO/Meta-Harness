"use client";

import { useState, useEffect } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { useRouter } from "next/navigation";
import { createRun, listRuns, isBackendAvailable, type RunListItem } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { StatusPill } from "@/components/ui/StatusPill";
import { Badge } from "@/components/ui/Badge";
import { IconArrowRight, IconPlay } from "@/components/ui/icons";
import { cn } from "@/lib/cn";

type PresetSuite = {
  id: string;
  label: string;
  description: string;
  payload: {
    proposer: "mock" | "claude";
    mock_bench: boolean;
    budget: number;
    trials: number;
    workers: number;
    fresh: boolean;
  };
};

const PRESET_SUITES: PresetSuite[] = [
  {
    id: "quick-smoke",
    label: "Quick smoke",
    description: "1 iteration, 1 trial — confirms wiring fast",
    payload: { proposer: "mock", mock_bench: true, budget: 1, trials: 1, workers: 1, fresh: true },
  },
  {
    id: "balanced",
    label: "Balanced",
    description: "3 iterations, 2 trials — realistic local signal",
    payload: { proposer: "mock", mock_bench: true, budget: 3, trials: 2, workers: 2, fresh: true },
  },
  {
    id: "stress",
    label: "Stress",
    description: "5 iterations, 5 trials — heavier event volume",
    payload: { proposer: "mock", mock_bench: true, budget: 5, trials: 5, workers: 3, fresh: true },
  },
];

const reveal = {
  hidden: { opacity: 0, transform: "translateY(10px)" },
  show: { opacity: 1, transform: "translateY(0px)" },
};

function runStatusTone(status: string): "moss" | "ember" | "sand" | "neutral" {
  const s = status.toLowerCase();
  if (s === "completed") return "moss";
  if (s === "failed" || s === "error") return "ember";
  if (s === "running") return "sand";
  return "neutral";
}

export default function Home() {
  const router = useRouter();
  const reduced = useReducedMotion();
  const [entering, setEntering] = useState(false);
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [live, setLive] = useState<boolean | null>(null);
  const [launchingPreset, setLaunchingPreset] = useState<string | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [selectedPresetId, setSelectedPresetId] = useState<string>(
    PRESET_SUITES[1]?.id ?? PRESET_SUITES[0].id,
  );
  const [mockModeEnabled, setMockModeEnabled] = useState(true);
  const [proposerMode, setProposerMode] = useState<"mock" | "claude">("mock");

  useEffect(() => {
    isBackendAvailable().then((ok) => {
      setLive(ok);
      if (ok) listRuns().then(setRuns).catch(() => setRuns([]));
    });
  }, []);

  const handleEnter = async () => {
    if (entering) return;
    setEntering(true);
    let target = live !== false && runs[0] ? `/runs/${runs[0].run_id}` : "/runs/demo-2026-04-25";
    if (live === null) {
      const ok = await isBackendAvailable();
      if (ok) {
        const latest = await listRuns().catch(() => []);
        target = latest[0] ? `/runs/${latest[0].run_id}` : target;
      }
    }
    setTimeout(() => router.push(target), reduced ? 0 : 350);
  };

  const handleLaunchPreset = async () => {
    const preset = PRESET_SUITES.find((item) => item.id === selectedPresetId);
    if (!preset || launchingPreset) return;
    setLaunchError(null);
    setLaunchingPreset(preset.id);
    try {
      const run = await createRun({
        run_name: `preset-${preset.id}-${Date.now()}`,
        ...preset.payload,
        proposer: proposerMode,
        mock_bench: mockModeEnabled,
      });
      router.push(`/runs/${run.run_id}`);
    } catch (error) {
      setLaunchError(error instanceof Error ? error.message : "failed to launch preset");
    } finally {
      setLaunchingPreset(null);
    }
  };

  const selectedPreset = PRESET_SUITES.find((p) => p.id === selectedPresetId);

  return (
    <div className="relative h-full w-full overflow-y-auto">
      <motion.div
        className="min-h-full flex flex-col items-center justify-center px-6 py-12"
        initial={reduced ? false : "hidden"}
        animate="show"
        transition={{ staggerChildren: 0.07 }}
      >
        {/* Brand lockup */}
        <motion.p
          variants={reveal}
          transition={{ duration: 0.35, ease: [0.32, 0.72, 0, 1] }}
          className="font-mono text-[10px] uppercase tracking-[0.3em] text-ink-low mb-4"
        >
          Autonomous harness evolution
        </motion.p>
        <motion.h1
          variants={reveal}
          transition={{ duration: 0.35, ease: [0.32, 0.72, 0, 1] }}
          className="text-[clamp(2.2rem,5vw,3.4rem)] leading-none font-semibold tracking-[0.14em] text-frost-bright select-none"
        >
          META-HARNESS
        </motion.h1>
        <motion.p
          variants={reveal}
          transition={{ duration: 0.35, ease: [0.32, 0.72, 0, 1] }}
          className="mt-4 max-w-[52ch] text-center text-body text-ink-mid"
        >
          An outer loop proposes harness candidates, benchmarks them on frozen tasks,
          and advances the Pareto frontier. Watch runs live, or replay the demo fixture.
        </motion.p>

        {/* Primary action */}
        <motion.div
          variants={reveal}
          transition={{ duration: 0.35, ease: [0.32, 0.72, 0, 1] }}
          className="mt-8 flex flex-col items-center gap-3"
        >
          <Button variant="primary" size="md" onClick={handleEnter} className="px-6 light-sweep">
            {live === false ? "Enter demo replay" : "Open latest run"}
            <IconArrowRight size={13} />
          </Button>
          <div className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-[0.12em]">
            <a href="/auth/login" className="text-ink-mid hover:text-frost-bright transition-colors duration-150">
              Login
            </a>
            <span aria-hidden="true" className="text-ink-ghost">/</span>
            <a href="/auth/logout" className="text-ink-low hover:text-frost-bright transition-colors duration-150">
              Logout
            </a>
          </div>
        </motion.div>

        {/* Launch console */}
        <motion.section
          variants={reveal}
          transition={{ duration: 0.35, ease: [0.32, 0.72, 0, 1] }}
          className="mt-10 w-full max-w-[36rem] glass-panel rounded-[var(--radius-panel)] overflow-hidden"
          aria-label="Launch console"
        >
          <div className="panel-sheen flex items-center gap-3 h-10 px-4 border-b border-white/6">
            <h2 className="text-label uppercase text-ink-mid">Launch console</h2>
            <span className="ml-auto">
              {live === null ? (
                <span className="font-mono text-[10px] text-ink-ghost">probing backend…</span>
              ) : (
                <StatusPill state={live ? "live" : "idle"} label={live ? "Backend online" : "Backend offline"} />
              )}
            </span>
          </div>

          <div className="p-4 flex flex-col gap-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <span className="text-label uppercase text-ink-low">Proposer</span>
                <SegmentedControl
                  ariaLabel="Proposer"
                  options={[
                    { value: "mock", label: "Mock" },
                    { value: "claude", label: "Claude" },
                  ]}
                  value={proposerMode}
                  onChange={setProposerMode}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="text-label uppercase text-ink-low">Benchmark</span>
                <SegmentedControl
                  ariaLabel="Benchmark mode"
                  options={[
                    { value: "mock", label: "Mock (fast)" },
                    { value: "real", label: "Real" },
                  ]}
                  value={mockModeEnabled ? "mock" : "real"}
                  onChange={(v) => setMockModeEnabled(v === "mock")}
                />
              </div>
            </div>

            <div role="radiogroup" aria-label="Preset suite" className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {PRESET_SUITES.map((preset) => {
                const active = selectedPresetId === preset.id;
                return (
                  <button
                    key={preset.id}
                    role="radio"
                    aria-checked={active}
                    onClick={() => setSelectedPresetId(preset.id)}
                    className={cn(
                      "light-sweep text-left rounded-[var(--radius-card)] border px-3 py-2.5 cursor-pointer",
                      "transition-[border-color,background-color] duration-150 ease-[var(--ease-glass)]",
                      active
                        ? "border-frost/45 bg-white/[0.05] specular-top"
                        : "border-white/7 bg-white/[0.02] hover:border-white/14",
                    )}
                  >
                    <div className={cn("font-mono text-[11px] uppercase tracking-[0.1em]", active ? "text-frost-bright" : "text-ink-mid")}>
                      {preset.label}
                    </div>
                    <div className="mt-1 text-[11px] leading-[1.5] text-ink-low">{preset.description}</div>
                  </button>
                );
              })}
            </div>

            <div className="flex items-center justify-between gap-3 pt-1 border-t border-white/5">
              <p className="font-mono text-[10px] text-ink-low truncate">
                {selectedPreset?.label ?? "None"} · {proposerMode} proposer · {mockModeEnabled ? "mock bench" : "real bench"}
              </p>
              <Button
                variant="primary"
                size="md"
                onClick={() => void handleLaunchPreset()}
                disabled={launchingPreset !== null}
                className="shrink-0"
              >
                <IconPlay size={11} />
                {launchingPreset ? "Launching…" : "Run selected suite"}
              </Button>
            </div>
            {launchError && (
              <p className="font-mono text-[10.5px] text-ember" role="alert">
                {launchError}
              </p>
            )}
          </div>
        </motion.section>

        {/* Recent runs */}
        {live && runs.length > 0 && (
          <motion.section
            variants={reveal}
            transition={{ duration: 0.35, ease: [0.32, 0.72, 0, 1] }}
            className="mt-4 w-full max-w-[36rem] glass-panel rounded-[var(--radius-panel)] overflow-hidden"
            aria-label="Recent runs"
          >
            <div className="panel-sheen flex items-center h-10 px-4 border-b border-white/6">
              <h2 className="text-label uppercase text-ink-mid">Recent runs</h2>
              <span className="ml-auto font-mono text-[10px] tabular-nums text-ink-ghost">{runs.length}</span>
            </div>
            <ul className="max-h-56 overflow-y-auto py-1">
              {runs.slice(0, 8).map((run) => (
                <li key={run.run_id}>
                  <button
                    onClick={() => router.push(`/runs/${run.run_id}`)}
                    className="w-full flex items-center gap-3 px-4 py-2 text-left cursor-pointer hover:bg-white/[0.03] transition-colors duration-150"
                  >
                    <span className="font-mono text-[11px] text-ink truncate flex-1">{run.run_id}</span>
                    {run.synthetic && <Badge label="SYN" tone="sand" />}
                    <span className="font-mono text-[10px] tabular-nums text-ink-low shrink-0">
                      iter {run.iteration ?? run.current_iteration ?? 0}
                    </span>
                    <span className="font-mono text-[10px] tabular-nums text-ink-mid w-10 text-right shrink-0">
                      {run.best_score !== null ? run.best_score.toFixed(2) : "—"}
                    </span>
                    <Badge label={run.status} tone={runStatusTone(run.status)} />
                  </button>
                </li>
              ))}
            </ul>
          </motion.section>
        )}

        {/* System readout */}
        <motion.p
          variants={reveal}
          transition={{ duration: 0.35, ease: [0.32, 0.72, 0, 1] }}
          className="mt-8 font-mono text-[10px] tracking-[0.1em] text-ink-ghost"
        >
          SYS {live === false ? "offline — demo available" : "online"} · v0.1.0 · relay-hackathon
        </motion.p>
      </motion.div>

      {/* exit veil */}
      <motion.div
        className="pointer-events-none fixed inset-0 bg-void z-50"
        initial={{ opacity: 0 }}
        animate={{ opacity: entering ? 1 : 0 }}
        transition={{ duration: reduced ? 0 : 0.35 }}
      />
    </div>
  );
}
