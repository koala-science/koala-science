import { getApiUrl } from '@/lib/api';
import { Paper } from '@/components/feed/paper-feed';
import { InfinitePaperFeed } from '@/components/feed/infinite-paper-feed';
import { PaperFeedSortControl, parseSort } from '@/components/feed/paper-feed-sort-control';
import { DomainInfoCard } from '@/components/domain/domain-info-card';

interface SearchParams {
  view?: string;
  sort?: string;
}

export default async function DomainHub({ params, searchParams }: { params: { domain: string }; searchParams: SearchParams }) {
  const apiUrl = getApiUrl();
  const domainName = `d/${decodeURIComponent(params.domain)}`;
  const view = searchParams.view || 'card';
  const sort = parseSort(searchParams.sort);

  let papers: Paper[] = [];
  let domainInfo: { id: string; name: string; description: string; paper_count?: number } | null = null;

  const listParams = new URLSearchParams({ domain: domainName, sort });
  const fetchParams = new URLSearchParams(listParams);
  fetchParams.set('limit', '50');

  try {
    const [papersRes, domainRes] = await Promise.all([
      fetch(`${apiUrl}/papers/?${fetchParams}`, { cache: 'no-store' }),
      fetch(`${apiUrl}/domains/${encodeURIComponent(domainName)}`, { cache: 'no-store' }),
    ]);

    if (papersRes.ok) papers = await papersRes.json();
    if (domainRes.ok) domainInfo = await domainRes.json();
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error("Failed to fetch domain data:", error);
  }

  return (
    <main className="max-w-2xl mx-auto" role="main" aria-label={`Domain Hub: ${domainName}`}>
      {domainInfo ? (
        <div className="mb-6">
          <DomainInfoCard
            id={domainInfo.id}
            name={domainInfo.name}
            description={domainInfo.description}
            paperCount={domainInfo.paper_count ?? papers.length}
          />
        </div>
      ) : (
        <div className="mb-6 rounded-lg border p-4 text-sm text-muted-foreground">
          Domain not found.
        </div>
      )}

      <section role="region" aria-label={`${domainName} Feed`} className="space-y-6">
        <div className="flex justify-end">
          <PaperFeedSortControl current={sort} />
        </div>
        {papers.length === 0 ? (
          <div className="p-8 rounded-lg border text-center text-muted-foreground">
            No papers in {domainName} yet.
          </div>
        ) : (
          <InfinitePaperFeed
            key={sort}
            initialPapers={papers}
            fetchPath={`/papers/?${listParams.toString()}`}
            view={view}
          />
        )}
      </section>
    </main>
  );
}
