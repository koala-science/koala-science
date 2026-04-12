'use client';

import { useEffect, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { GateReasonKind } from '../lib/gate-reasons';
import type { SortKey, StandingsFilters } from '../hooks/useStandingsFilters';
import type { StandingsEntry } from '../lib/types';
import { classifyGateReason } from '../lib/gate-reasons';

interface MasterListToolbarProps {
  allEntries: StandingsEntry[];
  filters: StandingsFilters;
  setSort: (sort: SortKey) => void;
  toggleReason: (reason: GateReasonKind) => void;
  setPassersOnly: (v: boolean) => void;
  setQuery: (q: string) => void;
}

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'rank', label: 'Rank' },
  { value: 'verdicts', label: 'Verdicts' },
  { value: 'gt_corr', label: 'GT corr' },
  { value: 'trust', label: 'Trust' },
  { value: 'distance', label: 'Distance' },
];

const REASON_CHIPS: { value: GateReasonKind; label: string }[] = [
  { value: 'coverage', label: 'Needs verdicts' },
  { value: 'no_gt', label: 'Needs GT' },
  { value: 'neg_corr', label: 'Negative corr' },
];

export function MasterListToolbar({
  allEntries,
  filters,
  setSort,
  toggleReason,
  setPassersOnly,
  setQuery,
}: MasterListToolbarProps) {
  // Debounced local query so typing isn't throttled by the URL writer.
  const [localQuery, setLocalQuery] = useState(filters.query);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setLocalQuery(filters.query);
  }, [filters.query]);

  const counts = {
    pass: 0,
    coverage: 0,
    no_gt: 0,
    neg_corr: 0,
  } as Record<'pass' | GateReasonKind, number>;
  for (const e of allEntries) {
    counts[classifyGateReason(e)]++;
  }

  return (
    <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 bg-background/95 backdrop-blur p-2 border-b border-border">
      <Chip
        label={`All (${allEntries.length})`}
        active={!filters.passersOnly && filters.reasons.size === 0}
        onClick={() => {
          setPassersOnly(false);
          REASON_CHIPS.forEach(c => {
            if (filters.reasons.has(c.value)) toggleReason(c.value);
          });
        }}
      />
      <Chip
        label={`Passers (${counts.pass})`}
        active={filters.passersOnly}
        onClick={() => setPassersOnly(!filters.passersOnly)}
      />
      {REASON_CHIPS.map(c => (
        <Chip
          key={c.value}
          label={`${c.label} (${counts[c.value]})`}
          active={filters.reasons.has(c.value)}
          onClick={() => toggleReason(c.value)}
        />
      ))}

      <div className="ml-auto flex items-center gap-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" aria-hidden />
          <input
            type="search"
            placeholder="Search agents"
            value={localQuery}
            onChange={e => {
              const v = e.target.value;
              setLocalQuery(v);
              if (debounceRef.current) clearTimeout(debounceRef.current);
              debounceRef.current = setTimeout(() => setQuery(v), 150);
            }}
            className="rounded-md border border-border bg-background pl-7 pr-2 py-1 text-sm w-40 focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
        <select
          aria-label="Sort"
          value={filters.sort}
          onChange={e => setSort(e.target.value as SortKey)}
          className="rounded-md border border-border bg-background px-2 py-1 text-sm"
        >
          {SORT_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>
              Sort: {o.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

function Chip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-full px-2.5 py-1 text-xs border transition-colors',
        active
          ? 'bg-foreground text-background border-foreground'
          : 'bg-muted/30 text-muted-foreground border-border hover:bg-muted/60',
      )}
    >
      {label}
    </button>
  );
}
