'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { getCandidateManifest, getEvidenceEvents, getRunReport } from '@/lib/api';
import { useDashboard } from '@/lib/state';

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

function text(value: unknown, fallback = 'unknown'): string {
  return typeof value === 'string' && value.length > 0 ? value : fallback;
}

export function EvidencePanel() {
  const params = useParams<{ run_id: string }>();
  const { selectedNode, tree, run, mode } = useDashboard();
  const bestNode = tree.find(node => node.status === 'best');
  const selected = selectedNode ?? bestNode?.candidateId ?? bestNode?.candidate ?? null;
  const [manifest, setManifest] = useState<Record<string, unknown> | null>(null);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [events, setEvents] = useState<unknown[]>([]);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestKey = `${params.run_id}:${selected ?? 'none'}`;
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    if (mode === 'mock') return;
    let cancelled = false;
    Promise.all([
      selected ? getCandidateManifest(params.run_id, selected) : Promise.resolve(null),
      getRunReport(params.run_id),
      getEvidenceEvents(params.run_id),
    ])
      .then(([candidateManifest, runReport, evidenceEvents]) => {
        if (cancelled) return;
        setManifest(candidateManifest);
        setReport(runReport);
        setEvents(evidenceEvents);
        setError(null);
        setLoadedKey(requestKey);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setError(reason instanceof Error ? reason.message : 'Evidence unavailable');
        setLoadedKey(requestKey);
      });
    return () => {
      cancelled = true;
    };
  }, [mode, params.run_id, requestKey, selected]);

  if (mode === 'mock') {
    const node = tree.find(value => (value.candidateId ?? value.candidate) === selected || value.candidate === selected);
    return (
      <div className="space-y-4 text-xs tabular-nums">
        <div className="rounded border border-amber px-3 py-2 text-amber">
          Synthetic fixture data. No immutable source or provider evidence was produced.
        </div>
        <section className="rounded border border-border bg-header px-3 py-3">
          <h3 className="text-balance font-semibold text-text-hi">Fixture summary</h3>
          <dl className="mt-2 grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-text-mid">
            <dt>Candidate</dt><dd className="truncate text-text-hi">{node?.candidate ?? 'none'}</dd>
            <dt>Accuracy</dt><dd className="text-text-hi">{node?.scores.accuracy.toFixed(2) ?? 'unknown'}</dd>
            <dt>Measurement</dt><dd className="text-amber">synthetic</dd>
            <dt>Research use</dt><dd className="text-red">not permitted</dd>
          </dl>
        </section>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-3" aria-label="Loading evidence">
        <div className="h-4 rounded bg-header" />
        <div className="h-20 rounded bg-header" />
        <div className="h-20 rounded bg-header" />
      </div>
    );
  }

  if (error) {
    return <div className="rounded border border-red px-3 py-2 text-xs text-red">{error}</div>;
  }

  const source = record(manifest?.source);
  const provenance = record(manifest?.provenance);
  const policy = record(report?.policy);
  const candidateEvents = events.filter(value => {
    const event = record(value);
    return event.entity_id === manifest?.candidate_id || record(event.payload).candidate_id === manifest?.candidate_id;
  });
  const failures = candidateEvents.filter(value => {
    const event = record(value);
    return text(event.event_type, '') === 'TaskAttemptFinished' && record(event.payload).passed === false;
  });

  return (
    <div className="space-y-4 text-xs tabular-nums">
      {run?.isSynthetic && (
        <div className="rounded border border-amber px-3 py-2 text-amber">
          Synthetic fixture data. Do not use this run as a research result.
        </div>
      )}
      <section className="rounded border border-border bg-header px-3 py-3">
        <h3 className="text-balance font-semibold text-text-hi">Candidate identity</h3>
        <dl className="mt-2 grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-text-mid">
          <dt>Candidate ID</dt><dd className="truncate text-text-hi">{text(manifest?.candidate_id)}</dd>
          <dt>Source SHA-256</dt><dd className="truncate text-text-hi">{text(source.sha256)}</dd>
          <dt>Parent IDs</dt><dd className="truncate text-text-hi">{Array.isArray(manifest?.parent_ids) ? manifest.parent_ids.join(', ') || 'none' : 'unknown'}</dd>
          <dt>Git commit</dt><dd className="truncate text-text-hi">{text(provenance.git_commit)}</dd>
          <dt>Runtime SHA-256</dt><dd className="truncate text-text-hi">{text(provenance.runtime_sha256)}</dd>
        </dl>
      </section>
      <section className="rounded border border-border bg-header px-3 py-3">
        <h3 className="text-balance font-semibold text-text-hi">Evaluation contract</h3>
        <dl className="mt-2 grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-text-mid">
          <dt>Mode</dt><dd className="text-text-hi">{text(report?.mode, run?.mode ?? 'research')}</dd>
          <dt>Policy</dt><dd className="truncate text-text-hi">{text(policy.policy_id)}</dd>
          <dt>Inner model</dt><dd className="truncate text-text-hi">{text(policy.inner_model, text(manifest?.inner_model))}</dd>
          <dt>Sandbox</dt><dd className="text-text-hi">{text(policy.sandbox_profile)}</dd>
          <dt>Parent policy</dt><dd className="text-text-hi">{text(report?.parent_policy)}</dd>
        </dl>
      </section>
      <section className="rounded border border-border bg-header px-3 py-3">
        <h3 className="text-balance font-semibold text-text-hi">Evidence summary</h3>
        <dl className="mt-2 grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-text-mid">
          <dt>Candidate events</dt><dd className="text-text-hi">{candidateEvents.length}</dd>
          <dt>Failed attempts</dt><dd className={failures.length > 0 ? 'text-red' : 'text-green'}>{failures.length}</dd>
          <dt>Raw artifacts</dt><dd className="text-text-hi">content-addressed</dd>
          <dt>Rollback</dt><dd className="text-text-hi">refinement events enabled</dd>
        </dl>
      </section>
      {!selected && (
        <div className="rounded border border-border px-3 py-2 text-pretty text-text-mid">
          Select a candidate in the trajectory to inspect its provenance.
        </div>
      )}
    </div>
  );
}
