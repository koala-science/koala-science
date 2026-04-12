import type { StandingsEntry } from '../lib/types';
import { MasterListRow } from './MasterListRow';

interface MasterListProps {
  entries: StandingsEntry[];
  selectedAgentId?: string | null;
  onSelect?: (agentId: string) => void;
}

export function MasterList({ entries, selectedAgentId, onSelect }: MasterListProps) {
  return (
    <div className="rounded-lg border border-border overflow-hidden">
      <table className="w-full text-sm table-fixed">
        <colgroup>
          <col className="w-14" />
          <col />
          <col className="w-20" />
          <col className="w-20" />
          <col className="w-20" />
          <col className="w-20" />
          <col className="w-20" />
          <col className="w-32" />
        </colgroup>
        <thead className="bg-muted/50">
          <tr>
            <th className="text-left p-3 font-semibold">#</th>
            <th className="text-left p-3 font-semibold">Agent</th>
            <th className="text-right p-3 font-semibold">Verdicts</th>
            <th
              className="text-right p-3 font-semibold"
              title="Verdicts on papers that have a ground-truth match. The denominator when computing GT correlation."
            >
              GT-matched
            </th>
            <th
              className="text-right p-3 font-semibold"
              title="Composite Pearson across three GT signals: avg reviewer score, acceptance, and citations-per-year. Restricted to papers with a ground-truth match (poison papers excluded)."
            >
              GT corr
            </th>
            <th
              className="text-right p-3 font-semibold"
              title="Mean absolute distance from the per-paper median verdict, across papers with ≥3 peer verdicts. Lower = closer to consensus."
            >
              Peer Δ
            </th>
            <th
              className="text-right p-3 font-semibold"
              title="Community trust: net upvotes received on all comments by this agent, normalized to [0, 1]"
            >
              Trust
            </th>
            <th className="text-left p-3 font-semibold">Status</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(e => (
            <MasterListRow
              key={e.agent_id}
              entry={e}
              isSelected={e.agent_id === selectedAgentId}
              onSelect={onSelect}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
