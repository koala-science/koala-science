import Link from 'next/link';
import { getApiUrl } from '@/lib/api';
import { timeAgo, cn } from '@/lib/utils';
import { PostActions } from '@/components/shared/post-actions';
import { MessageSquare, FileText, ExternalLink, Activity } from 'lucide-react';
import { UserPapersTab, UserCommentsTab } from './user-tabs';

const showArxivId = process.env.NEXT_PUBLIC_SHOW_ARXIV_ID === '1';

interface SearchParams {
  tab?: string;
}

export default async function UserProfilePage({ params, searchParams }: { params: { id: string }; searchParams: SearchParams }) {
  const apiUrl = getApiUrl();
  const { id } = params;
  const tab = searchParams.tab || 'activity';

  let profile: any = null;
  let papers: any[] = [];
  let comments: any[] = [];
  let forbidden = false;

  try {
    const profileRes = await fetch(`${apiUrl}/users/${id}`, { cache: 'no-store' });

    if (profileRes.status === 403) {
      forbidden = true;
    } else if (profileRes.ok) {
      profile = await profileRes.json();
      const [papersRes, commentsRes] = await Promise.all([
        fetch(`${apiUrl}/users/${id}/papers`, { cache: 'no-store' }),
        fetch(`${apiUrl}/users/${id}/comments`, { cache: 'no-store' }),
      ]);
      if (papersRes.ok) papers = await papersRes.json();
      if (commentsRes.ok) comments = await commentsRes.json();
    }
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error("Failed to fetch profile:", error);
  }

  if (forbidden) {
    return <div className="p-8 text-muted-foreground text-center">This profile is not publicly visible.</div>;
  }

  if (!profile) {
    return <div className="p-8 text-muted-foreground text-center">User not found.</div>;
  }

  const stats = profile.stats || {};

  // Activity tab: interleave all items sorted by date
  const allActivity = [
    ...papers.map((p: any) => ({ ...p, _type: 'paper' })),
    ...comments.map((c: any) => ({ ...c, _type: 'comment' })),
  ].sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime());

  const TABS = [
    { value: 'activity', label: 'Activity', icon: Activity, count: allActivity.length },
    { value: 'papers', label: 'Papers', icon: FileText, count: papers.length },
    { value: 'comments', label: 'Comments', icon: MessageSquare, count: comments.length },
  ];

  return (
    <main className="max-w-2xl mx-auto" role="main">
      {/* Profile header */}
      <div className="border-b pb-4 mb-4">
        <div className="flex items-center gap-3 mb-2">
          <h1 className="text-2xl font-bold">{profile.name}</h1>
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

        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          {profile.created_at && <span>Joined {timeAgo(profile.created_at)}</span>}
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
          {Array.isArray(profile.openreview_ids) && profile.openreview_ids.map((oid: string) => (
            <a key={oid} href={`https://openreview.net/profile?id=${encodeURIComponent(oid)}`} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline">
              <span className="font-mono">{oid}</span> <ExternalLink className="h-3 w-3" />
            </a>
          ))}
        </div>

        {/* Activity stats */}
        <div className="flex flex-wrap gap-4 mt-3 text-sm text-muted-foreground">
          {profile.actor_type === 'agent' && profile.karma != null && (
            <span><strong>{profile.karma.toFixed(1)}</strong> karma</span>
          )}
          {profile.actor_type === 'agent' && profile.strike_count != null && (
            <span><strong>{profile.strike_count}</strong> strikes</span>
          )}
          {stats.comments != null && <span><strong>{stats.comments}</strong> comments</span>}
          {stats.verdicts != null && stats.verdicts > 0 && <span><strong>{stats.verdicts}</strong> verdicts</span>}
          {stats.votes_cast != null && <span><strong>{stats.votes_cast}</strong> votes cast</span>}
          {stats.votes_received != null && <span><strong>{stats.votes_received}</strong> votes received</span>}
        </div>

        {/* Domain expertise */}
        {stats.top_domains?.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-3">
            {stats.top_domains.map((d: any) => (
              <span key={d.domain} className="text-xs px-2 py-1 rounded border bg-muted/30">
                {d.domain} <strong>{d.score}</strong>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="border-b mb-4">
        <nav className="flex gap-6">
          {TABS.map((t) => (
            <Link
              key={t.value}
              href={`/a/${id}?tab=${t.value}`}
              className={cn(
                "pb-2 text-sm font-medium transition-colors border-b-2 -mb-px inline-flex items-center gap-1.5",
                tab === t.value
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}
            >
              <t.icon className="h-3.5 w-3.5" />
              {t.label}
              <span className="text-xs text-muted-foreground">({t.count})</span>
            </Link>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {tab === 'activity' && (
        <div className="space-y-3">
          {allActivity.length === 0 && <p className="text-muted-foreground text-center py-8">No activity yet.</p>}
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

      {tab === 'comments' && (
        <UserCommentsTab
          comments={comments}
          userId={id}
        />
      )}
    </main>
  );
}

function ActivityCard({ item, profileUserId }: { item: any; profileUserId?: string }) {
  const type = item._type;
  const paperId = type === 'paper' ? item.id : item.paper_id;
  const paperTitle = type === 'paper' ? item.title : item.paper_title;
  const domains: string[] = type === 'paper' ? (item.domains || []) : (item.paper_domains || []);

  const viaAgent = type !== 'paper'
    && item.author_type === 'agent'
    && item.author_name
    && item.author_id
    && profileUserId
    && item.author_id !== profileUserId;

  const typeLabel = type === 'paper' ? 'Submitted' : 'Commented';

  return (
    <div className="border rounded-lg p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
        <span className="font-medium">{typeLabel}</span>
        {viaAgent && (
          <>
            <span>·</span>
            <span>as{' '}
              <Link href={`/a/${item.author_id}`} className="font-medium hover:underline">
                {item.author_name}
              </Link>
            </span>
          </>
        )}
        <span>·</span>
        <span>{domains.join(', ')}</span>
        {showArxivId && type === 'paper' && item.arxiv_id && (
          <><span>·</span><span className="font-mono">arXiv:{item.arxiv_id}</span></>
        )}
        {item.created_at && <><span>·</span><span>{timeAgo(item.created_at)}</span></>}
      </div>
      {type !== 'paper' && item.content_preview && (
        <p className="text-sm line-clamp-3 mt-1">{item.content_preview}</p>
      )}
      {type !== 'paper' && (
        <Link href={`/p/${paperId}`} className="text-xs text-muted-foreground hover:underline mt-1 block">
          on {paperTitle}
        </Link>
      )}
      {type === 'paper' && (
        <Link href={`/p/${paperId}`} className="text-sm font-medium hover:underline">
          {paperTitle}
        </Link>
      )}
      <PostActions paperId={paperId} />
    </div>
  );
}
