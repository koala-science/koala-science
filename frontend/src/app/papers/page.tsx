import { getApiUrl } from '../../lib/api';
import { Paper } from '../../components/feed/paper-feed';
import { InfinitePaperFeed } from '../../components/feed/infinite-paper-feed';
import { ActivityStrip } from '../../components/feed/activity-strip';
import { PageShell, PageTitle } from '@/components/shared/page';
import { ErrorState } from '@/components/shared/state';
import { LinkTabs } from '@/components/shared/tabs';

interface SearchParams {
  domain?: string;
  view?: string;
  sort?: string;
}

export const metadata = {
  title: 'Papers — Koala Science',
};

function feedQuery(domain: string | undefined, sort: string): URLSearchParams {
  const params = new URLSearchParams();
  if (domain) params.set('domain', domain);
  params.set('sort', sort);
  return params;
}

export default async function PapersPage({ searchParams }: { searchParams: SearchParams }) {
  const apiUrl = getApiUrl();
  const domain = searchParams.domain;
  const view = searchParams.view || 'card';
  const sort = searchParams.sort === 'new' ? 'new' : 'active';

  let papers: Paper[] = [];
  let failed = false;

  try {
    const params = feedQuery(domain, sort);
    params.set('limit', '50');
    const papersRes = await fetch(`${apiUrl}/papers/?${params}`, { cache: 'no-store' });
    if (papersRes.ok) papers = await papersRes.json();
    else failed = true;
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error("Failed to fetch data:", error);
    failed = true;
  }

  const tabs = [
    { label: 'Active', href: '/papers', action: 'sort-papers-active', current: sort === 'active' },
    { label: 'Newest', href: '/papers?sort=new', action: 'sort-papers-new', current: sort === 'new' },
  ];

  return (
    <PageShell>
      <PageTitle>Papers</PageTitle>
      <div className="mb-4">
        <ActivityStrip />
      </div>
      <LinkTabs tabs={tabs} label="Feed order" className="mb-4" />
      <section className="space-y-6" aria-label="Paper Feed">
        {failed ? (
          <ErrorState description="The papers could not be loaded. Try again in a moment." />
        ) : (
          <InfinitePaperFeed
            initialPapers={papers}
            fetchPath={`/papers/?${feedQuery(domain, sort).toString()}`}
            view={view}
          />
        )}
      </section>
    </PageShell>
  );
}
