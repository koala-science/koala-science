import type { StandingsEntry } from '../lib/types';

interface TrustDecompositionProps {
  entry: StandingsEntry;
}

export function TrustDecomposition({ entry }: TrustDecompositionProps) {
  return (
    <div className="space-y-1.5">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        Trust decomposition
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Stat
          label="raw"
          value={entry.trust == null ? '—' : entry.trust.toFixed(2)}
        />
        <Stat
          label="normalized"
          value={
            entry.trust_pct == null
              ? '—'
              : `${(entry.trust_pct * 100).toFixed(0)}%`
          }
        />
        <Stat
          label="activity"
          value={entry.activity == null ? '—' : entry.activity.toString()}
        />
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-muted/30 p-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="font-heading text-base tabular-nums mt-0.5">{value}</div>
    </div>
  );
}
