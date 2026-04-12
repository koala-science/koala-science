import type { StandingsEntry, StandingsResponse } from '../lib/types';
import { cn } from '@/lib/utils';

interface GateGaugesProps {
  entry: StandingsEntry;
  data: StandingsResponse;
}

// Three half-circle gauges: verdict count, GT-matched count, corr.
// The middle gauge greys out when the platform has 0 GT matches so users
// understand the gate is blocked at a layer above them.
export function GateGauges({ entry, data }: GateGaugesProps) {
  const platformBlocked = data.n_gt_matched_papers === 0;

  const verdictTarget = data.gate_min_verdicts;
  const verdictFrac = Math.min(1, entry.n_verdicts / verdictTarget);
  const verdictLabel =
    entry.n_verdicts >= verdictTarget
      ? 'cleared'
      : `short ${verdictTarget - entry.n_verdicts}`;

  const gtTarget = Math.max(3, Math.min(verdictTarget / 5, 10));
  const gtFrac = Math.min(1, entry.n_gt_matched / gtTarget);
  const gtLabel = platformBlocked
    ? 'platform blocked'
    : entry.n_gt_matched >= gtTarget
      ? 'cleared'
      : `short ${Math.max(0, Math.ceil(gtTarget - entry.n_gt_matched))}`;

  const corr = entry.gt_corr_composite;
  const corrFrac =
    corr == null ? 0 : Math.max(0, Math.min(1, (corr + 1) / 2));
  const corrLabel =
    corr == null ? 'no signal' : corr > data.gate_min_corr ? 'cleared' : 'below gate';

  return (
    <div className="grid grid-cols-3 gap-2">
      <Gauge
        title="verdicts"
        value={`${entry.n_verdicts}`}
        subtitle={verdictLabel}
        frac={verdictFrac}
        good={entry.n_verdicts >= verdictTarget}
      />
      <Gauge
        title="GT-matched"
        value={`${entry.n_gt_matched}`}
        subtitle={gtLabel}
        frac={gtFrac}
        good={!platformBlocked && entry.n_gt_matched >= gtTarget}
        dim={platformBlocked}
      />
      <Gauge
        title="GT corr"
        value={corr == null ? 'n/a' : corr >= 0 ? `+${corr.toFixed(2)}` : corr.toFixed(2)}
        subtitle={corrLabel}
        frac={corrFrac}
        good={corr != null && corr > data.gate_min_corr}
      />
    </div>
  );
}

function Gauge({
  title,
  value,
  subtitle,
  frac,
  good,
  dim,
}: {
  title: string;
  value: string;
  subtitle: string;
  frac: number;
  good: boolean;
  dim?: boolean;
}) {
  const radius = 40;
  const circumference = Math.PI * radius; // half circle
  const dash = circumference * (1 - frac);
  return (
    <div
      className={cn(
        'flex flex-col items-center gap-1 p-2 rounded-md border border-border bg-muted/30',
        dim && 'opacity-60',
      )}
    >
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      <svg viewBox="0 0 100 55" className="w-full h-12" aria-hidden>
        <path
          d="M10 50 A40 40 0 0 1 90 50"
          fill="none"
          stroke="rgb(226 232 240)"
          strokeWidth="8"
          strokeLinecap="round"
        />
        <path
          d="M10 50 A40 40 0 0 1 90 50"
          fill="none"
          stroke={good ? 'rgb(16 185 129)' : 'rgb(245 158 11)'}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={`${circumference} ${circumference}`}
          strokeDashoffset={dash}
        />
      </svg>
      <div className="text-sm font-semibold tabular-nums">{value}</div>
      <div className="text-[10px] text-muted-foreground text-center">
        {subtitle}
      </div>
    </div>
  );
}
