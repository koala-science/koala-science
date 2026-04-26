'use client';

import { useEffect, useState } from 'react';
import { MessageSquare, Users, FileText, Sparkles } from 'lucide-react';
import { getApiUrl } from '@/lib/api';

type Stats = {
  comments_recent: number;
  active_reviewers_recent: number;
  papers_active_recent: number;
  papers_released_today: number;
};

const REFRESH_MS = 60_000;

export function ActivityStrip() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch(`${getApiUrl()}/activity/stats`)
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => { if (!cancelled && data) setStats(data); })
        .catch(() => {});
    };
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  if (!stats) return null;

  type StatItem = {
    value: number;
    label: string;
    Icon: React.ComponentType<{ className?: string }>;
    accent?: 'amber';
  };

  const lastHour: StatItem[] = [
    { value: stats.comments_recent, label: 'comments', Icon: MessageSquare },
    { value: stats.active_reviewers_recent, label: 'reviewers', Icon: Users },
    { value: stats.papers_active_recent, label: 'papers', Icon: FileText },
  ].filter((item) => item.value > 0);

  if (lastHour.length === 0 && stats.papers_released_today === 0) return null;

  const allStats = [
    ...lastHour,
    ...(stats.papers_released_today > 0
      ? [{ value: stats.papers_released_today, label: 'released today', Icon: Sparkles, accent: 'amber' as const }]
      : []),
  ];

  return (
    <div
      className="rounded-xl border bg-gradient-to-r from-emerald-50/40 via-white to-white px-3 sm:px-4 py-2.5 shadow-sm"
      aria-label="Live platform activity"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4 sm:gap-y-2">
        <span className="self-start inline-flex items-center gap-1.5 rounded-full bg-emerald-100/80 text-emerald-700 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider">
          <span className="relative inline-flex h-1.5 w-1.5" aria-hidden>
            <span className="motion-safe:animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-500 opacity-75" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-600" />
          </span>
          Past 3h
        </span>

        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 sm:contents">
          {allStats.map(({ value, label, Icon, accent }, i) => (
            <Stat
              key={label}
              value={value}
              label={label}
              Icon={Icon}
              divider={i > 0}
              accent={accent}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function Stat({
  value,
  label,
  Icon,
  divider,
  accent,
}: {
  value: number;
  label: string;
  Icon: React.ComponentType<{ className?: string }>;
  divider: boolean;
  accent?: 'amber';
}) {
  return (
    <span className="inline-flex items-center gap-2">
      {divider && <span className="hidden sm:inline-block h-4 w-px bg-border" aria-hidden />}
      <Icon
        className={`h-3.5 w-3.5 shrink-0 ${
          accent === 'amber' ? 'text-amber-600' : 'text-muted-foreground'
        }`}
      />
      <span className="text-sm">
        <span className="font-bold tabular-nums text-foreground">{value}</span>{' '}
        <span className="text-muted-foreground">{label}</span>
      </span>
    </span>
  );
}
