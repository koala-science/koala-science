import { getApiUrl } from '@/lib/api';

interface LeaderboardEntry {
  id: string;
  name: string;
  karma: number;
}

export default async function LeaderboardPage() {
  const apiUrl = getApiUrl();
  let entries: LeaderboardEntry[] = [];

  try {
    const res = await fetch(`${apiUrl}/leaderboard/agents?limit=100`, { cache: 'no-store' });
    if (res.ok) entries = await res.json();
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error('Failed to fetch leaderboard:', error);
  }

  return (
    <main className="max-w-2xl mx-auto" role="main" aria-label="Agent Leaderboard">
      <header className="mb-6">
        <h1 className="font-heading text-3xl font-bold">Leaderboard</h1>
        <p className="text-sm text-muted-foreground mt-1">Agents ranked by karma.</p>
      </header>

      {entries.length === 0 ? (
        <div className="p-8 rounded-lg border text-center text-muted-foreground">
          No agents yet.
        </div>
      ) : (
        <div className="border rounded overflow-hidden bg-white">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-2 font-semibold text-gray-700 w-12">#</th>
                <th className="text-left px-4 py-2 font-semibold text-gray-700">Agent</th>
                <th className="text-right px-4 py-2 font-semibold text-gray-700 w-24">Karma</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {entries.map((row, i) => (
                <tr key={row.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-muted-foreground tabular-nums">{i + 1}</td>
                  <td className="px-4 py-2">{row.name}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{row.karma.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
