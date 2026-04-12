import { Bot } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { StandingsEntry } from '../lib/types';
import { classifyGateReason, GATE_REASON_STYLES } from '../lib/gate-reasons';
import { formatDistance } from '../lib/distance-fmt';

interface MasterListRowProps {
  entry: StandingsEntry;
  isSelected?: boolean;
  onSelect?: (agentId: string) => void;
}

export function MasterListRow({ entry, isSelected, onSelect }: MasterListRowProps) {
  const kind = classifyGateReason(entry);
  const style = GATE_REASON_STYLES[kind];
  const corr = entry.gt_corr_composite;
  const corrColor =
    corr == null
      ? 'text-muted-foreground'
      : corr > 0.3
        ? 'text-emerald-700'
        : corr > 0
          ? 'text-foreground'
          : 'text-red-700';
  const peer = entry.peer_distance;

  return (
    <tr
      data-testid="master-list-row"
      data-gate-kind={kind}
      data-selected={isSelected ? 'true' : undefined}
      onClick={onSelect ? () => onSelect(entry.agent_id) : undefined}
      className={cn(
        'border-t border-border hover:bg-muted/30 border-l-4',
        style.stripe,
        onSelect && 'cursor-pointer',
        isSelected && 'bg-muted/60',
      )}
    >
      <td className="p-3 font-medium tabular-nums whitespace-nowrap">
        {entry.passed_gate ? (
          <span className="text-muted-foreground">#{entry.rank}</span>
        ) : (
          <span
            data-testid="distance-pill"
            className="inline-block px-1.5 py-0.5 rounded bg-muted text-muted-foreground text-xs font-mono"
            title={`distance to clear: ${entry.distance_to_clear.toFixed(3)}`}
          >
            {formatDistance(entry.distance_to_clear)}
          </span>
        )}
      </td>
      <td className="p-3 font-medium overflow-hidden">
        <span className="flex items-center gap-1.5 min-w-0">
          <Bot className="h-3.5 w-3.5 text-purple-600 shrink-0" />
          <span className="truncate" title={entry.agent_id}>
            {entry.agent_name}
          </span>
        </span>
      </td>
      <td className="p-3 text-right tabular-nums whitespace-nowrap">
        {entry.n_verdicts}
      </td>
      <td className="p-3 text-right tabular-nums whitespace-nowrap text-muted-foreground">
        {entry.n_gt_matched}
      </td>
      <td className={cn('p-3 text-right tabular-nums whitespace-nowrap', corrColor)}>
        {corr == null ? '—' : corr >= 0 ? `+${corr.toFixed(2)}` : corr.toFixed(2)}
      </td>
      <td className="p-3 text-right tabular-nums whitespace-nowrap">
        {peer == null ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <span
            title={`${entry.n_peer_papers} paper${entry.n_peer_papers === 1 ? '' : 's'} with ≥3 peers`}
          >
            {peer.toFixed(2)}
          </span>
        )}
      </td>
      <td className="p-3 text-right tabular-nums whitespace-nowrap">
        {entry.trust_pct == null ? '—' : (entry.trust_pct * 100).toFixed(0) + '%'}
      </td>
      <td className="p-3 text-xs">
        {entry.passed_gate ? (
          <span className="inline-block px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 whitespace-nowrap">
            past gate
          </span>
        ) : (
          <span
            className="text-muted-foreground"
            title={entry.gate_reason ?? ''}
          >
            {style.label}
          </span>
        )}
      </td>
    </tr>
  );
}
