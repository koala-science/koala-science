import { cn } from '@/lib/utils';
import type { StandingsResponse } from '../lib/types';

interface GateKpisProps {
  data: StandingsResponse;
}

export function GateKpis({ data }: GateKpisProps) {
  const noGt = data.n_gt_matched_papers === 0;
  return (
    <div className="grid grid-cols-2 gap-3">
      <Tile
        label="passing"
        value={data.n_passers}
        valueClass="text-emerald-600"
      />
      <Tile label="candidates" value={data.n_failers} valueClass="text-muted-foreground" />
      <Tile
        label="GT-matched papers"
        value={`${data.n_gt_matched_papers} / ${data.n_papers}`}
        valueClass={cn('text-sm', noGt ? 'text-amber-600' : 'text-foreground')}
      />
      <div className="rounded-lg border border-border bg-muted/30 p-3">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">
          gate
        </div>
        <div className="text-xs leading-snug mt-1">
          <span className="tabular-nums">{data.gate_min_verdicts}</span>+
          verdicts &amp; corr &gt;{' '}
          <span className="tabular-nums">{data.gate_min_corr}</span>
        </div>
      </div>
    </div>
  );
}

function Tile({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: number | string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 p-3">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className={cn('font-heading text-2xl tabular-nums mt-1', valueClass)}>
        {value}
      </div>
    </div>
  );
}
