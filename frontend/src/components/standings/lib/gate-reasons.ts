import type { StandingsEntry } from './types';

export type GateReasonKind = 'pass' | 'coverage' | 'no_gt' | 'neg_corr';

// Dominant failure mode drives the stripe color. Negative correlation is
// the strongest signal (measured and wrong), no-GT-signal next (can't
// measure), coverage last (most fixable). Matches how the backend composes
// `gate_reason` in build_merged_leaderboard.
export function classifyGateReason(entry: StandingsEntry): GateReasonKind {
  if (entry.passed_gate) return 'pass';
  const r = entry.gate_reason ?? '';
  if (/corr=-?\d/.test(r)) return 'neg_corr';
  if (r.includes('no-GT-signal')) return 'no_gt';
  return 'coverage';
}

export interface GateReasonStyle {
  stripe: string;   // left-border-stripe tailwind class
  label: string;    // short human-readable label
}

export const GATE_REASON_STYLES: Record<GateReasonKind, GateReasonStyle> = {
  pass: {
    stripe: 'border-l-emerald-500',
    label: 'past gate',
  },
  coverage: {
    stripe: 'border-l-amber-500',
    label: 'needs verdicts',
  },
  no_gt: {
    stripe: 'border-l-slate-400',
    label: 'no GT signal',
  },
  neg_corr: {
    stripe: 'border-l-red-500',
    label: 'negative corr',
  },
};
