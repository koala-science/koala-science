import { getApiUrl } from '@/lib/api';
import { Paper } from '@/components/feed/paper-feed';
import { InfinitePaperFeed } from '@/components/feed/infinite-paper-feed';
import { DomainInfoCard } from '@/components/domain/domain-info-card';
import { PageShell, PageTitle } from '@/components/shared/page';
import { EmptyState, ErrorState } from '@/components/shared/state';

interface SearchParams {
  view?: string;
}

export default async function DomainHub({ params, searchParams }: { params: { domain: string }; searchParams: SearchParams }) {
  const apiUrl = getApiUrl();
  const domainName = `d/${decodeURIComponent(params.domain)}`;
  const view = searchParams.view || 'card';

  let papers: Paper[] = [];
  let domainInfo: { id: string; name: string; description: string; paper_count?: number } | null = null;
  let papersFailed = false;
  let failed = false;

  try {
    const [papersRes, domainRes] = await Promise.all([
      fetch(`${apiUrl}/papers/?domain=${encodeURIComponent(domainName)}`, { cache: 'no-store' }),
      fetch(`${apiUrl}/domains/${encodeURIComponent(domainName)}`, { cache: 'no-store' }),
    ]);

    if (papersRes.ok) papers = await papersRes.json();
    else papersFailed = true;
    if (domainRes.ok) domainInfo = await domainRes.json();
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error("Failed to fetch domain data:", error);
    failed = true;
  }

  if (failed) {
    return (
      <PageShell>
        <PageTitle>{domainName}</PageTitle>
        <ErrorState description="This domain could not be loaded. Try again in a moment." />
      </PageShell>
    );
  }

  return (
    <PageShell>
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
        <>
          <PageTitle>{domainName}</PageTitle>
          <EmptyState title="Domain not found" className="mb-6 py-6" />
        </>
      )}

      <section aria-label={`${domainName} Feed`} className="space-y-6">
        {papersFailed ? (
          <ErrorState description="The papers in this domain could not be loaded. Try again in a moment." />
        ) : (
          <InfinitePaperFeed
            initialPapers={papers}
            fetchPath={`/papers/?${new URLSearchParams({ domain: domainName }).toString()}`}
            view={view}
            emptyTitle={`No papers in ${domainName} yet`}
          />
        )}
      </section>
    </PageShell>
  );
}
