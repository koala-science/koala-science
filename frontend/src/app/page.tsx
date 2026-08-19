import { getApiUrl } from '../lib/api';
import { Paper } from '../components/feed/paper-feed';
import { InfinitePaperFeed } from '../components/feed/infinite-paper-feed';
import { ActivityStrip } from '../components/feed/activity-strip';

interface SearchParams {
  domain?: string;
  view?: string;
}

function feedQuery(domain: string | undefined): URLSearchParams {
  const params = new URLSearchParams();
  if (domain) params.set('domain', domain);
  return params;
}

export default async function PaperDiscoveryFeed({ searchParams }: { searchParams: SearchParams }) {
  const apiUrl = getApiUrl();
  const domain = searchParams.domain;
  const view = searchParams.view || 'card';

  let papers: Paper[] = [];

  try {
    const params = feedQuery(domain);
    params.set('limit', '50');
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
      <div className="mb-4">
        <ActivityStrip />
      </div>
      <section className="space-y-6" role="region" aria-label="Paper Feed">
        <InfinitePaperFeed
          initialPapers={papers}
          fetchPath={`/papers/?${feedQuery(domain).toString()}`}
          view={view}
        />
      </section>
    </main>
  );
}
