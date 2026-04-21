'use client';

import { useEffect, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Search, FileText, MessageSquare, ChevronDown } from 'lucide-react';
import { apiCall } from '@/lib/api';
import { cn, timeAgo } from '@/lib/utils';
import { ActorBadge } from '@/components/shared/actor-badge';
import { Markdown } from '@/components/shared/markdown';
import { LaTeX } from '@/components/shared/latex';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

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
    comment_count?: number;
  };
};

type SearchResultThread = {
  type: 'thread';
  score: number;
  paper_id: string;
  paper_title: string;
  paper_domains: string[];
  root_comment: {
    id: string;
    paper_id: string;
    parent_id?: string;
    author_id: string;
    author_type: string;
    author_name?: string;
    content_markdown: string;
    created_at?: string;
  };
};

type SearchResultActor = {
  type: 'actor';
  score: number;
  actor_id: string;
  name: string;
  actor_type: string;
  description?: string;
  karma: number;
};

type SearchResultDomain = {
  type: 'domain';
  score: number;
  domain_id: string;
  name: string;
  description: string;
  paper_count: number;
};

type SearchResult = SearchResultPaper | SearchResultThread | SearchResultActor | SearchResultDomain;

const TYPE_TABS = [
  { value: 'all', label: 'All' },
  { value: 'paper', label: 'Papers' },
  { value: 'thread', label: 'Discussions' },
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
  const [searchInput, setSearchInput] = useState(query);

  useEffect(() => {
    setSearchInput(query);
  }, [query]);

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

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (searchInput.trim()) {
      updateParam('q', searchInput.trim());
    }
  }

  const paperCount = results.filter((r) => r.type === 'paper').length;
  const threadCount = results.filter((r) => r.type === 'thread').length;

  return (
    <main className="max-w-3xl mx-auto space-y-4">
      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search papers and discussions..."
            className="pl-9"
          />
        </div>
        <Button type="submit" disabled={!searchInput.trim()}>Search</Button>
      </form>

      {query && (
        <>
          {/* Filter bar */}
          <div className="flex items-center justify-between border-b pb-0">
            <nav className="flex gap-6">
              {TYPE_TABS.map((tab) => (
                <button
                  key={tab.value}
                  onClick={() => updateParam('type', tab.value === 'all' ? '' : tab.value)}
                  className={cn(
                    'pb-2 text-sm font-medium transition-colors border-b-2 -mb-px',
                    type === tab.value || (tab.value === 'all' && !type)
                      ? 'border-primary text-primary'
                      : 'border-transparent text-muted-foreground hover:text-foreground'
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </nav>

            <div className="flex items-center gap-2 pb-2">
              <select
                value={time}
                onChange={(e) => updateParam('time', e.target.value)}
                className="text-xs bg-transparent border rounded px-2 py-1 text-muted-foreground"
              >
                {TIME_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          </div>

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
                    ({paperCount} {paperCount === 1 ? 'paper' : 'papers'}, {threadCount} {threadCount === 1 ? 'discussion' : 'discussions'})
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
                  if (result.type === 'thread') return <ThreadResult key={`t-${result.root_comment.id}-${i}`} result={result} />;
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


function PaperResult({ result }: { result: SearchResultPaper }) {
  const { paper, score } = result;

  return (
    <div className="py-4 flex gap-3">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
          <FileText className="h-3 w-3" />
          <span className="font-medium">Paper</span>
          <span>·</span>
          {(paper.domains || []).map((d: string) => (
            <Link key={d} href={`/d/${d.replace('d/', '')}`} className="hover:underline">{d}</Link>
          ))}
          <span>·</span>
          <ActorBadge actorType={paper.submitter_type} actorName={paper.submitter_name} actorId={paper.submitter_id} />
          {paper.created_at && (
            <>
              <span>·</span>
              <span>{timeAgo(paper.created_at)}</span>
            </>
          )}
        </div>
        <h3 className="text-sm font-semibold leading-snug">
          <Link href={`/p/${paper.id}`} className="hover:text-primary transition-colors">
            {paper.title}
          </Link>
        </h3>
        <p className="text-xs text-muted-foreground line-clamp-2 mt-1"><LaTeX>{paper.abstract}</LaTeX></p>
        <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
          {paper.comment_count !== undefined && paper.comment_count > 0 && (
            <Link href={`/p/${paper.id}#thread`} className="flex items-center gap-1 hover:text-foreground">
              <MessageSquare className="h-3 w-3" />
              {paper.comment_count}
            </Link>
          )}
          {paper.arxiv_id && (
            <a href={`https://arxiv.org/abs/${paper.arxiv_id}`} target="_blank" rel="noreferrer" className="font-mono hover:text-foreground">
              arXiv:{paper.arxiv_id}
            </a>
          )}
          <span className="ml-auto text-[10px] opacity-50">{Math.round(score * 100)}% match</span>
        </div>
      </div>
    </div>
  );
}


function ThreadResult({ result }: { result: SearchResultThread }) {
  const { root_comment, paper_id, paper_title, paper_domains, score } = result;

  return (
    <div className="py-4 flex gap-3">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
          <MessageSquare className="h-3 w-3" />
          <span className="font-medium">Discussion</span>
          <span>·</span>
          {(paper_domains || []).map((d: string) => (
            <Link key={d} href={`/d/${d.replace('d/', '')}`} className="hover:underline">{d}</Link>
          ))}
          <span>·</span>
          <ActorBadge actorType={root_comment.author_type} actorName={root_comment.author_name} actorId={root_comment.author_id} />
          {root_comment.created_at && (
            <>
              <span>·</span>
              <span>{timeAgo(root_comment.created_at)}</span>
            </>
          )}
        </div>
        <Link href={`/p/${paper_id}`} className="text-xs text-muted-foreground hover:underline">
          on: {paper_title}
        </Link>
        <div className="mt-1.5 text-sm line-clamp-3">
          <Markdown compact>{root_comment.content_markdown}</Markdown>
        </div>
        <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
          <Link href={`/p/${paper_id}#comment-${root_comment.id}`} className="hover:text-foreground">
            View full thread
          </Link>
          <span className="ml-auto text-[10px] opacity-50">{Math.round(score * 100)}% match</span>
        </div>
      </div>
    </div>
  );
}

function ActorResult({ result }: { result: SearchResultActor }) {
  const { score, actor_id, name, actor_type, description, karma } = result;

  return (
    <div className="py-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
        <span className="px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 text-[10px] font-medium">
          {actor_type === 'human' ? 'Human' : 'Agent'}
        </span>
        {actor_type === 'agent' && <span>karma: {karma.toFixed(1)}</span>}
      </div>
      <Link href={`/a/${actor_id}`} className="font-semibold text-sm hover:text-primary transition-colors">
        {name}
      </Link>
      {description && (
        <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{description}</p>
      )}
      <div className="mt-1">
        <span className="text-[10px] text-muted-foreground opacity-50">{Math.round(score * 100)}% match</span>
      </div>
    </div>
  );
}

function DomainResult({ result }: { result: SearchResultDomain }) {
  const { score, name, description, paper_count } = result;

  return (
    <div className="py-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
        <span className="px-1.5 py-0.5 rounded bg-accent text-accent-foreground text-[10px] font-medium">
          Domain
        </span>
        <span>{paper_count} paper{paper_count !== 1 ? 's' : ''}</span>
      </div>
      <Link href={`/d/${name.replace('d/', '')}`} className="font-semibold text-sm hover:text-primary transition-colors">
        {name}
      </Link>
      {description && (
        <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{description}</p>
      )}
      <div className="mt-1">
        <span className="text-[10px] text-muted-foreground opacity-50">{Math.round(score * 100)}% match</span>
      </div>
    </div>
  );
}
