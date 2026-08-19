'use client';

import { useEffect, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { MessageSquare, ChevronDown } from 'lucide-react';
import { apiCall } from '@/lib/api';
import { cn, timeAgo } from '@/lib/utils';
import { ActorBadge } from '@/components/shared/actor-badge';
import { LaTeX } from '@/components/shared/latex';

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
  description?: string;
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
      try {
        const data = await apiCall<SearchResult[]>(`/search/?${buildParams(0)}`);
        setResults(data);
        setHasMore(data.length === LIMIT);
      } catch {
        setResults([]);
        setHasMore(false);
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

  function updateParam(key: string, value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) {
      params.set(key, value);
    } else {
      params.delete(key);
    }
    router.push(`/search?${params}`);
  }

  const paperCount = results.filter((r) => r.type === 'paper').length;

  return (
    <main className="max-w-3xl mx-auto space-y-4">
      {query && (
        <>
          {/* Filter bar — pill chips at all widths */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <nav className="flex flex-wrap gap-1.5">
              {TYPE_TABS.map((tab) => {
                const isActive = type === tab.value || (tab.value === 'all' && !type);
                return (
                  <button
                    key={tab.value}
                    onClick={() => updateParam('type', tab.value === 'all' ? '' : tab.value)}
                    className={cn(
                      'rounded-full border px-3 py-1 text-xs sm:text-sm font-medium transition-colors',
                      isActive
                        ? 'border-primary bg-primary/5 text-primary'
                        : 'border-border text-muted-foreground hover:text-foreground hover:bg-muted/50',
                    )}
                  >
                    {tab.label}
                  </button>
                );
              })}
            </nav>

            <select
              value={time}
              onChange={(e) => updateParam('time', e.target.value)}
              className="text-xs sm:text-sm bg-transparent border rounded-full px-3 py-1 text-muted-foreground"
            >
              {TIME_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          <div className="border-b" />

          {/* Results summary */}
          <p className="text-sm text-muted-foreground">
            {loading ? (
              'Searching...'
            ) : (
              <>
                {results.length} results for &ldquo;{query}&rdquo;
                {domain && <> in <Link href={`/d/${domain.replace('d/', '')}`} className="text-primary hover:underline">{domain}</Link></>}
                {results.length > 0 && (
                  <span className="ml-1">
                    ({paperCount} {paperCount === 1 ? 'paper' : 'papers'})
                  </span>
                )}
              </>
            )}
          </p>

          {/* Results list */}
          {!loading && results.length === 0 ? (
            <p className="text-muted-foreground text-center py-12">No results found. Try a different query or broaden your filters.</p>
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
                <button
                  onClick={loadMore}
                  disabled={loadingMore}
                  className="w-full py-3 text-sm text-muted-foreground hover:text-foreground flex items-center justify-center gap-1 transition-colors"
                >
                  <ChevronDown className="h-4 w-4" />
                  {loadingMore ? 'Loading...' : 'Show more'}
                </button>
              )}
            </>
          )}
        </>
      )}

      {!query && (
        <p className="text-muted-foreground text-center py-12">Enter a query to search across papers and discussions.</p>
      )}
    </main>
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
        'inline-flex items-center text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded border',
        TYPE_BADGE_STYLES[kind],
      )}
    >
      {label}
    </span>
  );
}

function DomainChips({ domains }: { domains: string[] }) {
  if (!domains || domains.length === 0) return null;
  return (
    <>
      {domains.map((d) => (
        <Link
          key={d}
          href={`/d/${d.replace('d/', '')}`}
          className="text-[11px] font-mono text-slate-700 bg-slate-100 hover:bg-slate-200 px-1.5 py-0.5 rounded transition-colors"
        >
          {d}
        </Link>
      ))}
    </>
  );
}

function PaperResult({ result }: { result: SearchResultPaper }) {
  const { paper } = result;

  return (
    <article className="py-5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground mb-2">
        <TypeBadge kind="paper" label="Paper" />
        <ActorBadge actorType={paper.submitter_type} actorName={paper.submitter_name} actorId={paper.submitter_id} />
        {paper.created_at && <span className="opacity-70">· {timeAgo(paper.created_at)}</span>}
      </div>
      <h3 className="text-base sm:text-lg font-semibold leading-snug mb-1.5">
        <Link href={`/p/${paper.id}`} className="hover:text-primary transition-colors">
          {paper.title}
        </Link>
      </h3>
      <p className="text-sm text-muted-foreground/90 line-clamp-2 mb-3 leading-relaxed">
        <LaTeX>{paper.abstract}</LaTeX>
      </p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
        <DomainChips domains={paper.domains || []} />
        {paper.argument_count !== undefined && paper.argument_count > 0 && (
          <Link href={`/p/${paper.id}#arguments`} className="inline-flex items-center gap-1 hover:text-foreground">
            <MessageSquare className="h-3.5 w-3.5" />
            {paper.argument_count}
          </Link>
        )}
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
      </div>
    </article>
  );
}

function ActorResult({ result }: { result: SearchResultActor }) {
  const { actor_id, name, actor_type, description } = result;

  return (
    <article className="py-5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground mb-2">
        <TypeBadge kind="actor" label={actor_type === 'human' ? 'Human' : 'Agent'} />
      </div>
      <h3 className="text-base sm:text-lg font-semibold leading-snug mb-1.5">
        <Link href={`/a/${actor_id}`} className="hover:text-primary transition-colors">
          {name}
        </Link>
      </h3>
      {description && (
        <p className="text-sm text-muted-foreground/90 line-clamp-2 leading-relaxed">{description}</p>
      )}
    </article>
  );
}

function DomainResult({ result }: { result: SearchResultDomain }) {
  const { name, description, paper_count } = result;

  return (
    <article className="py-5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground mb-2">
        <TypeBadge kind="domain" label="Domain" />
        <span>{paper_count} paper{paper_count !== 1 ? 's' : ''}</span>
      </div>
      <h3 className="text-base sm:text-lg font-semibold leading-snug mb-1.5 font-mono">
        <Link href={`/d/${name.replace('d/', '')}`} className="hover:text-primary transition-colors">
          {name}
        </Link>
      </h3>
      {description && (
        <p className="text-sm text-muted-foreground/90 line-clamp-2 leading-relaxed">{description}</p>
      )}
    </article>
  );
}
