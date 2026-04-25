export type LeaderboardSort = 'karma' | 'comments' | 'replies' | 'papers';

export function parseLeaderboardSort(raw: string | undefined): LeaderboardSort {
  if (raw === 'comments' || raw === 'replies' || raw === 'papers') return raw;
  return 'karma';
}
