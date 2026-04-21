import { getApiUrl } from '@/lib/api';
import { Paper } from '@/components/feed/paper-feed';
import { InfinitePaperFeed } from '@/components/feed/infinite-paper-feed';
import { DomainInfoCard } from '@/components/domain/domain-info-card';

interface SearchParams {
  view?: string;
}

export default async function DomainHub({ params, searchParams }: { params: { domain: string }; searchParams: SearchParams }) {
  const apiUrl = getApiUrl();
  const domainName = `d/${decodeURIComponent(params.domain)}`;
  const view = searchParams.view || 'card';

  let papers: Paper[] = [];
  let domainInfo: { id: string; name: string; description: string; paper_count?: number } | null = null;

  try {
    const [papersRes, domainRes] = await Promise.all([
      fetch(`${apiUrl}/papers/?domain=${encodeURIComponent(domainName)}`, { cache: 'no-store' }),
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
          <section role="region" aria-label={`${domainName} Feed`} className="space-y-6">
            {papers.length === 0 ? (
              <div className="p-8 rounded-lg border text-center text-muted-foreground">
                No papers in {domainName} yet.
              </div>
            ) : (
              <InfinitePaperFeed
                initialPapers={papers}
                fetchPath={`/papers/?${new URLSearchParams({ domain: domainName }).toString()}`}
                view={view}
              />
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
                paperCount={domainInfo.paper_count ?? papers.length}
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
