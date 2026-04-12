import type { StandingsEntry } from '../lib/types';
import { cn } from '@/lib/utils';

interface SignalBreakdownProps {
  entry: StandingsEntry;
}

const ROWS: { key: keyof StandingsEntry; label: string }[] = [
  { key: 'gt_corr_avg_score', label: 'vs avg reviewer score' },
  { key: 'gt_corr_accepted', label: 'vs acceptance' },
  { key: 'gt_corr_citations', label: 'vs citations/year' },
];

export function SignalBreakdown({ entry }: SignalBreakdownProps) {
  return (
    <div className="space-y-2">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        GT signal breakdown
      </div>
      <div className="space-y-1.5">
        {ROWS.map(r => {
          const v = entry[r.key] as number | null;
          return (
            <div key={r.key} className="flex items-center gap-2 text-xs">
              <span className="w-32 text-muted-foreground shrink-0">
                {r.label}
              </span>
              <div className="flex-1 relative h-2 bg-muted rounded-full overflow-hidden">
                <div className="absolute top-0 bottom-0 left-1/2 w-px bg-border" />
                {v != null && <Bar value={v} />}
              </div>
              <span className="w-10 text-right tabular-nums">
                {v == null ? 'n/a' : v >= 0 ? `+${v.toFixed(2)}` : v.toFixed(2)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Bar({ value }: { value: number }) {
  const clamped = Math.max(-1, Math.min(1, value));
  const pct = Math.abs(clamped) * 50;
  const isPos = clamped >= 0;
  return (
    <div
      className={cn(
        'absolute top-0 bottom-0 rounded-full',
        isPos ? 'bg-emerald-500/70' : 'bg-red-500/70',
      )}
      style={{
        left: isPos ? '50%' : `${50 - pct}%`,
        width: `${pct}%`,
      }}
    />
  );
}
