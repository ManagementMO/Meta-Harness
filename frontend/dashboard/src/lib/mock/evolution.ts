import type { EvolutionRow } from '../types';

export const MOCK_CANDIDATES: EvolutionRow[] = [
  { iteration: 0, candidate: "baseline", parent_candidate_name: null, scores: { accuracy: 0.62 }, delta: null, outcome: "seed" },
  { iteration: 1, candidate: "retry-on-schema-drift", parent_candidate_name: "baseline", scores: { accuracy: 0.70 }, delta: 0.08, outcome: "70.0% (+8.0%)" },
  { iteration: 2, candidate: "stricter-tool-hashing", parent_candidate_name: "retry-on-schema-drift", scores: { accuracy: 0.66 }, delta: -0.04, outcome: "66.0% (-4.0%)" },
  { iteration: 3, candidate: "early-exit-on-auth", parent_candidate_name: "retry-on-schema-drift", scores: { accuracy: 0.74 }, delta: 0.04, outcome: "74.0% (+4.0%)" },
  { iteration: 4, candidate: "more-specific-descriptions", parent_candidate_name: "early-exit-on-auth", scores: { accuracy: 0.80 }, delta: 0.06, outcome: "80.0% (+6.0%)" },
  { iteration: 2, candidate: "rewrite-tool-descriptions", parent_candidate_name: "retry-on-schema-drift", scores: { accuracy: 0.78 }, delta: 0.16, outcome: "78.0% (+16.0%)", thread_id: "demo.fork.c7a1e3f0" },
  { iteration: 3, candidate: "few-shot-demos", parent_candidate_name: "rewrite-tool-descriptions", scores: { accuracy: 0.85 }, delta: 0.07, outcome: "85.0% (+7.0%)", thread_id: "demo.fork.c7a1e3f0" },
];
