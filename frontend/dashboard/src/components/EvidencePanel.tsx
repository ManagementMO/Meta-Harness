"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { artifactUrl, getCandidateManifest, getEvidenceEvents, getRunReport } from "@/lib/api";
import { useDashboard } from "@/lib/state";
import { cn } from "@/lib/cn";
import { IconCpu, IconFingerprint, IconShieldCheck, IconStack } from "./ui/icons";

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function text(value: unknown, fallback = "unknown"): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

function metric(value: unknown): string {
  const parsed = record(value);
  const measured = parsed.value;
  const status = text(parsed.status);
  return `${measured === null || measured === undefined ? "unknown" : String(measured)} · ${status}`;
}

function EvidenceSection({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="glass-inset rounded-[var(--radius-card)] px-3.5 py-3">
      <h3 className="flex items-center gap-2 text-label uppercase text-ink-mid">
        {icon && <span className="text-ink-low">{icon}</span>}
        {title}
      </h3>
      <dl className="mt-2.5 grid grid-cols-[7.5rem_1fr] gap-x-3 gap-y-1.5 font-mono text-[11px] leading-[1.5]">
        {children}
      </dl>
    </section>
  );
}

function Row({
  label,
  value,
  tone = "ink",
  title,
}: {
  label: string;
  value: React.ReactNode;
  tone?: "ink" | "moss" | "ember" | "sand";
  title?: string;
}) {
  const toneClass = { ink: "text-ink", moss: "text-moss", ember: "text-ember", sand: "text-sand" }[tone];
  return (
    <>
      <dt className="text-ink-low truncate">{label}</dt>
      <dd className={cn("truncate", toneClass)} title={title}>
        {value}
      </dd>
    </>
  );
}

export function EvidencePanel() {
  const params = useParams<{ run_id: string }>();
  const { selectedNode, tree, run, mode } = useDashboard();
  const bestNode = tree.find((node) => node.status === "best");
  const selected = selectedNode ?? bestNode?.candidateId ?? bestNode?.candidate ?? null;
  const [manifest, setManifest] = useState<Record<string, unknown> | null>(null);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [events, setEvents] = useState<unknown[]>([]);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestKey = `${params.run_id}:${selected ?? "none"}`;
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    if (mode === "mock") return;
    let cancelled = false;
    Promise.all([
      selected ? getCandidateManifest(params.run_id, selected) : Promise.resolve(null),
      getRunReport(params.run_id),
      getEvidenceEvents(params.run_id, selected ?? undefined),
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
        setError(reason instanceof Error ? reason.message : "Evidence unavailable");
        setLoadedKey(requestKey);
      });
    return () => {
      cancelled = true;
    };
  }, [mode, params.run_id, requestKey, selected]);

  if (mode === "mock") {
    const node = tree.find(
      (value) => (value.candidateId ?? value.candidate) === selected || value.candidate === selected,
    );
    return (
      <div className="space-y-3">
        <p className="rounded-[var(--radius-card)] border border-sand/25 bg-sand/8 px-3.5 py-2.5 font-mono text-[11px] leading-[1.55] text-sand">
          Synthetic fixture data. No immutable source or provider evidence was produced.
        </p>
        <EvidenceSection title="Fixture summary" icon={<IconFingerprint size={12} />}>
          <Row label="Candidate" value={node?.candidate ?? "none"} title={node?.candidate} />
          <Row label="Accuracy" value={node?.scores.accuracy.toFixed(2) ?? "unknown"} />
          <Row label="Measurement" value="synthetic" tone="sand" />
          <Row label="Research use" value="not permitted" tone="ember" />
        </EvidenceSection>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-3" aria-label="Loading evidence">
        <div className="h-4 rounded-[6px] bg-white/[0.04] animate-breathe" />
        <div className="h-24 rounded-[var(--radius-card)] bg-white/[0.03]" />
        <div className="h-24 rounded-[var(--radius-card)] bg-white/[0.03]" />
      </div>
    );
  }

  if (error) {
    return (
      <p className="rounded-[var(--radius-card)] border border-ember/25 bg-ember/8 px-3.5 py-2.5 font-mono text-[11px] text-ember">
        {error}
      </p>
    );
  }

  const source = record(manifest?.source);
  const provenance = record(manifest?.provenance);
  const policy = record(report?.policy);
  const results = record(report?.results);
  const selectedResult = record(results[String(manifest?.candidate_id ?? "")]);
  const usage = record(selectedResult.usage);
  const failureCategories = Array.isArray(selectedResult.failure_categories)
    ? selectedResult.failure_categories.map((value) => String(value))
    : [];
  const candidateEvents = events.filter((value) => {
    const event = record(value);
    return (
      event.entity_id === manifest?.candidate_id ||
      record(event.payload).candidate_id === manifest?.candidate_id
    );
  });
  const failures = candidateEvents.filter((value) => {
    const event = record(value);
    return text(event.event_type, "") === "TaskAttemptFinished" && record(event.payload).passed === false;
  });
  const artifactRefs = Array.from(
    new Map(
      candidateEvents
        .flatMap((value) => {
          const refs = record(value).artifact_refs;
          return Array.isArray(refs) ? refs.map(record) : [];
        })
        .filter((ref) => typeof ref.sha256 === "string")
        .map((ref) => [String(ref.sha256), ref] as const),
    ).values(),
  );

  return (
    <div className="space-y-3">
      {run?.isSynthetic && (
        <p className="rounded-[var(--radius-card)] border border-sand/25 bg-sand/8 px-3.5 py-2.5 font-mono text-[11px] leading-[1.55] text-sand">
          Synthetic fixture data. Do not use this run as a research result.
        </p>
      )}
      <EvidenceSection title="Candidate identity" icon={<IconFingerprint size={12} />}>
        <Row label="Candidate ID" value={text(manifest?.candidate_id)} title={text(manifest?.candidate_id)} />
        <Row label="Source SHA-256" value={text(source.sha256)} title={text(source.sha256)} />
        <Row
          label="Parent IDs"
          value={Array.isArray(manifest?.parent_ids) ? manifest.parent_ids.join(", ") || "none" : "unknown"}
        />
        <Row label="Git commit" value={text(provenance.git_commit)} title={text(provenance.git_commit)} />
        <Row label="Runtime SHA-256" value={text(provenance.runtime_sha256)} title={text(provenance.runtime_sha256)} />
      </EvidenceSection>
      <EvidenceSection title="Evaluation contract" icon={<IconShieldCheck size={12} />}>
        <Row label="Mode" value={text(report?.mode, run?.mode ?? "research")} />
        <Row label="Policy" value={text(policy.policy_id)} title={text(policy.policy_id)} />
        <Row label="Inner model" value={text(policy.inner_model, text(manifest?.inner_model))} />
        <Row label="Sandbox" value={text(policy.sandbox_profile)} />
        <Row label="Parent policy" value={text(report?.parent_policy)} />
      </EvidenceSection>
      <EvidenceSection title="Usage and failures" icon={<IconCpu size={12} />}>
        <Row label="Input tokens" value={metric(usage.input_tokens)} />
        <Row label="Output tokens" value={metric(usage.output_tokens)} />
        <Row label="Cached tokens" value={metric(usage.cached_tokens)} />
        <Row label="Model calls" value={metric(usage.model_calls)} />
        <Row label="Tool calls" value={metric(usage.tool_calls)} />
        <Row label="Verify retries" value={metric(usage.verification_retries)} />
        <Row label="Wall seconds" value={metric(usage.wall_seconds)} />
        <Row
          label="Failure count"
          value={String(selectedResult.failure_count ?? 0)}
          tone={Number(selectedResult.failure_count ?? 0) > 0 ? "ember" : "moss"}
        />
        <Row label="Categories" value={failureCategories.join(", ") || "none"} />
      </EvidenceSection>
      <EvidenceSection title="Evidence summary" icon={<IconStack size={12} />}>
        <Row label="Candidate events" value={candidateEvents.length} />
        <Row label="Failed attempts" value={failures.length} tone={failures.length > 0 ? "ember" : "moss"} />
        <Row label="Raw artifacts" value={`${artifactRefs.length} content-addressed`} />
        <Row label="Rollback" value="refinement events enabled" />
      </EvidenceSection>
      <section className="glass-inset rounded-[var(--radius-card)] px-3.5 py-3">
        <h3 className="flex items-center gap-2 text-label uppercase text-ink-mid">
          <span className="text-ink-low">
            <IconStack size={12} />
          </span>
          Artifact links
        </h3>
        {artifactRefs.length > 0 ? (
          <ul className="mt-2.5 space-y-1 font-mono text-[11px] leading-[1.5]">
            {artifactRefs.slice(0, 12).map((ref) => {
              const digest = String(ref.sha256);
              return (
                <li key={digest} className="truncate">
                  <a
                    className="text-frost-dim underline underline-offset-2 decoration-white/25 hover:text-frost-bright transition-colors duration-150"
                    href={artifactUrl(params.run_id, digest)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {digest.slice(0, 16)} · {text(ref.media_type, "artifact")}
                  </a>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="mt-2.5 font-mono text-[11px] leading-[1.5] text-ink-low">
            Run a candidate evaluation to produce downloadable evidence artifacts.
          </p>
        )}
      </section>
      {!selected && (
        <p className="font-mono text-[11px] leading-[1.55] text-ink-low px-1">
          Select a candidate in the trajectory to inspect its provenance.
        </p>
      )}
    </div>
  );
}
