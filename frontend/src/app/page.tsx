import { getApiUrl } from '../lib/api';
import { Paper } from '../components/feed/paper-feed';
import { InfinitePaperFeed } from '../components/feed/infinite-paper-feed';
import { FeedSortControls } from '../components/feed/feed-sort-controls';

interface SearchParams {
  sort?: string;
  domain?: string;
  view?: string;
}

export default async function PaperDiscoveryFeed({ searchParams }: { searchParams: SearchParams }) {
  const apiUrl = getApiUrl();
  const sort = searchParams.sort || 'new';
  const domain = searchParams.domain;
  const view = searchParams.view || 'card';

  let papers: Paper[] = [];

  try {
    const params = new URLSearchParams({ sort, limit: '20' });
    if (domain) params.set('domain', domain);

    const papersRes = await fetch(`${apiUrl}/papers/?${params}`, { cache: 'no-store' });
    if (papersRes.ok) papers = await papersRes.json();
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error("Failed to fetch data:", error);
  }

  return (
    <main className="max-w-2xl mx-auto" role="main" aria-label="Paper Discovery Feed">
      <FeedSortControls currentSort={sort} currentDomain={domain} currentView={view} />
      <section className="space-y-6" role="region" aria-label="Paper Feed">
        <InfinitePaperFeed
          initialPapers={papers}
          fetchPath={`/papers/?${new URLSearchParams({ sort, ...(domain ? { domain } : {}) }).toString()}`}
          view={view}
        />
      </section>
    </main>
  );
}
