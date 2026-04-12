'use client';

import { useCallback, useMemo } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { StandingsEntry } from '../lib/types';
import { classifyGateReason, type GateReasonKind } from '../lib/gate-reasons';

export type SortKey = 'rank' | 'verdicts' | 'gt_corr' | 'trust' | 'distance';

const SORT_KEYS: ReadonlyArray<SortKey> = [
  'rank',
  'verdicts',
  'gt_corr',
  'trust',
  'distance',
];

const REASON_VALUES: ReadonlyArray<GateReasonKind> = [
  'coverage',
  'no_gt',
  'neg_corr',
];

export interface StandingsFilters {
  sort: SortKey;
  reasons: Set<GateReasonKind>; // empty set = all
  passersOnly: boolean;
  query: string;
}

export interface UseStandingsFiltersResult {
  filters: StandingsFilters;
  setSort: (sort: SortKey) => void;
  toggleReason: (reason: GateReasonKind) => void;
  setPassersOnly: (v: boolean) => void;
  setQuery: (q: string) => void;
  filteredEntries: StandingsEntry[];
}

function parseSort(raw: string | null): SortKey {
  if (raw && (SORT_KEYS as ReadonlyArray<string>).includes(raw)) {
    return raw as SortKey;
  }
  return 'rank';
}

function parseReasons(raw: string | null): Set<GateReasonKind> {
  if (!raw) return new Set();
  const parts = raw
    .split(',')
    .map(s => s.trim())
    .filter(s => (REASON_VALUES as ReadonlyArray<string>).includes(s));
  return new Set(parts as GateReasonKind[]);
}

export function useStandingsFilters(
  entries: StandingsEntry[],
): UseStandingsFiltersResult {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const filters: StandingsFilters = useMemo(
    () => ({
      sort: parseSort(searchParams.get('sort')),
      reasons: parseReasons(searchParams.get('reason')),
      passersOnly: searchParams.get('passers') === '1',
      query: searchParams.get('q') ?? '',
    }),
    [searchParams],
  );

  const replaceParam = useCallback(
    (updater: (p: URLSearchParams) => void) => {
      const next = new URLSearchParams(searchParams.toString());
      updater(next);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  const setSort = useCallback(
    (sort: SortKey) => {
      replaceParam(p => {
        if (sort === 'rank') p.delete('sort');
        else p.set('sort', sort);
      });
    },
    [replaceParam],
  );

  const toggleReason = useCallback(
    (reason: GateReasonKind) => {
      replaceParam(p => {
        const current = parseReasons(p.get('reason'));
        if (current.has(reason)) current.delete(reason);
        else current.add(reason);
        if (current.size === 0) p.delete('reason');
        else p.set('reason', Array.from(current).join(','));
      });
    },
    [replaceParam],
  );

  const setPassersOnly = useCallback(
    (v: boolean) => {
      replaceParam(p => {
        if (v) p.set('passers', '1');
        else p.delete('passers');
      });
    },
    [replaceParam],
  );

  const setQuery = useCallback(
    (q: string) => {
      replaceParam(p => {
        if (q) p.set('q', q);
        else p.delete('q');
      });
    },
    [replaceParam],
  );

  const filteredEntries = useMemo(() => {
    let out = entries;
    if (filters.passersOnly) {
      out = out.filter(e => e.passed_gate);
    }
    if (filters.reasons.size > 0) {
      out = out.filter(e => {
        const kind = classifyGateReason(e);
        return kind !== 'pass' && filters.reasons.has(kind);
      });
    }
    const q = filters.query.trim().toLowerCase();
    if (q) {
      out = out.filter(
        e =>
          e.agent_name.toLowerCase().includes(q) ||
          e.agent_id.toLowerCase().includes(q),
      );
    }
    if (filters.sort !== 'rank') {
      // Clone before sorting; filtered array may alias the source.
      out = [...out];
      const by = filters.sort;
      out.sort((a, b) => {
        const av = sortValue(a, by);
        const bv = sortValue(b, by);
        // Higher is better for trust / gt_corr / verdicts; lower for distance.
        const asc = by === 'distance';
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        return asc ? av - bv : bv - av;
      });
    }
    return out;
  }, [entries, filters]);

  return {
    filters,
    setSort,
    toggleReason,
    setPassersOnly,
    setQuery,
    filteredEntries,
  };
}

function sortValue(e: StandingsEntry, key: SortKey): number | null {
  switch (key) {
    case 'verdicts':
      return e.n_verdicts;
    case 'gt_corr':
      return e.gt_corr_composite;
    case 'trust':
      return e.trust_pct;
    case 'distance':
      return e.distance_to_clear;
    case 'rank':
      return e.rank;
  }
}
