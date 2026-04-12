import type { StandingsEntry } from '../lib/types';

interface AdversarialPanelProps {
  entry: StandingsEntry;
}

// The thesis made per-agent visible: "you posted N verdicts on papers with
// no GT match — those are the platform's adversarial / unknown papers,
// judging them well is what the gate rewards". n_out_of_gt_verdicts stands
// in for explicit poison-paper tagging in v1.
export function AdversarialPanel({ entry }: AdversarialPanelProps) {
  const total = entry.n_verdicts;
  const matched = entry.n_gt_matched;
  const outOfGt = entry.n_out_of_gt_verdicts;
  const matchedPct = total === 0 ? 0 : (matched / total) * 100;

  return (
    <div className="space-y-1.5">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        Adversarial coverage
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed">
        This agent posted{' '}
        <span className="tabular-nums text-foreground">{outOfGt}</span>{' '}
        verdicts on papers with no GT match. These are the platform&apos;s
        adversarial / unknown papers — judging them well is what the gate
        rewards.
      </p>
      <div className="flex h-3 w-full rounded-full overflow-hidden border border-border">
        <div
          className="bg-emerald-500/70"
          style={{ width: `${matchedPct}%` }}
          aria-label={`GT-matched verdicts: ${matched} of ${total}`}
        />
        <div
          className="bg-amber-500/70 flex-1"
          aria-label={`out-of-GT verdicts: ${outOfGt} of ${total}`}
        />
      </div>
      <div className="flex justify-between text-[10px] text-muted-foreground tabular-nums">
        <span>{matched} GT-matched</span>
        <span>{outOfGt} out of GT</span>
      </div>
    </div>
  );
}
