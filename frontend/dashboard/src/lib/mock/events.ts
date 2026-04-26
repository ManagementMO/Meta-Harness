import type { LogEntry, IterationChapter, ForkEvent, RunInfo } from '../types';

export type MockSSEEvent =
  | { type: 'init'; delay: number; run: RunInfo }
  | { type: 'chapter'; delay: number; chapter: IterationChapter }
  | { type: 'log'; delay: number; entry: LogEntry }
  | { type: 'fork'; delay: number; fork: ForkEvent }
  | { type: 'score-update'; delay: number; candidate: string; score: number; delta: number; accepted: boolean }
  | { type: 'best-update'; delay: number; candidate: string; score: number };

let id = 0;
const nextId = () => `log-${++id}`;

export const MOCK_EVENTS: MockSSEEvent[] = [
  // Init
  { type: 'init', delay: 0, run: { runId: 'demo-2026-04-25', threadId: 'demo-2026-04-25', branches: 1, checkpointId: 'a8f3c2e1', bestScore: 0.62, status: 'running', iteration: 0 } },

  // Iter 1: retry-on-schema-drift
  { type: 'chapter', delay: 500, chapter: { iteration: 1, candidateName: 'retry-on-schema-drift', status: 'running', phases: { propose: true, validate: false, benchmark: false, frontier: false }, hypothesis: 'Add retry logic when tool output fails JSON schema validation', isForkBranch: false } },
  { type: 'log', delay: 800, entry: { id: nextId(), timestamp: '14:30:05', tag: 'orient', text: 'Scanning workspace: agents/base.py', expandable: false, candidateName: 'retry-on-schema-drift' } },
  { type: 'log', delay: 1200, entry: { id: nextId(), timestamp: '14:30:07', tag: 'plan', text: 'Strategy: wrap tool calls with schema validation retry', expandable: false, candidateName: 'retry-on-schema-drift' } },
  { type: 'log', delay: 1800, entry: { id: nextId(), timestamp: '14:30:10', tag: 'tool/read', text: 'Read agents/base.py (89 lines)', expandable: true, expandedContent: 'class CodingAgentHarness:\n    def execute_tool_call(self, ...):\n        ...', candidateName: 'retry-on-schema-drift' } },
  { type: 'log', delay: 2400, entry: { id: nextId(), timestamp: '14:30:12', tag: 'tool/patch', text: 'Patched agents/retry-on-schema-drift.py +12 -1', expandable: true, candidateName: 'retry-on-schema-drift' } },
  { type: 'log', delay: 3200, entry: { id: nextId(), timestamp: '14:30:15', tag: 'verify', text: 'pytest eval/tests/ — 5 passed in 2.1s', expandable: true, candidateName: 'retry-on-schema-drift' } },
  { type: 'log', delay: 3800, entry: { id: nextId(), timestamp: '14:30:18', tag: 'score', text: 'accuracy: 0.70 (+0.08)', expandable: false, candidateName: 'retry-on-schema-drift' } },
  { type: 'score-update', delay: 4000, candidate: 'retry-on-schema-drift', score: 0.70, delta: 0.08, accepted: true },

  // Iter 2: stricter-tool-hashing (rejected)
  { type: 'chapter', delay: 5000, chapter: { iteration: 2, candidateName: 'stricter-tool-hashing', status: 'running', phases: { propose: true, validate: false, benchmark: false, frontier: false }, hypothesis: 'Hash tool signatures to detect duplicates and force diversity', isForkBranch: false } },
  { type: 'log', delay: 5500, entry: { id: nextId(), timestamp: '14:30:25', tag: 'orient', text: 'Scanning workspace: agents/retry-on-schema-drift.py', expandable: false, candidateName: 'stricter-tool-hashing' } },
  { type: 'log', delay: 6000, entry: { id: nextId(), timestamp: '14:30:28', tag: 'tool/patch', text: 'Patched agents/stricter-tool-hashing.py +3 -1', expandable: true, candidateName: 'stricter-tool-hashing' } },
  { type: 'log', delay: 7000, entry: { id: nextId(), timestamp: '14:30:35', tag: 'verify', text: 'pytest eval/tests/ — 3 passed, 2 failed in 1.8s', expandable: true, candidateName: 'stricter-tool-hashing' } },
  { type: 'log', delay: 7500, entry: { id: nextId(), timestamp: '14:30:40', tag: 'score', text: 'accuracy: 0.66 (-0.04)', expandable: false, candidateName: 'stricter-tool-hashing' } },
  { type: 'score-update', delay: 7800, candidate: 'stricter-tool-hashing', score: 0.66, delta: -0.04, accepted: false },

  // Fork
  { type: 'fork', delay: 9000, fork: { timestamp: '14:30:50', parentCandidate: 'retry-on-schema-drift', checkpointId: 'a8f3c2e1', prior: 'Explore tool description rewrites', branchId: 'demo.fork.c7a1e3f0', rationale: 'Main branch regressed; forking from last accepted to try alternative approach' } },

  // Iter 3 main: early-exit-on-auth
  { type: 'chapter', delay: 10000, chapter: { iteration: 3, candidateName: 'early-exit-on-auth', status: 'running', phases: { propose: true, validate: false, benchmark: false, frontier: false }, hypothesis: 'Skip expensive validation when auth token is expired', isForkBranch: false } },
  { type: 'log', delay: 10500, entry: { id: nextId(), timestamp: '14:30:55', tag: 'orient', text: 'Scanning workspace: agents/retry-on-schema-drift.py', expandable: false, candidateName: 'early-exit-on-auth' } },
  { type: 'log', delay: 11200, entry: { id: nextId(), timestamp: '14:31:00', tag: 'tool/patch', text: 'Patched agents/early-exit-on-auth.py +6 -0', expandable: true, candidateName: 'early-exit-on-auth' } },
  { type: 'log', delay: 12000, entry: { id: nextId(), timestamp: '14:31:05', tag: 'verify', text: 'pytest eval/tests/ — 5 passed in 1.9s', expandable: true, candidateName: 'early-exit-on-auth' } },
  { type: 'log', delay: 12500, entry: { id: nextId(), timestamp: '14:31:10', tag: 'score', text: 'accuracy: 0.74 (+0.04)', expandable: false, candidateName: 'early-exit-on-auth' } },
  { type: 'score-update', delay: 12800, candidate: 'early-exit-on-auth', score: 0.74, delta: 0.04, accepted: true },

  // Iter 2' fork: rewrite-tool-descriptions
  { type: 'chapter', delay: 10200, chapter: { iteration: 2, candidateName: 'rewrite-tool-descriptions', status: 'running', phases: { propose: true, validate: false, benchmark: false, frontier: false }, hypothesis: 'Use LLM to rewrite tool descriptions for clarity', isForkBranch: true, threadId: 'demo.fork.c7a1e3f0' } },
  { type: 'log', delay: 10800, entry: { id: nextId(), timestamp: '14:30:58', tag: 'orient', text: 'Scanning workspace: agents/retry-on-schema-drift.py', expandable: false, candidateName: 'rewrite-tool-descriptions', threadId: 'demo.fork.c7a1e3f0' } },
  { type: 'log', delay: 11500, entry: { id: nextId(), timestamp: '14:31:02', tag: 'tool/patch', text: 'Patched agents/rewrite-tool-descriptions.py +10 -1', expandable: true, candidateName: 'rewrite-tool-descriptions', threadId: 'demo.fork.c7a1e3f0' } },
  { type: 'log', delay: 12200, entry: { id: nextId(), timestamp: '14:31:08', tag: 'verify', text: 'pytest eval/tests/ — 5 passed in 2.0s', expandable: true, candidateName: 'rewrite-tool-descriptions', threadId: 'demo.fork.c7a1e3f0' } },
  { type: 'log', delay: 12700, entry: { id: nextId(), timestamp: '14:31:15', tag: 'score', text: 'accuracy: 0.78 (+0.16)', expandable: false, candidateName: 'rewrite-tool-descriptions', threadId: 'demo.fork.c7a1e3f0' } },
  { type: 'score-update', delay: 13000, candidate: 'rewrite-tool-descriptions', score: 0.78, delta: 0.16, accepted: true },

  // Iter 4 main: more-specific-descriptions
  { type: 'chapter', delay: 14000, chapter: { iteration: 4, candidateName: 'more-specific-descriptions', status: 'running', phases: { propose: true, validate: false, benchmark: false, frontier: false }, hypothesis: 'Add detailed parameter docs and error cases to tool descriptions', isForkBranch: false } },
  { type: 'log', delay: 14500, entry: { id: nextId(), timestamp: '14:31:20', tag: 'tool/patch', text: 'Patched agents/more-specific-descriptions.py +8 -2', expandable: true, candidateName: 'more-specific-descriptions' } },
  { type: 'log', delay: 15500, entry: { id: nextId(), timestamp: '14:31:30', tag: 'verify', text: 'pytest eval/tests/ — 5 passed in 2.3s', expandable: true, candidateName: 'more-specific-descriptions' } },
  { type: 'log', delay: 16000, entry: { id: nextId(), timestamp: '14:31:35', tag: 'score', text: 'accuracy: 0.80 (+0.06)', expandable: false, candidateName: 'more-specific-descriptions' } },
  { type: 'score-update', delay: 16200, candidate: 'more-specific-descriptions', score: 0.80, delta: 0.06, accepted: true },

  // Iter 3' fork: few-shot-demos (NEW BEST)
  { type: 'chapter', delay: 14200, chapter: { iteration: 3, candidateName: 'few-shot-demos', status: 'running', phases: { propose: true, validate: false, benchmark: false, frontier: false }, hypothesis: 'Adding few-shot examples to tool descriptions should improve accuracy', isForkBranch: true, threadId: 'demo.fork.c7a1e3f0' } },
  { type: 'log', delay: 14800, entry: { id: nextId(), timestamp: '14:31:22', tag: 'orient', text: 'Scanning workspace: agents/rewrite-tool-descriptions.py', expandable: false, candidateName: 'few-shot-demos', threadId: 'demo.fork.c7a1e3f0' } },
  { type: 'log', delay: 15200, entry: { id: nextId(), timestamp: '14:31:25', tag: 'plan', text: 'Strategy: add 2-3 examples per tool call', expandable: false, candidateName: 'few-shot-demos', threadId: 'demo.fork.c7a1e3f0' } },
  { type: 'log', delay: 15800, entry: { id: nextId(), timestamp: '14:31:28', tag: 'tool/read', text: 'Read agents/base.py (42 lines)', expandable: true, expandedContent: 'class CodingAgentHarness:\n    def get_demonstrations(self, query_type):\n        return []', candidateName: 'few-shot-demos', threadId: 'demo.fork.c7a1e3f0' } },
  { type: 'log', delay: 16200, entry: { id: nextId(), timestamp: '14:31:32', tag: 'tool/patch', text: 'Patched agents/few-shot-demos.py +18 -3', expandable: true, candidateName: 'few-shot-demos', threadId: 'demo.fork.c7a1e3f0' } },
  { type: 'log', delay: 17000, entry: { id: nextId(), timestamp: '14:31:38', tag: 'verify', text: 'pytest eval/tests/ — 5 passed in 2.1s', expandable: true, candidateName: 'few-shot-demos', threadId: 'demo.fork.c7a1e3f0' } },
  { type: 'log', delay: 17500, entry: { id: nextId(), timestamp: '14:31:40', tag: 'score', text: 'accuracy: 0.85 (+0.07)', expandable: false, candidateName: 'few-shot-demos', threadId: 'demo.fork.c7a1e3f0' } },
  { type: 'score-update', delay: 17700, candidate: 'few-shot-demos', score: 0.85, delta: 0.07, accepted: true },
  { type: 'best-update', delay: 17800, candidate: 'few-shot-demos', score: 0.85 },

  // Memory pattern stored
  { type: 'log', delay: 18500, entry: { id: nextId(), timestamp: '14:31:45', tag: 'memory', text: 'Pattern stored: few-shot-demos approach yields +23% over baseline', expandable: false, candidateName: 'few-shot-demos', threadId: 'demo.fork.c7a1e3f0' } },
];
