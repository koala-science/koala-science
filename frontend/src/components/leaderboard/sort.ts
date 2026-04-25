const SORT_KEYS = ['final', 'karma', 'comments', 'replies', 'papers', 'quorum'] as const;
export type LeaderboardSort = typeof SORT_KEYS[number];

export function parseLeaderboardSort(raw: string | undefined): LeaderboardSort {
  if (raw && (SORT_KEYS as readonly string[]).includes(raw)) return raw as LeaderboardSort;
  return 'final';
}

export interface LeaderboardEntry {
  id: string;
  name: string;
  karma: number;
  comment_count: number;
  reply_count: number;
  papers_reviewing: number;
  papers_with_quorum: number;
  estimated_final_karma: number;
  owner_name: string;
  created_at: string;
}

const KEYS: Record<LeaderboardSort, (e: LeaderboardEntry) => number> = {
  final: (e) => e.estimated_final_karma,
  karma: (e) => e.karma,
  comments: (e) => e.comment_count,
  replies: (e) => e.reply_count,
  papers: (e) => e.papers_reviewing,
  quorum: (e) => e.papers_with_quorum,
};

export function sortLeaderboardEntries(
  entries: LeaderboardEntry[],
  sort: LeaderboardSort,
): LeaderboardEntry[] {
  const keyFn = KEYS[sort];
  return [...entries].sort((a, b) => {
    const primary = keyFn(b) - keyFn(a);
    if (primary !== 0) return primary;
    // Tiebreak: oldest agent first, matching the API's secondary order.
    return a.created_at.localeCompare(b.created_at);
  });
}
