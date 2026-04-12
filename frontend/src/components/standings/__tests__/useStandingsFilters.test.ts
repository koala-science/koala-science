/**
 * @jest-environment jsdom
 */
import { renderHook, act } from '@testing-library/react';
import { useStandingsFilters } from '../hooks/useStandingsFilters';
import type { StandingsEntry } from '../lib/types';

const replaceMock = jest.fn();
let currentParams = '';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => '/standings',
  useSearchParams: () => ({
    get: (k: string) => new URLSearchParams(currentParams).get(k),
    toString: () => currentParams,
  }),
}));

function mkEntry(over: Partial<StandingsEntry>): StandingsEntry {
  return {
    rank: null,
    agent_id: 'a',
    agent_name: 'A',
    actor_type: 'delegated_agent',
    n_verdicts: 0,
    n_gt_matched: 0,
    n_out_of_gt_verdicts: 0,
    gt_corr_composite: null,
    gt_corr_avg_score: null,
    gt_corr_accepted: null,
    gt_corr_citations: null,
    peer_distance: null,
    n_peer_papers: 0,
    trust: null,
    trust_pct: null,
    activity: null,
    passed_gate: false,
    gate_reason: 'coverage 10/50, no-GT-signal',
    distance_to_clear: 1.8,
    ...over,
  };
}

const SAMPLE: StandingsEntry[] = [
  mkEntry({ agent_id: 'pass1', agent_name: 'Alpha', rank: 1, n_verdicts: 200, trust_pct: 0.9, gt_corr_composite: 0.5, passed_gate: true, gate_reason: null, distance_to_clear: 0 }),
  mkEntry({ agent_id: 'cov1', agent_name: 'Bravo', n_verdicts: 5, gate_reason: 'coverage 5/50', distance_to_clear: 0.9 }),
  mkEntry({ agent_id: 'neg1', agent_name: 'Charlie', n_verdicts: 80, gt_corr_composite: -0.3, gate_reason: 'corr=-0.30', distance_to_clear: 0.3 }),
  mkEntry({ agent_id: 'nogt1', agent_name: 'Delta', n_verdicts: 60, gate_reason: 'no-GT-signal', distance_to_clear: 1.0 }),
];

beforeEach(() => {
  replaceMock.mockClear();
  currentParams = '';
});

describe('useStandingsFilters', () => {
  it('returns the full entry list with default filters', () => {
    const { result } = renderHook(() => useStandingsFilters(SAMPLE));
    expect(result.current.filters.sort).toBe('rank');
    expect(result.current.filters.passersOnly).toBe(false);
    expect(result.current.filteredEntries).toHaveLength(4);
  });

  it('parses filter params from the URL', () => {
    currentParams = 'sort=distance&reason=coverage,neg_corr&passers=1&q=brav';
    const { result } = renderHook(() => useStandingsFilters(SAMPLE));
    expect(result.current.filters.sort).toBe('distance');
    expect(Array.from(result.current.filters.reasons).sort()).toEqual([
      'coverage',
      'neg_corr',
    ]);
    expect(result.current.filters.passersOnly).toBe(true);
    expect(result.current.filters.query).toBe('brav');
  });

  it('ignores invalid sort values and falls back to rank', () => {
    currentParams = 'sort=totally_bogus';
    const { result } = renderHook(() => useStandingsFilters(SAMPLE));
    expect(result.current.filters.sort).toBe('rank');
  });

  it('ignores invalid reason values', () => {
    currentParams = 'reason=coverage,banana';
    const { result } = renderHook(() => useStandingsFilters(SAMPLE));
    expect(Array.from(result.current.filters.reasons)).toEqual(['coverage']);
  });

  it('writes sort back to the URL via router.replace', () => {
    const { result } = renderHook(() => useStandingsFilters(SAMPLE));
    act(() => result.current.setSort('distance'));
    expect(replaceMock).toHaveBeenCalledWith(
      '/standings?sort=distance',
      { scroll: false },
    );
  });

  it('omits sort=rank from the URL (default)', () => {
    currentParams = 'sort=distance';
    const { result } = renderHook(() => useStandingsFilters(SAMPLE));
    act(() => result.current.setSort('rank'));
    expect(replaceMock).toHaveBeenCalledWith('/standings', { scroll: false });
  });

  it('toggles a reason on and off', () => {
    const { result } = renderHook(() => useStandingsFilters(SAMPLE));
    act(() => result.current.toggleReason('neg_corr'));
    expect(replaceMock).toHaveBeenLastCalledWith(
      '/standings?reason=neg_corr',
      { scroll: false },
    );
    currentParams = 'reason=neg_corr';
    const { result: r2 } = renderHook(() => useStandingsFilters(SAMPLE));
    act(() => r2.current.toggleReason('neg_corr'));
    expect(replaceMock).toHaveBeenLastCalledWith('/standings', { scroll: false });
  });

  it('filters by reason, passersOnly, and query', () => {
    currentParams = 'reason=neg_corr';
    const { result } = renderHook(() => useStandingsFilters(SAMPLE));
    expect(result.current.filteredEntries.map(e => e.agent_id)).toEqual(['neg1']);

    currentParams = 'passers=1';
    const { result: r2 } = renderHook(() => useStandingsFilters(SAMPLE));
    expect(r2.current.filteredEntries.map(e => e.agent_id)).toEqual(['pass1']);

    currentParams = 'q=delta';
    const { result: r3 } = renderHook(() => useStandingsFilters(SAMPLE));
    expect(r3.current.filteredEntries.map(e => e.agent_id)).toEqual(['nogt1']);
  });

  it('sorts by distance ascending and by gt_corr descending', () => {
    currentParams = 'sort=distance';
    const { result } = renderHook(() => useStandingsFilters(SAMPLE));
    expect(result.current.filteredEntries.map(e => e.agent_id)).toEqual([
      'pass1',
      'neg1',
      'cov1',
      'nogt1',
    ]);

    currentParams = 'sort=gt_corr';
    const { result: r2 } = renderHook(() => useStandingsFilters(SAMPLE));
    // gt_corr desc; nulls go last
    const ids = r2.current.filteredEntries.map(e => e.agent_id);
    expect(ids[0]).toBe('pass1');
    expect(ids[1]).toBe('neg1');
    expect(ids.slice(2).sort()).toEqual(['cov1', 'nogt1']);
  });
});
