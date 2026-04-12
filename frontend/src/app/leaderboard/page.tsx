import LeaderboardClientPage from './page-client';

export default function LeaderboardPage({
  searchParams,
}: {
  searchParams?: Record<string, string | string[] | undefined>;
}) {
  return <LeaderboardClientPage searchParams={searchParams ?? {}} />;
}
