import type { StandingsEntry } from '../lib/types';

export function ActivityStrip({ entry }: { entry: StandingsEntry }) {
  return (
    <div className="text-xs text-muted-foreground tabular-nums">
      <span className="text-foreground">{entry.n_verdicts}</span> total verdicts
      {' · '}
      activity score{' '}
      <span className="text-foreground">
        {entry.activity == null ? '—' : entry.activity}
      </span>
    </div>
  );
}
