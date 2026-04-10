import { getApiUrl } from '@/lib/api';
import { PaperFeed, Paper } from '@/components/feed/paper-feed';
import { DomainInfoCard } from '@/components/domain/domain-info-card';
import { FeedSortControls } from '@/components/feed/feed-sort-controls';

interface SearchParams {
  sort?: string;
  view?: string;
}

export default async function DomainHub({ params, searchParams }: { params: { domain: string }; searchParams: SearchParams }) {
  const apiUrl = getApiUrl();
  const domainName = `d/${decodeURIComponent(params.domain)}`;
  const sort = searchParams.sort || 'new';
  const view = searchParams.view || 'card';

  let papers: Paper[] = [];
  let domainInfo: { id: string; name: string; description: string } | null = null;

  try {
    const [papersRes, domainRes] = await Promise.all([
      fetch(`${apiUrl}/papers/?domain=${encodeURIComponent(domainName)}&sort=${sort}`, { cache: 'no-store' }),
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
    <main className="max-w-4xl mx-auto" role="main" aria-label={`Domain Hub: ${domainName}`}>
      <div className="flex gap-6">
        {/* Feed column */}
        <div className="flex-1 min-w-0 max-w-2xl">
          <FeedSortControls
            currentSort={sort}
            currentView={view}
            basePath={`/d/${encodeURIComponent(params.domain)}`}
          />

          <section role="region" aria-label={`${domainName} Feed`} className="space-y-6">
            {papers.length === 0 ? (
              <div className="p-8 rounded-lg border text-center text-muted-foreground">
                No papers in {domainName} yet.
              </div>
            ) : (
              <PaperFeed papers={papers} view={view} />
            )}
          </section>
        </div>

        {/* Domain info sidebar — top-aligned with first feed item */}
        <div className="hidden lg:block w-72 shrink-0 pt-10">
          <div className="sticky top-16">
            {domainInfo ? (
              <DomainInfoCard
                id={domainInfo.id}
                name={domainInfo.name}
                description={domainInfo.description}
                paperCount={papers.length}
              />
            ) : (
              <div className="rounded-lg border p-4 text-sm text-muted-foreground">
                Domain not found.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Mobile: domain info above feed */}
      {domainInfo && (
        <div className="lg:hidden mb-6 -order-1">
          <DomainInfoCard
            id={domainInfo.id}
            name={domainInfo.name}
            description={domainInfo.description}
            paperCount={papers.length}
          />
        </div>
      )}
    </main>
  );
}
