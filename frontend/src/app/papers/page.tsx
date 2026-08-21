import Link from 'next/link';
import { getApiUrl } from '../../lib/api';
import { Paper } from '../../components/feed/paper-feed';
import { InfinitePaperFeed } from '../../components/feed/infinite-paper-feed';
import { ActivityStrip } from '../../components/feed/activity-strip';
import { cn } from '@/lib/utils';

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

  try {
    const params = feedQuery(domain, sort);
    params.set('limit', '50');
    const papersRes = await fetch(`${apiUrl}/papers/?${params}`, { cache: 'no-store' });
    if (papersRes.ok) papers = await papersRes.json();
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error("Failed to fetch data:", error);
  }

  const tabs = [
    { label: 'Active', href: '/papers', action: 'sort-papers-active', current: sort === 'active' },
    { label: 'Newest', href: '/papers?sort=new', action: 'sort-papers-new', current: sort === 'new' },
  ];

  return (
    <main className="max-w-2xl mx-auto" role="main" aria-label="Paper Discovery Feed">
      <div className="mb-4">
        <ActivityStrip />
      </div>
      <nav className="mb-4 flex items-center gap-4 text-sm" aria-label="Feed order">
        {tabs.map((tab) => (
          <Link
            key={tab.label}
            href={tab.href}
            className={cn(
              'transition-colors',
              tab.current
                ? 'font-semibold text-foreground'
                : 'text-muted-foreground hover:text-foreground',
            )}
            aria-current={tab.current ? 'page' : undefined}
            data-agent-action={tab.action}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
      <section className="space-y-6" role="region" aria-label="Paper Feed">
        <InfinitePaperFeed
          initialPapers={papers}
          fetchPath={`/papers/?${feedQuery(domain, sort).toString()}`}
          view={view}
        />
      </section>
    </main>
  );
}
