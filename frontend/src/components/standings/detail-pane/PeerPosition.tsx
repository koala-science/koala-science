import type { StandingsEntry } from '../lib/types';

interface PeerPositionProps {
  entry: StandingsEntry;
}

export function PeerPosition({ entry }: PeerPositionProps) {
  const d = entry.peer_distance;
  if (d == null) {
    return (
      <div className="space-y-1.5">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">
          Peer alignment
        </div>
        <div className="text-xs text-muted-foreground">
          No papers with ≥3 peers to compare against yet.
        </div>
      </div>
    );
  }
  // Peer distance is an absolute distance from the per-paper median on a
  // 0-10 verdict scale. Cap the bar at 5.0 so the common case (0-2) reads.
  const pct = Math.min(1, d / 5);
  return (
    <div className="space-y-1.5">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        Peer alignment
      </div>
      <div className="relative h-2 bg-muted rounded-full overflow-hidden">
        <div
          className="absolute top-0 left-0 bottom-0 bg-blue-500/70 rounded-full"
          style={{ width: `${pct * 100}%` }}
        />
      </div>
      <div className="text-xs text-muted-foreground">
        <span className="tabular-nums text-foreground">{d.toFixed(2)}</span>{' '}
        median distance across{' '}
        <span className="tabular-nums text-foreground">{entry.n_peer_papers}</span>{' '}
        papers with ≥3 peer verdicts. Lower is closer to consensus.
      </div>
    </div>
  );
}
