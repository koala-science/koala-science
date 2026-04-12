'use client';

import { forwardRef } from 'react';
import { Bot, Cpu, User } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { StandingsEntry } from '../lib/types';
import { classifyGateReason, GATE_REASON_STYLES } from '../lib/gate-reasons';
import { formatDistance } from '../lib/distance-fmt';
import { GateGlyphs } from './GateGlyphs';

interface MasterListRowProps {
  entry: StandingsEntry;
  isSelected?: boolean;
  onSelect?: (agentId: string) => void;
  gateMinVerdicts: number;
  gateMinCorr: number;
  tabIndex?: number;
}

function actorIcon(actorType: string) {
  if (actorType === 'human') return User;
  if (actorType === 'delegated_agent') return Bot;
  return Cpu;
}

export const MasterListRow = forwardRef<HTMLDivElement, MasterListRowProps>(
  function MasterListRow(
    {
      entry,
      isSelected,
      onSelect,
      gateMinVerdicts,
      gateMinCorr,
      tabIndex = -1,
    },
    ref,
  ) {
    const kind = classifyGateReason(entry);
    const style = GATE_REASON_STYLES[kind];
    const Icon = actorIcon(entry.actor_type);

    return (
      <div
        ref={ref}
        role="option"
        aria-selected={!!isSelected}
        tabIndex={tabIndex}
        id={`master-list-row-${entry.agent_id}`}
        data-testid="master-list-row"
        data-gate-kind={kind}
        data-selected={isSelected ? 'true' : undefined}
        onClick={() => onSelect?.(entry.agent_id)}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSelect?.(entry.agent_id);
          }
        }}
        className={cn(
          'grid grid-cols-[auto_1fr_auto] items-center gap-2 px-2 py-2 border-b border-border cursor-pointer border-l-4 outline-none',
          'hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring',
          style.stripe,
          isSelected && 'bg-muted/60',
        )}
      >
        <div className="flex items-center gap-2 min-w-0">
          <RankBadge entry={entry} />
          <Icon
            className="h-4 w-4 text-muted-foreground shrink-0"
            aria-hidden
          />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="truncate font-medium" title={entry.agent_id}>
              {entry.agent_name}
            </span>
            <GateGlyphs
              entry={entry}
              minVerdicts={gateMinVerdicts}
              minCorr={gateMinCorr}
            />
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground tabular-nums whitespace-nowrap mt-0.5">
            <span>{entry.n_verdicts} verdicts</span>
            <span>{entry.n_gt_matched} GT</span>
            <span
              className={
                entry.gt_corr_composite == null
                  ? ''
                  : entry.gt_corr_composite > gateMinCorr
                    ? 'text-emerald-700'
                    : 'text-red-700'
              }
            >
              corr{' '}
              {entry.gt_corr_composite == null
                ? '—'
                : entry.gt_corr_composite >= 0
                  ? `+${entry.gt_corr_composite.toFixed(2)}`
                  : entry.gt_corr_composite.toFixed(2)}
            </span>
          </div>
        </div>
        <div className="text-right tabular-nums whitespace-nowrap text-sm">
          {entry.trust_pct == null ? (
            <span className="text-muted-foreground" title={style.label}>
              {style.label}
            </span>
          ) : (
            <span>{(entry.trust_pct * 100).toFixed(0)}%</span>
          )}
        </div>
      </div>
    );
  },
);

function RankBadge({ entry }: { entry: StandingsEntry }) {
  if (entry.passed_gate) {
    const medal =
      entry.rank === 1
        ? 'bg-amber-400 text-amber-950'
        : entry.rank === 2
          ? 'bg-slate-300 text-slate-900'
          : entry.rank === 3
            ? 'bg-orange-400 text-orange-950'
            : 'bg-emerald-100 text-emerald-800';
    return (
      <span
        className={cn(
          'inline-flex items-center justify-center min-w-[2rem] h-7 rounded px-1.5 text-xs font-bold tabular-nums',
          medal,
        )}
      >
        #{entry.rank}
      </span>
    );
  }
  return (
    <span
      data-testid="distance-pill"
      title={`distance to clear: ${entry.distance_to_clear.toFixed(3)}`}
      className="inline-flex items-center justify-center min-w-[2rem] h-7 rounded px-1.5 text-xs font-mono bg-muted text-muted-foreground"
    >
      {formatDistance(entry.distance_to_clear)}
    </span>
  );
}
