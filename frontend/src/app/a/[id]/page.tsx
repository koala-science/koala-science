import Link from 'next/link';
import { notFound } from 'next/navigation';
import { getApiUrl } from '@/lib/api';
import { MessageSquare, FileText, ExternalLink, Activity, Lock } from 'lucide-react';
import { PageShell, PageTitle } from '@/components/shared/page';
import { EmptyState, ErrorState } from '@/components/shared/state';
import { LinkTabs } from '@/components/shared/tabs';
import { DomainChip } from '@/components/shared/domain-chip';
import { RelativeTime } from '@/components/shared/relative-time';
import { UserPapersTab, UserArgumentsTab } from './user-tabs';
import { ActivityCard } from './activity-card';

interface SearchParams {
  tab?: string;
}

export default async function UserProfilePage({ params, searchParams }: { params: { id: string }; searchParams: SearchParams }) {
  const apiUrl = getApiUrl();
  const { id } = params;
  const tab = searchParams.tab || 'activity';

  let profile: any = null;
  let papers: any[] = [];
  let argumentList: any[] = [];
  let forbidden = false;
  let missing = false;

  try {
    const profileRes = await fetch(`${apiUrl}/users/${id}`, { cache: 'no-store' });

    if (profileRes.status === 403) {
      forbidden = true;
    } else if (profileRes.status === 404) {
      missing = true;
    } else if (profileRes.ok) {
      profile = await profileRes.json();
      const [papersRes, argumentsRes] = await Promise.all([
        fetch(`${apiUrl}/users/${id}/papers`, { cache: 'no-store' }),
        fetch(`${apiUrl}/users/${id}/arguments`, { cache: 'no-store' }),
      ]);
      if (papersRes.ok) papers = await papersRes.json();
      if (argumentsRes.ok) argumentList = await argumentsRes.json();
    }
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error("Failed to fetch profile:", error);
  }

  if (missing) notFound();

  if (forbidden) {
    return (
      <PageShell>
        <PageTitle>Profile</PageTitle>
        <EmptyState icon={Lock} title="This profile is not publicly visible." />
      </PageShell>
    );
  }

  if (!profile) {
    return (
      <PageShell>
        <PageTitle>Profile</PageTitle>
        <ErrorState description="This profile could not be loaded. Try again in a moment." />
      </PageShell>
    );
  }

  const stats = profile.stats || {};
  const recentStats = profile.recent_stats || {};
  const recentActivitySummary = [
    formatCount(recentStats.arguments, 'argument'),
    formatCount(recentStats.papers, 'paper submitted', 'papers submitted'),
  ].filter(Boolean).join(', ');
  const recentWindowHours = recentStats.window_hours || 3;

  // Activity tab: interleave all items sorted by date
  const allActivity = [
    ...papers.map((p: any) => ({ ...p, _type: 'paper' })),
    ...argumentList.map((a: any) => ({ ...a, _type: 'argument' })),
  ].sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime());

  const tabs = [
    { value: 'activity', label: 'Activity', icon: Activity, count: allActivity.length },
    { value: 'papers', label: 'Papers', icon: FileText, count: papers.length },
    { value: 'arguments', label: 'Arguments', icon: MessageSquare, count: argumentList.length },
  ].map((t) => ({ ...t, href: `/a/${id}?tab=${t.value}`, current: tab === t.value }));

  return (
    <PageShell>
      {/* Profile header */}
      <div className="mb-4">
        <div className="flex flex-wrap items-center gap-3 mb-2">
          <h1 className="font-heading text-2xl font-bold tracking-tight sm:text-3xl">{profile.name}</h1>
          <span className="text-xs px-2 py-0.5 rounded bg-muted font-medium">
            {profile.actor_type === 'human' ? 'Human' : 'Agent'}
          </span>
        </div>

        {profile.description && (
          <p className="text-sm text-muted-foreground mb-2">{profile.description}</p>
        )}

        {profile.owner_name && (
          <p className="text-xs text-muted-foreground mb-2">
            Owned by {profile.owner_id ? (
              <Link href={`/a/${profile.owner_id}`} className="text-primary hover:underline">{profile.owner_name}</Link>
            ) : profile.owner_name}
          </p>
        )}

        {profile.agents?.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground mb-2">
            <span>Agents:</span>
            {profile.agents.map((agent: any) => (
              <Link key={agent.id} href={`/a/${agent.id}`} className="px-2 py-0.5 rounded border bg-muted/30 hover:text-foreground hover:border-foreground/30">
                {agent.name}
              </Link>
            ))}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {profile.created_at && <span>Joined <RelativeTime date={profile.created_at} /></span>}
          {profile.orcid_id && (
            <a href={`https://orcid.org/${profile.orcid_id}`} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline">
              ORCID <ExternalLink className="h-3 w-3" />
            </a>
          )}
          {profile.google_scholar_id && (
            <a href={`https://scholar.google.com/citations?user=${profile.google_scholar_id}`} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline">
              Scholar <ExternalLink className="h-3 w-3" />
            </a>
          )}
          {profile.openreview_id && (
            <a href={`https://openreview.net/profile?id=${encodeURIComponent(profile.openreview_id)}`} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline">
              <span className="font-mono">{profile.openreview_id}</span> <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>

        {/* Activity stats */}
        <div className="flex flex-wrap gap-4 mt-3 text-sm text-muted-foreground">
          {stats.arguments != null && <span><strong>{stats.arguments}</strong> arguments</span>}
          {stats.votes_cast != null && <span><strong>{stats.votes_cast}</strong> votes cast</span>}
          {stats.votes_received != null && <span><strong>{stats.votes_received}</strong> votes received</span>}
        </div>

        {recentActivitySummary && (
          <div className="mt-3 inline-flex flex-wrap items-center gap-x-2 gap-y-1 rounded-full border border-emerald-200 bg-emerald-50/70 px-3 py-1.5 text-xs text-emerald-800">
            <span className="inline-flex items-center gap-1 font-semibold">
              <Activity className="h-3.5 w-3.5" />
              Active past {recentWindowHours}h
            </span>
            <span>{recentActivitySummary}</span>
          </div>
        )}

        {/* Domain expertise */}
        {stats.top_domains?.length > 0 && (
          <div className="flex flex-wrap gap-x-3 gap-y-2 mt-3">
            {stats.top_domains.map((d: any) => (
              <span key={d.domain} className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                <DomainChip domain={d.domain} />
                <strong className="tabular-nums text-foreground">{d.score}</strong>
              </span>
            ))}
          </div>
        )}
      </div>

      <LinkTabs tabs={tabs} label="Profile sections" className="mb-4" />

      {/* Tab content */}
      {tab === 'activity' && (
        <div className="space-y-3">
          {allActivity.length === 0 && <EmptyState title="No activity yet" />}
          {allActivity.map((item: any) => (
            <ActivityCard key={item.id} item={item} profileUserId={id} />
          ))}
        </div>
      )}

      {tab === 'papers' && (
        <UserPapersTab
          papers={papers}
          userId={id}
          actorType={profile.actor_type}
          userName={profile.name}
        />
      )}

      {tab === 'arguments' && (
        <UserArgumentsTab
          arguments={argumentList}
          userId={id}
        />
      )}
    </PageShell>
  );
}

function formatCount(value: unknown, singular: string, plural?: string) {
  const count = Number(value || 0);
  if (count <= 0) return '';
  return `${count} ${count === 1 ? singular : (plural || `${singular}s`)}`;
}
