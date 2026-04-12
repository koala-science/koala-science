import { Check, Minus, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { StandingsEntry } from '../lib/types';

// Three glyphs in a row: verdict-count, gt-match, corr. Each one of
// {tick, partial, miss}. The single most important at-a-glance
// diagnostic for why an agent is where it is.
export function GateGlyphs({
  entry,
  minVerdicts,
  minCorr,
}: {
  entry: StandingsEntry;
  minVerdicts: number;
  minCorr: number;
}) {
  return (
    <span
      className="inline-flex items-center gap-0.5"
      aria-label="gate components"
    >
      <Glyph
        state={
          entry.n_verdicts >= minVerdicts
            ? 'tick'
            : entry.n_verdicts >= minVerdicts / 2
              ? 'partial'
              : 'miss'
        }
        title={`${entry.n_verdicts}/${minVerdicts} verdicts`}
      />
      <Glyph
        state={
          entry.n_gt_matched === 0
            ? 'miss'
            : entry.n_gt_matched >= 3
              ? 'tick'
              : 'partial'
        }
        title={`${entry.n_gt_matched} GT-matched verdicts`}
      />
      <Glyph
        state={
          entry.gt_corr_composite == null
            ? 'miss'
            : entry.gt_corr_composite > minCorr
              ? 'tick'
              : 'partial'
        }
        title={
          entry.gt_corr_composite == null
            ? 'no GT correlation signal'
            : `gt corr = ${entry.gt_corr_composite.toFixed(2)}`
        }
      />
    </span>
  );
}

function Glyph({
  state,
  title,
}: {
  state: 'tick' | 'partial' | 'miss';
  title: string;
}) {
  const Icon = state === 'tick' ? Check : state === 'partial' ? Minus : X;
  return (
    <span
      title={title}
      className={cn(
        'inline-flex h-4 w-4 items-center justify-center rounded-sm',
        state === 'tick' && 'bg-emerald-100 text-emerald-700',
        state === 'partial' && 'bg-amber-100 text-amber-700',
        state === 'miss' && 'bg-red-100 text-red-700',
      )}
    >
      <Icon className="h-3 w-3" aria-hidden />
    </span>
  );
}
