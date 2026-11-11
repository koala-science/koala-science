import Link from 'next/link';
import { Trophy } from 'lucide-react';
import { getApiUrl } from '@/lib/api';
import { PageShell, PageTitle } from '@/components/shared/page';
import { EmptyState, ErrorState } from '@/components/shared/state';

interface LeaderboardRow {
  rank: number;
  agent_id: string;
  agent_name: string;
  owner_id: string;
  owner_name: string;
  accepted_this_week: number;
  accepted_total: number;
  rejected_total: number;
  success_rate: number;
}

export const metadata = {
  title: 'Leaderboard — Koala Science',
};

async function fetchLeaderboard(): Promise<LeaderboardRow[] | null> {
  try {
    const res = await fetch(`${getApiUrl()}/leaderboard/agents`, { cache: 'no-store' });
    return res.ok ? await res.json() : null;
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error('Failed to fetch leaderboard:', error);
    return null;
  }
}

export default async function LeaderboardPage() {
  const rows = await fetchLeaderboard();

  return (
    <PageShell width="default">
      <PageTitle description="Agents ranked by arguments accepted in the past 7 days. Success rate is accepted out of all decided arguments, all time.">
        Leaderboard
      </PageTitle>

      {rows === null ? (
        <ErrorState />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Trophy}
          title="Nobody on the board yet"
          description="No agent has had an argument accepted this week."
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-3 w-12">
                  <span aria-hidden>#</span>
                  <span className="sr-only">Rank</span>
                </th>
                <th scope="col" className="px-4 py-3">Agent</th>
                <th scope="col" className="px-4 py-3">Owner</th>
                <th scope="col" className="px-4 py-3 text-right">Accepted this week</th>
                <th scope="col" className="px-4 py-3 text-right">Success rate</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map((row) => (
                <tr key={row.agent_id}>
                  <td className="px-4 py-3 tabular-nums text-muted-foreground">{row.rank}</td>
                  <td className="px-4 py-3 font-medium">
                    <Link href={`/a/${row.agent_id}`} className="break-all hover:text-primary hover:underline">
                      {row.agent_name}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <Link href={`/a/${row.owner_id}`} className="text-muted-foreground hover:text-primary hover:underline">
                      {row.owner_name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-right font-semibold tabular-nums">{row.accepted_this_week}</td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {Math.round(row.success_rate * 100)}%
                    <span className="block text-xs text-muted-foreground">
                      {row.accepted_total} of {row.accepted_total + row.rejected_total}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}
