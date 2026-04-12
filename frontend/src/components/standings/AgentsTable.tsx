'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Bot, User, ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Input } from '@/components/ui/input';
import type { StandingsEntry, StandingsResponse } from './lib/types';

// ── Types ────────────────────────────────────────────────────────────────────

type SortKey =
  | 'rank'
  | 'agent_name'
  | 'actor_type'
  | 'n_verdicts'
  | 'passed_gate'
  | 'gt_corr_composite'
  | 'n_gt_matched'
  | 'trust_pct'
  | 'peer_distance';

type SortDir = 'asc' | 'desc';

interface Props {
  data: StandingsResponse;
}

// ── Medal helpers ─────────────────────────────────────────────────────────────

const MEDAL: Record<number, { label: string; cls: string }> = {
  1: { label: '#1', cls: 'text-amber-500 font-bold' },
  2: { label: '#2', cls: 'text-slate-400 font-bold' },
  3: { label: '#3', cls: 'text-amber-700 font-bold' },
};

// ── SortHeader ────────────────────────────────────────────────────────────────

function SortHeader({
  label,
  sortKey,
  current,
  dir,
  onSort,
  className,
  title,
}: {
  label: string;
  sortKey: SortKey;
  current: SortKey;
  dir: SortDir;
  onSort: (k: SortKey) => void;
  className?: string;
  title?: string;
}) {
  const active = current === sortKey;
  const Icon = active ? (dir === 'asc' ? ChevronUp : ChevronDown) : ChevronsUpDown;
  return (
    <th
      scope="col"
      title={title}
      className={cn(
        'px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide cursor-pointer select-none whitespace-nowrap hover:text-foreground transition-colors',
        active && 'text-foreground',
        className,
      )}
      onClick={() => onSort(sortKey)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <Icon className="h-3 w-3 opacity-60" />
      </span>
    </th>
  );
}

// ── Gate cell ─────────────────────────────────────────────────────────────────

function GateCell({
  entry,
  isFullMode,
  gateMin,
}: {
  entry: StandingsEntry;
  isFullMode: boolean;
  gateMin: number;
}) {
  if (!isFullMode) {
    const pct = Math.min(100, (entry.n_verdicts / gateMin) * 100);
    return (
      <td className="px-3 py-2 whitespace-nowrap">
        <div className="flex items-center gap-1.5 min-w-[80px]">
          <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
            <div
              className="h-full bg-teal-500 rounded-full transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-xs text-muted-foreground tabular-nums">
            {entry.n_verdicts}/{gateMin}
          </span>
        </div>
      </td>
    );
  }
  return (
    <td className="px-3 py-2 whitespace-nowrap" title={entry.gate_reason ?? undefined}>
      {entry.passed_gate ? (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">
          Pass
        </span>
      ) : (
        <span
          className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800 cursor-help"
          title={entry.gate_reason ?? undefined}
        >
          Fail
        </span>
      )}
    </td>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function AgentsTable({ data }: Props) {
  const { entries, gate_min_verdicts, n_gt_matched_papers } = data;
  const isFullMode = n_gt_matched_papers > 0;

  const searchParams = useSearchParams();
  const highlightId = searchParams.get('a');

  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [passersOnly, setPassersOnly] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>('rank');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const highlightRowRef = useRef<HTMLTableRowElement | null>(null);

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), 150);
    return () => clearTimeout(t);
  }, [query]);

  // Scroll highlight into view
  useEffect(() => {
    if (highlightId && highlightRowRef.current) {
      highlightRowRef.current.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [highlightId]);

  // Derived: which optional columns exist
  const showGtCorr = useMemo(
    () => isFullMode && entries.some(e => e.gt_corr_composite !== null),
    [isFullMode, entries],
  );
  const showGtMatched = useMemo(
    () => isFullMode && entries.some(e => e.n_gt_matched > 0),
    [isFullMode, entries],
  );

  // Sort handler
  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  // Filter + sort
  const displayed = useMemo(() => {
    let rows = [...entries];

    // text filter
    if (debouncedQuery.trim()) {
      const q = debouncedQuery.trim().toLowerCase();
      rows = rows.filter(
        e => e.agent_name.toLowerCase().includes(q) || e.agent_id.toLowerCase().includes(q),
      );
    }

    // passers only
    if (passersOnly) {
      if (isFullMode) {
        rows = rows.filter(e => e.passed_gate);
      } else {
        rows = rows.filter(e => e.n_verdicts >= gate_min_verdicts);
      }
    }

    // sort
    rows.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case 'rank': {
          // nulls last
          const ra = a.rank ?? Infinity;
          const rb = b.rank ?? Infinity;
          cmp = ra - rb;
          break;
        }
        case 'agent_name':
          cmp = a.agent_name.localeCompare(b.agent_name);
          break;
        case 'actor_type':
          cmp = a.actor_type.localeCompare(b.actor_type);
          break;
        case 'n_verdicts':
          cmp = a.n_verdicts - b.n_verdicts;
          break;
        case 'passed_gate':
          cmp = Number(b.passed_gate) - Number(a.passed_gate);
          break;
        case 'gt_corr_composite': {
          const ga = a.gt_corr_composite ?? -Infinity;
          const gb = b.gt_corr_composite ?? -Infinity;
          cmp = ga - gb;
          break;
        }
        case 'n_gt_matched':
          cmp = a.n_gt_matched - b.n_gt_matched;
          break;
        case 'trust_pct': {
          const ta = a.trust_pct ?? -Infinity;
          const tb = b.trust_pct ?? -Infinity;
          cmp = ta - tb;
          break;
        }
        case 'peer_distance': {
          const pa = a.peer_distance ?? Infinity;
          const pb = b.peer_distance ?? Infinity;
          cmp = pa - pb;
          break;
        }
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });

    return rows;
  }, [entries, debouncedQuery, passersOnly, isFullMode, gate_min_verdicts, sortKey, sortDir]);

  const sharedSortProps = { current: sortKey, dir: sortDir, onSort: handleSort };

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Search agents…"
          value={query}
          onChange={e => setQuery(e.target.value)}
          className="h-8 w-48 text-sm"
        />
        <button
          onClick={() => setPassersOnly(v => !v)}
          className={cn(
            'h-8 px-3 rounded-md text-xs font-medium border transition-colors',
            passersOnly
              ? 'bg-teal-600 text-white border-teal-600'
              : 'bg-background text-muted-foreground border-border hover:text-foreground',
          )}
        >
          {isFullMode ? 'Passers only' : `${gate_min_verdicts}+ verdicts only`}
        </button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-border scrollbar-thin">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 border-b border-border">
            <tr>
              {/* Sticky: Rank */}
              <th
                scope="col"
                className="sticky left-0 z-10 bg-muted/50 px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide cursor-pointer select-none hover:text-foreground transition-colors whitespace-nowrap"
                onClick={() => handleSort('rank')}
              >
                <span className="inline-flex items-center gap-1">
                  Rank
                  {sortKey === 'rank' ? (
                    sortDir === 'asc' ? (
                      <ChevronUp className="h-3 w-3 opacity-60" />
                    ) : (
                      <ChevronDown className="h-3 w-3 opacity-60" />
                    )
                  ) : (
                    <ChevronsUpDown className="h-3 w-3 opacity-60" />
                  )}
                </span>
              </th>
              {/* Sticky: Agent */}
              <th
                scope="col"
                className="sticky left-10 z-10 bg-muted/50 px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide cursor-pointer select-none hover:text-foreground transition-colors whitespace-nowrap"
                onClick={() => handleSort('agent_name')}
              >
                <span className="inline-flex items-center gap-1">
                  Agent
                  {sortKey === 'agent_name' ? (
                    sortDir === 'asc' ? (
                      <ChevronUp className="h-3 w-3 opacity-60" />
                    ) : (
                      <ChevronDown className="h-3 w-3 opacity-60" />
                    )
                  ) : (
                    <ChevronsUpDown className="h-3 w-3 opacity-60" />
                  )}
                </span>
              </th>
              <SortHeader label="Type" sortKey="actor_type" {...sharedSortProps} />
              <SortHeader label="Verdicts" sortKey="n_verdicts" {...sharedSortProps} />
              <SortHeader label="Gate" sortKey="passed_gate" {...sharedSortProps} />
              {showGtCorr && (
                <SortHeader label="GT Corr" sortKey="gt_corr_composite" {...sharedSortProps} />
              )}
              {showGtMatched && (
                <SortHeader label="GT Matched" sortKey="n_gt_matched" {...sharedSortProps} />
              )}
              <SortHeader label="Trust" sortKey="trust_pct" {...sharedSortProps} />
              <SortHeader
                label="Peer dist."
                sortKey="peer_distance"
                {...sharedSortProps}
                title="Lower is better"
              />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {displayed.map(entry => {
              const isHighlight = entry.agent_id === highlightId;
              const isPasser = entry.passed_gate;
              const medal = entry.rank != null ? MEDAL[entry.rank] : null;

              return (
                <tr
                  key={entry.agent_id}
                  ref={isHighlight ? highlightRowRef : null}
                  className={cn(
                    'hover:bg-muted/30 transition-colors',
                    isPasser && 'border-l-2 border-l-green-500',
                    !isPasser && 'text-muted-foreground',
                    isHighlight && 'animate-flash',
                  )}
                >
                  {/* Rank — sticky */}
                  <td className="sticky left-0 z-10 bg-background px-3 py-2 whitespace-nowrap tabular-nums w-10">
                    {entry.rank != null ? (
                      <span className={cn('text-sm', medal?.cls ?? 'text-foreground')}>
                        {medal?.label ?? `#${entry.rank}`}
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        {entry.distance_to_clear > 0
                          ? `+${entry.distance_to_clear.toFixed(2)}`
                          : '—'}
                      </span>
                    )}
                  </td>

                  {/* Agent — sticky */}
                  <td className="sticky left-10 z-10 bg-background px-3 py-2 whitespace-nowrap max-w-[180px]">
                    <Link
                      href={`/a/${entry.agent_id}`}
                      className="inline-flex items-center gap-1.5 text-sm font-medium text-foreground hover:text-teal-700 hover:underline transition-colors"
                    >
                      {entry.actor_type === 'human' ? (
                        <User className="h-3.5 w-3.5 text-cyan-600 shrink-0" />
                      ) : (
                        <Bot className="h-3.5 w-3.5 text-purple-600 shrink-0" />
                      )}
                      <span className="truncate">{entry.agent_name}</span>
                    </Link>
                  </td>

                  {/* Type pill */}
                  <td className="px-3 py-2 whitespace-nowrap">
                    {entry.actor_type === 'human' ? (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-cyan-100 text-cyan-800">
                        Human
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800">
                        Agent
                      </span>
                    )}
                  </td>

                  {/* Verdicts */}
                  <td className="px-3 py-2 whitespace-nowrap tabular-nums text-sm">
                    {entry.n_verdicts}
                  </td>

                  {/* Gate */}
                  <GateCell entry={entry} isFullMode={isFullMode} gateMin={gate_min_verdicts} />

                  {/* GT Corr */}
                  {showGtCorr && (
                    <td className="px-3 py-2 whitespace-nowrap tabular-nums text-sm">
                      {entry.gt_corr_composite != null
                        ? entry.gt_corr_composite.toFixed(2)
                        : '—'}
                    </td>
                  )}

                  {/* GT Matched */}
                  {showGtMatched && (
                    <td className="px-3 py-2 whitespace-nowrap tabular-nums text-sm">
                      {entry.n_gt_matched}
                    </td>
                  )}

                  {/* Trust */}
                  <td className="px-3 py-2 whitespace-nowrap tabular-nums text-sm">
                    {entry.trust_pct != null ? `${(entry.trust_pct * 100).toFixed(0)}%` : '—'}
                  </td>

                  {/* Peer distance */}
                  <td
                    className="px-3 py-2 whitespace-nowrap tabular-nums text-sm"
                    title="Lower is better"
                  >
                    {entry.peer_distance != null ? entry.peer_distance.toFixed(2) : '—'}
                  </td>
                </tr>
              );
            })}

            {displayed.length === 0 && (
              <tr>
                <td
                  colSpan={
                    5 + (showGtCorr ? 1 : 0) + (showGtMatched ? 1 : 0) + 2
                  }
                  className="px-3 py-8 text-center text-sm text-muted-foreground"
                >
                  No agents match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
