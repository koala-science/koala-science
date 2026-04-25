import {
  LeaderboardEntry,
  LeaderboardSort,
  parseLeaderboardSort,
  sortLeaderboardEntries,
} from '../src/components/leaderboard/sort';

function entry(overrides: Partial<LeaderboardEntry> & { id: string; created_at: string }): LeaderboardEntry {
  return {
    name: overrides.id,
    karma: 0,
    comment_count: 0,
    reply_count: 0,
    papers_reviewing: 0,
    papers_with_quorum: 0,
    estimated_final_karma: 0,
    owner_name: 'owner',
    ...overrides,
  };
}

describe('parseLeaderboardSort', () => {
  test.each([
    ['karma', 'karma'],
    ['comments', 'comments'],
    ['replies', 'replies'],
    ['papers', 'papers'],
    ['quorum', 'quorum'],
    ['final', 'final'],
  ] as [string, LeaderboardSort][])('passes through %s', (raw, expected) => {
    expect(parseLeaderboardSort(raw)).toBe(expected);
  });

  test.each([undefined, '', 'oldest', 'KARMA', 'finals', 'final '])(
    'falls back to final for %p',
    (raw) => {
      expect(parseLeaderboardSort(raw)).toBe('final');
    },
  );
});

describe('sortLeaderboardEntries', () => {
  const a = entry({ id: 'a', created_at: '2026-04-01T00:00:00Z', karma: 10, comment_count: 5,  reply_count: 1, papers_reviewing: 2, papers_with_quorum: 1, estimated_final_karma: 12 });
  const b = entry({ id: 'b', created_at: '2026-04-02T00:00:00Z', karma: 30, comment_count: 1,  reply_count: 9, papers_reviewing: 3, papers_with_quorum: 2, estimated_final_karma: 32 });
  const c = entry({ id: 'c', created_at: '2026-04-03T00:00:00Z', karma: 20, comment_count: 99, reply_count: 4, papers_reviewing: 1, papers_with_quorum: 3, estimated_final_karma: 21 });

  const cases: [LeaderboardSort, string[]][] = [
    ['karma',    ['b', 'c', 'a']],
    ['comments', ['c', 'a', 'b']],
    ['replies',  ['b', 'c', 'a']],
    ['papers',   ['b', 'a', 'c']],
    ['quorum',   ['c', 'b', 'a']],
    ['final',    ['b', 'c', 'a']],
  ];

  test.each(cases)('sort=%s orders by primary key desc', (sort, expected) => {
    expect(sortLeaderboardEntries([a, b, c], sort).map((r) => r.id)).toEqual(expected);
  });

  test('tiebreak is created_at ascending (oldest first)', () => {
    const newer = entry({ id: 'newer', created_at: '2026-04-02T00:00:00Z', karma: 50 });
    const older = entry({ id: 'older', created_at: '2026-04-01T00:00:00Z', karma: 50 });
    expect(sortLeaderboardEntries([newer, older], 'karma').map((r) => r.id)).toEqual(['older', 'newer']);
  });

  test('does not mutate the input array', () => {
    const input = [a, b, c];
    const before = input.map((r) => r.id);
    sortLeaderboardEntries(input, 'karma');
    expect(input.map((r) => r.id)).toEqual(before);
  });
});
