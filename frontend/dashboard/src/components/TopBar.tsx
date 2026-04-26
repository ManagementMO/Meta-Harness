'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useDashboard } from '@/lib/state';

type AuthProfile = {
  name?: string;
  email?: string;
};

export function TopBar({ onReplay }: { onReplay?: () => void }) {
  const { run, mode } = useDashboard();
  const [profile, setProfile] = useState<AuthProfile | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetch('/auth/profile', { cache: 'no-store' })
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

  return (
    <div className="h-12 flex items-center justify-between px-6 bg-header border-b border-border">
      <Link href="/" className="text-cyan text-sm font-semibold tracking-[3px] uppercase hover:text-text-hi transition-colors">META-HARNESS</Link>
      <div className="flex items-center gap-4">
        {onReplay && (
          <button
            onClick={onReplay}
            className="text-[10px] text-amber uppercase tracking-wide border border-border px-2 py-1 rounded hover:text-text-hi hover:border-amber/40 transition-colors"
          >
            Replay run
          </button>
        )}
        {run && (
          <span className="text-[10px] text-text-mid uppercase tracking-wide">
            {run.isMock ? 'mock run' : mode} · {run.status} · iter {run.iteration}
          </span>
        )}
        {profile && (
          <span className="text-[10px] text-text-mid truncate max-w-[220px]">
            {profile.name ?? profile.email ?? 'authenticated user'}
          </span>
        )}
        <a
          href={profile ? '/auth/logout' : '/auth/login'}
          className="text-[10px] text-cyan uppercase tracking-wide hover:text-text-hi transition-colors"
        >
          {profile ? 'Logout' : 'Login'}
        </a>
      </div>
    </div>
  );
}
