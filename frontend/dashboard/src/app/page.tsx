'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useRouter } from 'next/navigation';
import { createRun, listRuns, isBackendAvailable, type RunListItem } from '@/lib/api';

const TITLE = 'META-HARNESS';
const SUBTITLE = 'autonomous agent evolution monitor';
const GRID_LINES_H = 12;
const GRID_LINES_V = 20;

type PresetSuite = {
  id: string;
  label: string;
  description: string;
  payload: {
    proposer: 'mock' | 'claude';
    mock_bench: boolean;
    budget: number;
    trials: number;
    workers: number;
    fresh: boolean;
  };
};

const PRESET_SUITES: PresetSuite[] = [
  {
    id: 'quick-smoke',
    label: 'Quick Smoke',
    description: '1 iter, 1 trial - confirms wiring fast',
    payload: { proposer: 'mock', mock_bench: true, budget: 1, trials: 1, workers: 1, fresh: true },
  },
  {
    id: 'balanced',
    label: 'Balanced',
    description: '3 iter, 2 trials - realistic local signal',
    payload: { proposer: 'mock', mock_bench: true, budget: 3, trials: 2, workers: 2, fresh: true },
  },
  {
    id: 'stress',
    label: 'Stress',
    description: '5 iter, 5 trials - heavier event volume',
    payload: { proposer: 'mock', mock_bench: true, budget: 5, trials: 5, workers: 3, fresh: true },
  },
];

function GridBackground() {
  return (
    <svg className="absolute inset-0 w-full h-full" xmlns="http://www.w3.org/2000/svg">
      {Array.from({ length: GRID_LINES_H }).map((_, i) => {
        const y = ((i + 1) / (GRID_LINES_H + 1)) * 100;
        return (
          <motion.line
            key={`h-${i}`}
            x1="0%"
            y1={`${y}%`}
            x2="100%"
            y2={`${y}%`}
            stroke="#22222e"
            strokeWidth={0.5}
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ duration: 1.8, delay: 0.05 * i, ease: 'easeOut' }}
          />
        );
      })}
      {Array.from({ length: GRID_LINES_V }).map((_, i) => {
        const x = ((i + 1) / (GRID_LINES_V + 1)) * 100;
        return (
          <motion.line
            key={`v-${i}`}
            x1={`${x}%`}
            y1="0%"
            x2={`${x}%`}
            y2="100%"
            stroke="#22222e"
            strokeWidth={0.5}
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ duration: 1.8, delay: 0.05 * i + 0.3, ease: 'easeOut' }}
          />
        );
      })}
    </svg>
  );
}

function TypingTitle({ onComplete }: { onComplete: () => void }) {
  const [charCount, setCharCount] = useState(0);
  const [showCursor, setShowCursor] = useState(true);

  const stableOnComplete = useCallback(() => onComplete(), [onComplete]);

  useEffect(() => {
    if (charCount < TITLE.length) {
      const timeout = setTimeout(() => setCharCount(c => c + 1), 90 + Math.random() * 60);
      return () => clearTimeout(timeout);
    } else {
      const timeout = setTimeout(stableOnComplete, 400);
      return () => clearTimeout(timeout);
    }
  }, [charCount, stableOnComplete]);

  useEffect(() => {
    const interval = setInterval(() => setShowCursor(c => !c), 530);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex items-center justify-center">
      <h1 className="text-[clamp(2rem,6vw,4.5rem)] font-bold tracking-[0.3em] text-text-hi">
        {TITLE.slice(0, charCount).split('').map((char, i) => (
          <motion.span
            key={i}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.15 }}
            style={{ display: 'inline-block' }}
          >
            {char === '-' ? '‐' : char}
          </motion.span>
        ))}
        <span
          className="inline-block w-[0.5ch] h-[1em] bg-cyan ml-1 align-middle"
          style={{ opacity: showCursor ? 1 : 0 }}
        />
      </h1>
    </div>
  );
}

function Scanline() {
  return (
    <motion.div
      className="absolute left-0 right-0 h-0.5 pointer-events-none"
      style={{
        background: 'linear-gradient(90deg, transparent, rgba(122,184,173,0.15), transparent)',
        boxShadow: '0 0 20px rgba(122,184,173,0.08)',
      }}
      initial={{ top: '-2px' }}
      animate={{ top: '100%' }}
      transition={{ duration: 3, repeat: Infinity, repeatDelay: 4, ease: 'linear' }}
    />
  );
}

function StatusReadout({ visible }: { visible: boolean }) {
  const lines = [
    { label: 'SYS', value: 'online', color: 'text-green' },
    { label: 'VER', value: 'v0.1.0', color: 'text-text-mid' },
    { label: 'ENV', value: 'relay-hackathon', color: 'text-amber' },
  ];

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          className="absolute bottom-8 left-8 flex flex-col gap-1"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.2 }}
        >
          {lines.map((line, i) => (
            <motion.div
              key={line.label}
              className="flex items-center gap-2 text-[10px]"
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3, delay: 0.3 + i * 0.15 }}
            >
              <span className="text-text-ghost">{line.label}</span>
              <span className="text-text-ghost">&mdash;</span>
              <span className={line.color}>{line.value}</span>
            </motion.div>
          ))}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export default function Home() {
  const router = useRouter();
  const [phase, setPhase] = useState<'typing' | 'ready'>('typing');
  const [entering, setEntering] = useState(false);
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [live, setLive] = useState<boolean | null>(null);
  const [launchingPreset, setLaunchingPreset] = useState<string | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [selectedPresetId, setSelectedPresetId] = useState<string>(PRESET_SUITES[1]?.id ?? PRESET_SUITES[0].id);
  const [mockModeEnabled, setMockModeEnabled] = useState(true);
  const [proposerMode, setProposerMode] = useState<'mock' | 'claude'>('mock');

  useEffect(() => {
    if (phase !== 'ready') return;
    isBackendAvailable().then(ok => {
      setLive(ok);
      if (ok) listRuns().then(setRuns).catch(() => setRuns([]));
    });
  }, [phase]);

  const handleEnter = async () => {
    if (entering) return;
    setEntering(true);
    let target = live !== false && runs[0] ? `/runs/${runs[0].run_id}` : '/runs/demo-2026-04-25';
    if (live === null) {
      const ok = await isBackendAvailable();
      if (ok) {
        const latest = await listRuns().catch(() => []);
        target = latest[0] ? `/runs/${latest[0].run_id}` : target;
      }
    }
    setTimeout(() => router.push(target), 600);
  };

  const handleLaunchPreset = async () => {
    const preset = PRESET_SUITES.find(item => item.id === selectedPresetId);
    if (!preset) return;
    if (launchingPreset) return;
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
      setLaunchError(error instanceof Error ? error.message : 'failed to launch preset');
    } finally {
      setLaunchingPreset(null);
    }
  };

  return (
    <div className="relative h-full w-full bg-void overflow-hidden flex items-center justify-center">
      <GridBackground />
      <Scanline />

      <div className="relative z-10 flex flex-col items-center gap-8">
        <TypingTitle onComplete={() => setPhase('ready')} />

        <AnimatePresence>
          {phase === 'ready' && (
            <motion.p
              className="text-text-mid text-[11px] tracking-[0.25em] uppercase"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.8 }}
            >
              {SUBTITLE}
            </motion.p>
          )}
        </AnimatePresence>

        <AnimatePresence>
          {phase === 'ready' && (
            <div className="mt-4 flex flex-col items-center gap-3">
              <motion.button
                onClick={handleEnter}
                className="px-8 py-3 border border-border-active rounded text-[11px] font-semibold tracking-[0.2em] uppercase text-cyan hover:bg-hover hover:border-cyan transition-colors cursor-pointer"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.3 }}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
              >
                {live === false ? 'Enter Mock Dashboard →' : 'Enter Dashboard →'}
              </motion.button>
              <div className="flex items-center gap-3 text-[10px] uppercase tracking-[0.15em]">
                <a href="/auth/login" className="text-cyan hover:text-text-hi transition-colors">
                  Login
                </a>
                <span className="text-text-ghost">/</span>
                <a href="/auth/logout" className="text-text-mid hover:text-text-hi transition-colors">
                  Logout
                </a>
              </div>
              <div className="mt-2 w-full max-w-115 rounded border border-border bg-header/80 px-4 py-3">
                <div className="text-[9px] uppercase tracking-wide text-text-mid mb-2">Preset test suites</div>
                <div className="mb-3 grid grid-cols-1 md:grid-cols-2 gap-2">
                  <label className="rounded border border-border px-3 py-2 bg-panel/60">
                    <div className="text-[9px] uppercase tracking-wide text-text-mid mb-1">Mock benchmark</div>
                    <button
                      onClick={() => setMockModeEnabled(prev => !prev)}
                      className={`rounded border px-2 py-1 text-[10px] uppercase tracking-wide transition-colors ${
                        mockModeEnabled
                          ? 'border-amber text-amber hover:border-amber/70'
                          : 'border-green text-green hover:border-green/70'
                      }`}
                    >
                      {mockModeEnabled ? 'On (fast mock data)' : 'Off (real benchmark)'}
                    </button>
                  </label>

                  <label className="rounded border border-border px-3 py-2 bg-panel/60">
                    <div className="text-[9px] uppercase tracking-wide text-text-mid mb-1">Proposer</div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setProposerMode('mock')}
                        className={`rounded border px-2 py-1 text-[10px] uppercase tracking-wide transition-colors ${
                          proposerMode === 'mock'
                            ? 'border-cyan text-cyan'
                            : 'border-border text-text-mid hover:text-text-hi'
                        }`}
                      >
                        Mock
                      </button>
                      <button
                        onClick={() => setProposerMode('claude')}
                        className={`rounded border px-2 py-1 text-[10px] uppercase tracking-wide transition-colors ${
                          proposerMode === 'claude'
                            ? 'border-cyan text-cyan'
                            : 'border-border text-text-mid hover:text-text-hi'
                        }`}
                      >
                        Claude
                      </button>
                    </div>
                  </label>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                  {PRESET_SUITES.map((preset) => (
                    <div
                      key={preset.id}
                      onClick={() => setSelectedPresetId(preset.id)}
                      className={`text-left rounded border px-3 py-2 transition-colors cursor-pointer ${
                        selectedPresetId === preset.id
                          ? 'border-cyan bg-cyan/5'
                          : 'border-border hover:border-cyan/40'
                      }`}
                    >
                      <div className="text-[10px] font-semibold uppercase tracking-wide text-cyan">{preset.label}</div>
                      <div className="text-[10px] text-text-mid mt-1">{preset.description}</div>
                    </div>
                  ))}
                </div>
                <div className="mt-3 flex items-center justify-between gap-3">
                  <div className="text-[10px] text-text-mid">
                    Selected: {PRESET_SUITES.find(p => p.id === selectedPresetId)?.label ?? 'None'} · {proposerMode} proposer · {mockModeEnabled ? 'mock bench' : 'real bench'}
                  </div>
                  <button
                    onClick={() => void handleLaunchPreset()}
                    disabled={launchingPreset !== null}
                    className="rounded border border-border-active px-3 py-1.5 text-[10px] uppercase tracking-wide text-cyan hover:border-cyan hover:bg-hover disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
                  >
                    Run selected suite
                  </button>
                </div>
                {launchingPreset && (
                  <div className="text-[10px] text-text-mid mt-2">Launching {launchingPreset} preset...</div>
                )}
                {launchError && (
                  <div className="text-[10px] text-red mt-2">{launchError}</div>
                )}
              </div>
            </div>
          )}
        </AnimatePresence>
      </div>

      <StatusReadout visible={phase === 'ready'} />
      <AnimatePresence>
        {entering && (
          <motion.div
            className="absolute inset-0 bg-void z-50"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5 }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
