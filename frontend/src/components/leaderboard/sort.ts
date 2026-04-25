export type LeaderboardSort = 'karma' | 'comments' | 'replies' | 'papers' | 'quorum';

export function parseLeaderboardSort(raw: string | undefined): LeaderboardSort {
  if (raw === 'comments' || raw === 'replies' || raw === 'papers' || raw === 'quorum') return raw;
  return 'karma';
}
