"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useDashboard } from "@/lib/state";
import { StatusPill, type PillState } from "./ui/StatusPill";
import { Button } from "./ui/Button";
import { IconArrowCounterClockwise, IconSignIn, IconSignOut } from "./ui/icons";
import type { DashboardState } from "@/lib/types";

type AuthProfile = {
  name?: string;
  email?: string;
};

export function derivePillState(state: Pick<DashboardState, "run" | "mode" | "sseConnected">): PillState {
  const { run, mode, sseConnected } = state;
  if (mode === "mock") return "demo";
  const status = run?.status?.toLowerCase() ?? "";
  if (status === "running") return sseConnected ? "live" : "reconnecting";
  if (status === "completed") return "completed";
  if (status === "failed" || status === "error") return "failed";
  return sseConnected ? "live" : "idle";
}

export function TopBar({ onReplay }: { onReplay?: () => void }) {
  const { run, mode, sseConnected } = useDashboard();
  const [profile, setProfile] = useState<AuthProfile | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetch("/auth/profile", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) return null;
        return (await response.json()) as AuthProfile;
      })
      .then((data) => {
        if (!cancelled) setProfile(data);
      })
      .catch(() => {
        if (!cancelled) setProfile(null);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const pill = derivePillState({ run, mode, sseConnected });

  return (
    <div className="panel-sheen relative z-20 h-12 flex items-center justify-between gap-4 px-4 border-b border-white/6 bg-white/[0.02] backdrop-blur-[14px] shrink-0">
      <div className="flex items-center gap-3 min-w-0">
        <Link
          href="/"
          className="flex items-center gap-2 text-[13px] font-semibold tracking-[0.18em] text-ink hover:text-frost-bright transition-colors duration-150"
        >
          <span aria-hidden="true" className="w-1.5 h-1.5 bg-frost shadow-[0_0_8px_rgba(255,255,255,0.35)]" />
          META-HARNESS
        </Link>
        {run && (
          <>
            <span aria-hidden="true" className="h-4 w-px bg-white/8" />
            <span className="font-mono text-[11px] text-ink-mid truncate" title={run.runId}>
              {run.runId}
            </span>
          </>
        )}
        <StatusPill state={pill} />
      </div>

      <div className="flex items-center gap-3 shrink-0">
        {run && (
          <span className="hidden lg:block font-mono text-[10px] uppercase tracking-[0.1em] text-ink-low">
            {run.mode ?? mode}
          </span>
        )}
        {onReplay && (
          <Button variant="ghost" size="sm" onClick={onReplay}>
            <IconArrowCounterClockwise size={12} />
            Replay run
          </Button>
        )}
        {profile && (
          <span className="font-mono text-[10px] text-ink-low truncate max-w-[180px]">
            {profile.name ?? profile.email ?? "authenticated"}
          </span>
        )}
        <a
          href={profile ? "/auth/logout" : "/auth/login"}
          className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-mid hover:text-frost-bright transition-colors duration-150"
        >
          {profile ? <IconSignOut size={12} /> : <IconSignIn size={12} />}
          {profile ? "Logout" : "Login"}
        </a>
      </div>
    </div>
  );
}
