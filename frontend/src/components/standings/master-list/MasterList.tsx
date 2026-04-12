'use client';

import { useEffect, useRef } from 'react';
import type { StandingsEntry, StandingsResponse } from '../lib/types';
import { MasterListRow } from './MasterListRow';
import { MasterListToolbar } from './MasterListToolbar';
import type { SortKey, StandingsFilters } from '../hooks/useStandingsFilters';
import type { GateReasonKind } from '../lib/gate-reasons';

interface MasterListProps {
  data: StandingsResponse;
  entries: StandingsEntry[]; // filtered view
  selectedAgentId?: string | null;
  onSelect?: (agentId: string) => void;
  filters: StandingsFilters;
  setSort: (sort: SortKey) => void;
  toggleReason: (reason: GateReasonKind) => void;
  setPassersOnly: (v: boolean) => void;
  setQuery: (q: string) => void;
}

export function MasterList({
  data,
  entries,
  selectedAgentId,
  onSelect,
  filters,
  setSort,
  toggleReason,
  setPassersOnly,
  setQuery,
}: MasterListProps) {
  const listRef = useRef<HTMLDivElement>(null);

  // Keyboard navigation: Up/Down move selection. The listbox owns focus;
  // individual rows have tabIndex=-1 so focus stays at the container.
  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!entries.length) return;
    const currentIdx = selectedAgentId
      ? entries.findIndex(x => x.agent_id === selectedAgentId)
      : -1;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = entries[Math.min(entries.length - 1, currentIdx + 1)];
      if (next) onSelect?.(next.agent_id);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const next = entries[Math.max(0, currentIdx - 1)];
      if (next) onSelect?.(next.agent_id);
    } else if (e.key === 'Home') {
      e.preventDefault();
      onSelect?.(entries[0].agent_id);
    } else if (e.key === 'End') {
      e.preventDefault();
      onSelect?.(entries[entries.length - 1].agent_id);
    }
  };

  // Scroll the selected row into view if it leaves the visible region.
  useEffect(() => {
    if (!selectedAgentId || !listRef.current) return;
    const el = listRef.current.querySelector(
      `#master-list-row-${CSS.escape(selectedAgentId)}`,
    );
    if (el && 'scrollIntoView' in el) {
      (el as HTMLElement).scrollIntoView({ block: 'nearest' });
    }
  }, [selectedAgentId]);

  return (
    <div className="rounded-lg border border-border bg-background flex flex-col min-h-0">
      <MasterListToolbar
        allEntries={data.entries}
        filters={filters}
        setSort={setSort}
        toggleReason={toggleReason}
        setPassersOnly={setPassersOnly}
        setQuery={setQuery}
      />
      <div
        ref={listRef}
        role="listbox"
        aria-label="Standings"
        aria-activedescendant={
          selectedAgentId ? `master-list-row-${selectedAgentId}` : undefined
        }
        tabIndex={0}
        onKeyDown={handleKeyDown}
        className="flex-1 overflow-y-auto max-h-[70vh] focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {entries.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground text-center">
            No agents match the current filters.
          </div>
        ) : (
          entries.map(e => (
            <MasterListRow
              key={e.agent_id}
              entry={e}
              isSelected={e.agent_id === selectedAgentId}
              onSelect={onSelect}
              gateMinVerdicts={data.gate_min_verdicts}
              gateMinCorr={data.gate_min_corr}
            />
          ))
        )}
      </div>
    </div>
  );
}
