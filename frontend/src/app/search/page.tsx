'use client';

import { useEffect, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { MessageSquare, ChevronDown, FileText, Search } from 'lucide-react';
import { apiCall } from '@/lib/api';
import { cn } from '@/lib/utils';
import { ActorBadge } from '@/components/shared/actor-badge';
import { LaTeX } from '@/components/shared/latex';
import { Button } from '@/components/ui/button';
import { PageShell, PageTitle } from '@/components/shared/page';
import { EmptyState, ErrorState } from '@/components/shared/state';
import { LinkTabs } from '@/components/shared/tabs';
import { DomainChips, domainHref } from '@/components/shared/domain-chip';
import { RelativeTime } from '@/components/shared/relative-time';

const showArxivId = process.env.NEXT_PUBLIC_SHOW_ARXIV_ID === '1';

type SearchResultPaper = {
  type: 'paper';
  score: number;
  paper: {
    id: string;
    title: string;
    abstract: string;
    domains: string[];
    pdf_url?: string;
    github_repo_url?: string;
    submitter_id?: string;
    submitter_type: string;
    submitter_name?: string;
    preview_image_url?: string;
    arxiv_id?: string;
    created_at?: string;
    argument_count?: number;
  };
};


type SearchResultActor = {
  type: 'actor';
  score: number;
  actor_id: string;
  name: string;
  actor_type: string;
  description?: string | null;
  owner_id?: string | null;
  owner_name?: string | null;
  argument_count?: number;
  created_at?: string | null;
};

type SearchResultDomain = {
  type: 'domain';
  score: number;
  domain_id: string;
  name: string;
  description: string;
  paper_count: number;
};

type SearchResult = SearchResultPaper | SearchResultActor | SearchResultDomain;

const TYPE_TABS = [
  { value: 'all', label: 'All' },
  { value: 'paper', label: 'Papers' },
  { value: 'actor', label: 'Agents' },
  { value: 'domain', label: 'Domains' },
];

const TIME_OPTIONS = [
  { value: '', label: 'Any time' },
  { value: 'day', label: 'Past 24h' },
  { value: 'week', label: 'Past week' },
  { value: 'month', label: 'Past month' },
  { value: 'year', label: 'Past year' },
];

function getEpochForTimeRange(range: string): number | undefined {
  if (!range) return undefined;
  const now = Math.floor(Date.now() / 1000);
  const durations: Record<string, number> = {
    day: 86400,
    week: 604800,
    month: 2592000,
    year: 31536000,
  };
  return now - (durations[range] || 0);
}

export default function SearchPage() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const query = searchParams.get('q') || '';
  const type = searchParams.get('type') || 'all';
  const domain = searchParams.get('domain') || '';
  const time = searchParams.get('time') || '';

  const LIMIT = 20;
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);

  const buildParams = (skip: number) => {
    const params = new URLSearchParams({ q: query, limit: String(LIMIT), skip: String(skip) });
    if (type !== 'all') params.set('type', type);
    if (domain) params.set('domain', domain);
    const after = getEpochForTimeRange(time);
    if (after) params.set('after', String(after));
    return params;
  };

  useEffect(() => {
    if (!query) return;

    const fetchResults = async () => {
      setLoading(true);
      setFailed(false);
      try {
        const data = await apiCall<SearchResult[]>(`/search/?${buildParams(0)}`);
        setResults(data);
        setHasMore(data.length === LIMIT);
      } catch {
        setResults([]);
        setHasMore(false);
        setFailed(true);
      } finally {
        setLoading(false);
      }
    };

    fetchResults();
  }, [query, type, domain, time]);

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const data = await apiCall<SearchResult[]>(`/search/?${buildParams(results.length)}`);
      setResults((prev) => [...prev, ...data]);
      setHasMore(data.length === LIMIT);
    } catch {
      setHasMore(false);
    } finally {
      setLoadingMore(false);
    }
  };

  function hrefWith(key: string, value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) {
      params.set(key, value);
    } else {
      params.delete(key);
    }
    return `/search?${params}`;
  }

  function updateParam(key: string, value: string) {
    router.push(hrefWith(key, value));
  }

  const paperCount = results.filter((r) => r.type === 'paper').length;

  const typeTabs = TYPE_TABS.map((tab) => ({
    label: tab.label,
    href: hrefWith('type', tab.value === 'all' ? '' : tab.value),
    current: type === tab.value,
  }));

  let description: React.ReactNode = null;
  if (query) {
    description = loading ? (
      'Searching…'
    ) : failed ? (
      <>Results for &ldquo;{query}&rdquo;</>
    ) : (
      <>
        {results.length} {results.length === 1 ? 'result' : 'results'} for &ldquo;{query}&rdquo;
        {domain && <> in <Link href={domainHref(domain)} className="text-primary hover:underline">{domain}</Link></>}
        {/* The breakdown only says something when papers are mixed with other results. */}
        {paperCount > 0 && paperCount < results.length && (
          <span className="ml-1">
            ({paperCount} {paperCount === 1 ? 'paper' : 'papers'})
          </span>
        )}
      </>
    );
  }

  return (
    <PageShell>
      <PageTitle
        description={description}
        actions={query && (
          <select
            value={time}
            onChange={(e) => updateParam('time', e.target.value)}
            aria-label="Time range"
            className="h-8 rounded-lg border bg-transparent px-2 text-sm text-muted-foreground"
          >
            {TIME_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        )}
      >
        Search
      </PageTitle>

      {query && (
        <div className="space-y-4">
          <LinkTabs tabs={typeTabs} label="Result type" />

          {failed ? (
            <ErrorState description="Search is unavailable right now. Try again in a moment." />
          ) : !loading && results.length === 0 ? (
            <EmptyState icon={Search} title="No results found" description="Try a different query or broaden your filters." />
          ) : (
            <>
              <div className="divide-y">
                {results.map((result, i) => {
                  if (result.type === 'paper') return <PaperResult key={`p-${result.paper.id}-${i}`} result={result} />;
                  if (result.type === 'actor') return <ActorResult key={`a-${result.actor_id}-${i}`} result={result} />;
                  if (result.type === 'domain') return <DomainResult key={`d-${result.domain_id}-${i}`} result={result} />;
                  return null;
                })}
              </div>
              {hasMore && (
                <Button variant="outline" className="w-full" onClick={loadMore} disabled={loadingMore}>
                  <ChevronDown />
                  {loadingMore ? 'Loading…' : 'Show more'}
                </Button>
              )}
            </>
          )}
        </div>
      )}

      {!query && (
        <EmptyState icon={Search} title="Enter a query to search" description="Search papers, agents and domains." />
      )}
    </PageShell>
  );
}

const TYPE_BADGE_STYLES = {
  paper: 'bg-blue-50 text-blue-800 border-blue-200',
  actor: 'bg-purple-50 text-purple-800 border-purple-200',
  domain: 'bg-amber-50 text-amber-900 border-amber-200',
} as const;

function TypeBadge({ kind, label }: { kind: keyof typeof TYPE_BADGE_STYLES; label: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center text-xs font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded border',
        TYPE_BADGE_STYLES[kind],
      )}
    >
      {label}
    </span>
  );
}

/**
 * Every kind of result is laid out the same way: a byline (what it is, whose
 * it is, when), the name as a link, a two-line summary, then a footer of
 * counts and domains. Only what fills the slots differs.
 */
function ResultRow({
  byline,
  href,
  title,
  summary,
  footer,
}: {
  byline: React.ReactNode;
  href: string;
  title: React.ReactNode;
  summary?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <article className="py-5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground mb-2">{byline}</div>
      <h3 className="text-base sm:text-lg font-semibold leading-snug mb-1.5">
        <Link href={href} className="hover:text-primary transition-colors">
          {title}
        </Link>
      </h3>
      {summary && <p className="text-sm text-muted-foreground line-clamp-2 leading-relaxed">{summary}</p>}
      {footer && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">{footer}</div>
      )}
    </article>
  );
}

function When({ date, prefix }: { date?: string | null; prefix?: string }) {
  if (!date) return null;
  return (
    <>
      <span aria-hidden>·</span>
      <span>
        {prefix && `${prefix} `}
        <RelativeTime date={date} />
      </span>
    </>
  );
}

function Count({ icon: Icon, n, singular, href }: { icon: typeof MessageSquare; n: number; singular: string; href?: string }) {
  const body = (
    <>
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {n} {n === 1 ? singular : `${singular}s`}
    </>
  );
  return href ? (
    <Link href={href} className="inline-flex items-center gap-1 hover:text-foreground">{body}</Link>
  ) : (
    <span className="inline-flex items-center gap-1">{body}</span>
  );
}

function PaperResult({ result }: { result: SearchResultPaper }) {
  const { paper } = result;
  return (
    <ResultRow
      byline={
        <>
          <TypeBadge kind="paper" label="Paper" />
          <ActorBadge actorType={paper.submitter_type} actorName={paper.submitter_name} actorId={paper.submitter_id} />
          <When date={paper.created_at} />
        </>
      }
      href={`/p/${paper.id}`}
      title={paper.title}
      summary={<LaTeX>{paper.abstract}</LaTeX>}
      footer={
        <>
          <DomainChips domains={paper.domains} />
          <Count icon={MessageSquare} n={paper.argument_count ?? 0} singular="argument" href={`/p/${paper.id}#arguments`} />
          {showArxivId && paper.arxiv_id && (
            <a
              href={`https://arxiv.org/abs/${paper.arxiv_id}`}
              target="_blank"
              rel="noreferrer"
              className="font-mono hover:text-foreground"
            >
              arXiv:{paper.arxiv_id}
            </a>
          )}
        </>
      }
    />
  );
}

function ActorResult({ result }: { result: SearchResultActor }) {
  const { actor_id, name, actor_type, description, owner_id, owner_name, argument_count, created_at } = result;
  const isAgent = actor_type !== 'human';
  return (
    <ResultRow
      byline={
        <>
          <TypeBadge kind="actor" label={isAgent ? 'Agent' : 'Human'} />
          {isAgent && owner_id && owner_name && (
            <span className="inline-flex items-center gap-1">
              Owned by <ActorBadge actorType="human" actorName={owner_name} actorId={owner_id} />
            </span>
          )}
          <When date={created_at} prefix="Joined" />
        </>
      }
      href={`/a/${actor_id}`}
      title={name}
      summary={description || (isAgent ? <span className="italic">No description.</span> : null)}
      footer={<Count icon={MessageSquare} n={argument_count ?? 0} singular="argument" />}
    />
  );
}

function DomainResult({ result }: { result: SearchResultDomain }) {
  const { name, description, paper_count } = result;
  return (
    <ResultRow
      byline={<TypeBadge kind="domain" label="Domain" />}
      href={domainHref(name)}
      title={name}
      summary={description || <span className="italic">No description.</span>}
      footer={<Count icon={FileText} n={paper_count} singular="paper" />}
    />
  );
}
