import { getApiUrl } from '../lib/api';
import { Paper } from '../components/feed/paper-feed';
import { InfinitePaperFeed } from '../components/feed/infinite-paper-feed';
import { PaperFeedSortControl, parseSort } from '../components/feed/paper-feed-sort-control';

interface SearchParams {
  domain?: string;
  view?: string;
  sort?: string;
}

export default async function PaperDiscoveryFeed({ searchParams }: { searchParams: SearchParams }) {
  const apiUrl = getApiUrl();
  const domain = searchParams.domain;
  const view = searchParams.view || 'card';
  const sort = parseSort(searchParams.sort);

  let papers: Paper[] = [];

  try {
    const params = new URLSearchParams({ limit: '50', sort });
    if (domain) params.set('domain', domain);

    const papersRes = await fetch(`${apiUrl}/papers/?${params}`, { cache: 'no-store' });
    if (papersRes.ok) papers = await papersRes.json();
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error("Failed to fetch data:", error);
  }

  const feedParams = new URLSearchParams({ sort });
  if (domain) feedParams.set('domain', domain);

  return (
    <main className="max-w-2xl mx-auto" role="main" aria-label="Paper Discovery Feed">
      <section className="space-y-6" role="region" aria-label="Paper Feed">
        <div className="flex justify-end">
          <PaperFeedSortControl current={sort} />
        </div>
        <InfinitePaperFeed
          key={sort}
          initialPapers={papers}
          fetchPath={`/papers/?${feedParams.toString()}`}
          view={view}
        />
      </section>
    </main>
  );
}
