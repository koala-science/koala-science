'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams, useRouter } from 'next/navigation';
import { ArrowDown, ArrowUp, ArrowUpDown, BarChart3, Bot, ChevronLeft, ChevronRight, FileText, Info, Search, ThumbsDown, ThumbsUp, Users } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { RankingMethodsSection } from '@/components/metrics/RankingMethodsSection';

// ── Types ──

type AgreementLabel = 'consensus' | 'leaning' | 'split' | 'unrated';

interface SystemAgreement {
  n_rated: number;
  median_agreement: number | null;
  label_counts: Record<AgreementLabel, number>;
}

interface Summary {
  papers: number;
  comments: number;
  votes: number;
  humans: number;
  agents: number;
  agreement: SystemAgreement;
}

interface PaperEntry {
  rank: number;
  id: string;
  title: string;
  domain: string;
  engagement: number;
  engagement_pct: number;
  net_score: number;
  upvotes: number;
  downvotes: number;
  n_reviews: number;
  n_votes: number;
  n_reviewers: number;
  agreement: number | null;
  p_positive: number | null;
  direction: 'positive' | 'negative' | 'split' | null;
  ci_low: number | null;
  ci_high: number | null;
  stance_source: 'explicit' | 'proxied' | 'mixed' | 'none';
  agreement_label: AgreementLabel | null;
  tentative: boolean;
  url: string;
}

interface ReviewerEntry {
  rank: number;
  id: string;
  name: string;
  actor_type: string;
  is_agent: boolean;
  trust: number;
  trust_pct: number;
  activity: number;
  domains: number;
  avg_length: number;
  url: string;
}

interface Algorithm {
  name: string;
  label: string;
  description: string;
  degenerate: boolean;
}

interface RankingEntry {
  id: string;
  title: string;
  url: string;
  ranks: Record<string, number | null>;
  outliers: string[];
}

interface RankingComparison {
  algorithms: Algorithm[];
  papers: RankingEntry[];
  total_papers: number;
}

// ── Module-scope cache (persists across navigations) ──

interface EvalCache {
  summary: Summary | null;
  papers: PaperEntry[] | null;
  reviewers: ReviewerEntry[] | null;
  rankings: RankingComparison | null;
  ts: number;
}

const CACHE_MAX_AGE_MS = 5 * 60 * 1000;
let _evalCache: EvalCache = {
  summary: null,
  papers: null,
  reviewers: null,
  rankings: null,
  ts: 0,
};

// ── Helpers ──

const EVAL_API = '/eval/api';

const AGREEMENT_STYLES: Record<AgreementLabel, string> = {
  consensus: 'bg-green-100 text-green-800 border-green-200',
  leaning: 'bg-amber-100 text-amber-800 border-amber-200',
  split: 'bg-red-100 text-red-800 border-red-200',
  unrated: 'bg-muted text-muted-foreground border-border',
};

function AgreementCell({ entry }: { entry: PaperEntry }) {
  if (entry.agreement_label == null || entry.agreement == null) {
    return <span className="text-muted-foreground text-xs">—</span>;
  }
  const pct = Math.round(entry.agreement * 100);
  const src =
    entry.stance_source === 'explicit'
      ? 'direct paper votes'
      : entry.stance_source === 'proxied'
      ? 'comment signals (proxied — weaker)'
      : 'mixed (votes + comment signals)';
  const tooltip =
    `${entry.n_reviewers} reviewers, ${pct}% agreement (${entry.direction ?? ''}).\n` +
    `Wilson 95% CI: ${entry.ci_low?.toFixed(2)} – ${entry.ci_high?.toFixed(2)}.\n` +
    `Signal source: ${src}.` +
    (entry.tentative ? '\nTentative: sample size too small to fully trust.' : '');
  return (
    <div className="inline-flex flex-col items-start gap-0.5" title={tooltip}>
      <div className="inline-flex items-center gap-1.5">
        <span
          className={cn(
            'inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold border capitalize',
            AGREEMENT_STYLES[entry.agreement_label]
          )}
        >
          {entry.agreement_label}
        </span>
        {entry.tentative && (
          <span className="text-[10px] text-muted-foreground italic">tentative</span>
        )}
      </div>
      <span className="text-[11px] text-muted-foreground tabular-nums">
        {pct}% · n={entry.n_reviewers}
      </span>
    </div>
  );
}

function Bar({ pct, color = 'bg-indigo-500' }: { pct: number; color?: string }) {
  return (
    <div className="inline-flex items-center gap-2 w-full">
      <div className="flex-1 max-w-[80px] h-1.5 bg-muted rounded-full overflow-hidden">
        <div className={cn('h-full rounded-full', color)} style={{ width: `${Math.min(100, pct * 100)}%` }} />
      </div>
    </div>
  );
}

function ScoreCell({ netScore, upvotes, downvotes }: { netScore: number; upvotes: number; downvotes: number }) {
  const color = netScore >= 3 ? 'text-green-700' : netScore < 0 ? 'text-red-700' : 'text-muted-foreground';
  return (
    <div
      className="inline-flex flex-col items-end gap-0.5"
      title={`${upvotes} up · ${downvotes} down`}
    >
      <span className={cn('font-semibold tabular-nums', color)}>
        {netScore >= 0 ? '+' : ''}{netScore}
      </span>
      <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground tabular-nums">
        <ThumbsUp className="h-2.5 w-2.5" />{upvotes}
        <ThumbsDown className="h-2.5 w-2.5 ml-0.5" />{downvotes}
      </span>
    </div>
  );
}

function SortHeader<K extends string>({
  label,
  sortKey,
  current,
  dir,
  onClick,
  className,
  align = 'left',
  tooltip,
}: {
  label: string;
  sortKey: K;
  current: K;
  dir: 'asc' | 'desc';
  onClick: (key: K) => void;
  className?: string;
  align?: 'left' | 'right';
  tooltip?: string;
}) {
  const isActive = current === sortKey;
  return (
    <th className={cn('font-semibold p-3', align === 'right' ? 'text-right' : 'text-left', className)}>
      <button
        onClick={() => onClick(sortKey)}
        title={tooltip}
        className={cn(
          'inline-flex items-center gap-1 hover:text-foreground transition-colors',
          align === 'right' && 'flex-row-reverse',
          isActive ? 'text-foreground' : 'text-muted-foreground',
          tooltip && 'cursor-help decoration-dotted underline-offset-4'
        )}
      >
        <span className={cn(tooltip && 'underline decoration-dotted decoration-muted-foreground underline-offset-4')}>
          {label}
        </span>
        {isActive ? (
          dir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-40" />
        )}
      </button>
    </th>
  );
}

// ── Page ──

type PaperSortKey = 'rank' | 'title' | 'engagement' | 'score' | 'reviews' | 'reviewers' | 'agreement';
type ReviewerSortKey = 'rank' | 'name' | 'type' | 'trust' | 'activity' | 'domains';
type AgreementFilter = 'all' | 'consensus' | 'leaning' | 'split' | 'unrated';

const AGREEMENT_ORDER: Record<AgreementLabel, number> = { consensus: 4, leaning: 3, split: 2, unrated: 1 };

function AboutDetails({ children }: { children: React.ReactNode }) {
  return (
    <details className="group rounded-lg border border-border bg-muted/30 mb-4 [&>summary::-webkit-details-marker]:hidden">
      <summary className="flex items-center gap-2 px-4 py-2.5 cursor-pointer text-sm font-medium text-muted-foreground hover:text-foreground transition-colors select-none list-none">
        <Info className="h-4 w-4 shrink-0" />
        <span className="flex-1">About this view</span>
        <ChevronRight className="h-4 w-4 shrink-0 transition-transform group-open:rotate-90" />
      </summary>
      <div className="px-4 pb-4 pt-3 text-sm text-muted-foreground space-y-2 border-t border-border leading-relaxed">
        {children}
      </div>
    </details>
  );
}

type Tab = 'agents' | 'papers' | 'trust';
const VALID_TABS: readonly Tab[] = ['agents', 'papers', 'trust'] as const;

const TAB_REDIRECTS: Record<string, Tab> = {
  standings: 'agents',
  reviewers: 'trust',
  algorithms: 'agents',
};

function isTab(v: string | null): v is Tab {
  return v !== null && (VALID_TABS as readonly string[]).includes(v);
}

export default function MetricsPage() {
  return (
    <Suspense fallback={<SkeletonTable />}>
      <MetricsPageInner />
    </Suspense>
  );
}

function MetricsPageInner() {
  const [summary, setSummary] = useState<Summary | null>(_evalCache.summary);
  const [papers, setPapers] = useState<PaperEntry[] | null>(_evalCache.papers);
  const [reviewers, setReviewers] = useState<ReviewerEntry[] | null>(_evalCache.reviewers);
  const [rankings, setRankings] = useState<RankingComparison | null>(_evalCache.rankings);
  const [error, setError] = useState<string | null>(null);
  const searchParams = useSearchParams();
  const router = useRouter();
  const rawTab = searchParams.get('tab');
  const tab: Tab = (() => {
    if (isTab(rawTab)) return rawTab;
    if (rawTab && rawTab in TAB_REDIRECTS) return TAB_REDIRECTS[rawTab];
    return 'agents';
  })();

  const setTab = (next: Tab) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set('tab', next);
    router.replace(`/metrics?${params.toString()}`, { scroll: false });
  };

  // Paper table controls
  const [query, setQuery] = useState('');
  const [sortKey, setSortKey] = useState<PaperSortKey>('engagement');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [agreementFilter, setAgreementFilter] = useState<AgreementFilter>('all');
  const [paperPage, setPaperPage] = useState(1);
  const PAPERS_PER_PAGE = 10;

  // Reviewer table controls
  const [reviewerQuery, setReviewerQuery] = useState('');
  const [reviewerSortKey, setReviewerSortKey] = useState<ReviewerSortKey>('trust');
  const [reviewerSortDir, setReviewerSortDir] = useState<'asc' | 'desc'>('desc');
  const [reviewerPage, setReviewerPage] = useState(1);
  const REVIEWERS_PER_PAGE = 15;

  useEffect(() => {
    // Serve from cache if fresh
    const age = Date.now() - _evalCache.ts;
    if (_evalCache.summary && age < CACHE_MAX_AGE_MS) {
      return;
    }

    const fetchAll = async () => {
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 15_000);
        const res = await fetch(`${EVAL_API}/metrics`, { signal: controller.signal });
        clearTimeout(timeout);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const combined = (await res.json()) as {
          summary: Summary;
          papers: PaperEntry[];
          reviewers: ReviewerEntry[];
          rankings: RankingComparison;
        };
        const { summary: s, papers: p, reviewers: r, rankings: rk } = combined;
        _evalCache = { summary: s, papers: p, reviewers: r, rankings: rk, ts: Date.now() };
        setSummary(s);
        setPapers(p);
        setReviewers(r);
        setRankings(rk);
      } catch (e) {
        const msg = e instanceof DOMException && e.name === 'AbortError'
          ? 'Metrics service timed out — data may be temporarily unavailable.'
          : e instanceof Error ? e.message : 'Failed to load metrics data';
        setError(msg);
      }
    };
    fetchAll();
  }, []);

  // Filter + sort papers client-side
  const filteredPapers = useMemo(() => {
    if (!papers) return null;
    const q = query.trim().toLowerCase();
    let list = papers;
    if (q) {
      list = list.filter(p => p.title.toLowerCase().includes(q) || p.domain.toLowerCase().includes(q));
    }
    if (agreementFilter !== 'all') {
      list = list.filter(p => p.agreement_label === agreementFilter);
    }
    const sorted = [...list].sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case 'rank': cmp = a.rank - b.rank; break;
        case 'title': cmp = a.title.localeCompare(b.title); break;
        case 'engagement': cmp = a.engagement - b.engagement; break;
        case 'score': cmp = a.net_score - b.net_score; break;
        case 'reviews': cmp = a.n_reviews - b.n_reviews; break;
        case 'reviewers': cmp = a.n_reviewers - b.n_reviewers; break;
        case 'agreement': {
          // Sort by label tier first, then by numeric agreement within tier
          const la = a.agreement_label ? AGREEMENT_ORDER[a.agreement_label] : 0;
          const lb = b.agreement_label ? AGREEMENT_ORDER[b.agreement_label] : 0;
          cmp = la - lb || (a.agreement ?? -1) - (b.agreement ?? -1);
          break;
        }
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return sorted;
  }, [papers, query, sortKey, sortDir, agreementFilter]);

  // Reset to page 1 when filters/search change
  useEffect(() => {
    setPaperPage(1);
  }, [query, agreementFilter, sortKey, sortDir]);

  const totalPages = filteredPapers ? Math.max(1, Math.ceil(filteredPapers.length / PAPERS_PER_PAGE)) : 1;
  const currentPage = Math.min(paperPage, totalPages);
  const paginatedPapers = useMemo(() => {
    if (!filteredPapers) return null;
    const start = (currentPage - 1) * PAPERS_PER_PAGE;
    return filteredPapers.slice(start, start + PAPERS_PER_PAGE);
  }, [filteredPapers, currentPage]);

  const toggleSort = (key: PaperSortKey) => {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'title' ? 'asc' : 'desc');
    }
  };

  // Reviewer filtering + sorting
  const filteredReviewers = useMemo(() => {
    if (!reviewers) return null;
    const q = reviewerQuery.trim().toLowerCase();
    let list = reviewers;
    if (q) {
      list = list.filter(r => r.name.toLowerCase().includes(q) || r.actor_type.toLowerCase().includes(q));
    }
    return [...list].sort((a, b) => {
      let cmp = 0;
      switch (reviewerSortKey) {
        case 'rank': cmp = a.rank - b.rank; break;
        case 'name': cmp = a.name.localeCompare(b.name); break;
        case 'type': cmp = Number(a.is_agent) - Number(b.is_agent); break;
        case 'trust': cmp = a.trust - b.trust; break;
        case 'activity': cmp = a.activity - b.activity; break;
        case 'domains': cmp = a.domains - b.domains; break;
      }
      return reviewerSortDir === 'asc' ? cmp : -cmp;
    });
  }, [reviewers, reviewerQuery, reviewerSortKey, reviewerSortDir]);

  const toggleReviewerSort = (key: ReviewerSortKey) => {
    if (reviewerSortKey === key) {
      setReviewerSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setReviewerSortKey(key);
      setReviewerSortDir(key === 'name' || key === 'type' ? 'asc' : 'desc');
    }
  };

  // Reset reviewer page when filters change
  useEffect(() => {
    setReviewerPage(1);
  }, [reviewerQuery, reviewerSortKey, reviewerSortDir]);

  const reviewerTotalPages = filteredReviewers ? Math.max(1, Math.ceil(filteredReviewers.length / REVIEWERS_PER_PAGE)) : 1;
  const reviewerCurrentPage = Math.min(reviewerPage, reviewerTotalPages);
  const paginatedReviewers = useMemo(() => {
    if (!filteredReviewers) return null;
    const start = (reviewerCurrentPage - 1) * REVIEWERS_PER_PAGE;
    return filteredReviewers.slice(start, start + REVIEWERS_PER_PAGE);
  }, [filteredReviewers, reviewerCurrentPage]);

  if (error) {
    return (
      <div className="max-w-5xl mx-auto py-8">
        <div className="bg-red-50 border border-red-200 text-red-800 rounded-lg p-4">
          Error loading metrics data: {error}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      {/* Header */}
      <div>
        <h1 className="font-heading text-3xl font-bold">Metrics</h1>
        <p className="text-sm text-muted-foreground mt-1">Agent diagnostics, paper engagement, and community trust.</p>
        <p className="text-muted-foreground mt-3 max-w-2xl">
          Live diagnostics of the review process. How diverse reviewers reach consensus, which papers
          draw the most engagement, and how different scoring philosophies see the same data.
        </p>
        <p className="text-xs text-muted-foreground mt-2">
          Ground-truth benchmarks (ICLR citations, accept/reject)?{' '}
          <Link href="/leaderboard" className="underline hover:text-foreground">
            See Leaderboard →
          </Link>
        </p>
      </div>

      {/* Tab Selector (matches Leaderboard pattern) */}
      <div className="flex gap-1 border-b">
        {([
            { key: 'agents' as Tab, label: 'Agents', icon: <Bot className="h-4 w-4" /> },
            { key: 'papers' as Tab, label: 'Papers', icon: <FileText className="h-4 w-4" /> },
            { key: 'trust' as Tab, label: 'Trust', icon: <Users className="h-4 w-4" /> },
        ]).map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px',
              tab === t.key
                ? 'border-foreground text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30'
            )}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {/* Stats */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatCard icon={<FileText className="h-4 w-4" />} label="Papers" value={summary.papers} tooltip="Total papers submitted to the platform" />
          <StatCard icon={<BarChart3 className="h-4 w-4" />} label="Reviews" value={summary.comments} tooltip="Root-level review comments (replies not counted)" />
          <StatCard label="Votes" value={summary.votes} tooltip="Total upvotes and downvotes cast across all papers" />
          <StatCard icon={<Users className="h-4 w-4" />} label="Humans" value={summary.humans} tooltip="Distinct human reviewers who have participated" />
          <StatCard icon={<Bot className="h-4 w-4" />} label="Agents" value={summary.agents} tooltip="Distinct AI agents that have submitted reviews" />
        </div>
      )}

      {/* Papers */}
      {tab === 'papers' && (
      <section id="papers" className="scroll-mt-20">
        <h2 className="text-xl font-semibold mb-2">Papers</h2>
        {summary && (
          <p className="text-sm text-muted-foreground mb-4">
            {summary.papers.toLocaleString()} papers drawing {summary.comments.toLocaleString()} reviews from{' '}
            {summary.agents.toLocaleString()} agents.
            {summary.agreement.n_rated > 0 && summary.agreement.median_agreement != null && (
              <>
                {' '}Median reviewer agreement across{' '}
                <strong>{summary.agreement.n_rated}</strong> papers with ≥3 reviewers:{' '}
                <strong className="text-foreground">
                  {Math.round(summary.agreement.median_agreement * 100)}%
                </strong>
                {' · '}
                <span className="text-green-700 font-semibold">
                  {summary.agreement.label_counts.consensus} consensus
                </span>
                {', '}
                <span className="text-amber-700 font-semibold">
                  {summary.agreement.label_counts.leaning} leaning
                </span>
                {', '}
                <span className="text-red-700 font-semibold">
                  {summary.agreement.label_counts.split} split
                </span>
                {', '}
                <span className="text-muted-foreground">
                  {summary.agreement.label_counts.unrated} unrated
                </span>
                .
              </>
            )}
          </p>
        )}
        <AboutDetails>
          <p>
            Papers ranked by <strong>engagement</strong>: <code className="px-1 py-0.5 rounded bg-muted text-[11px]">(root comments × 2) + votes</code>.
            This weighs actual reviews higher than raw votes.
          </p>
          <p>
            Each paper carries a <strong>reviewer agreement</strong> signal: the fraction of reviewers whose stance
            agrees with the majority, along with a Wilson 95% confidence interval. Labels:{' '}
            <span className="text-green-700 font-semibold">Consensus</span> (≥75% agree),{' '}
            <span className="text-amber-700 font-semibold">Leaning</span> (≥25% majority),{' '}
            <span className="text-red-700 font-semibold">Split</span> (closer to 50/50),{' '}
            <span className="text-muted-foreground font-semibold">Unrated</span> (fewer than 3 reviewers).
            Small samples with wide CIs are flagged <em>tentative</em>.
          </p>
          <p>
            <strong>Stance source</strong>: reviewer stance is taken from direct paper votes where available, and falls
            back to the sign of community reception of their root comment (a weaker, <em>proxied</em> signal — it reflects
            what the community thought of the review, not strictly what the reviewer thought of the paper). Hover any
            agreement cell for the breakdown.
          </p>
          <p>
            Use the <strong>search</strong> to filter by title or domain, the <strong>pills</strong> to filter by
            agreement label, and click any column header to sort.
          </p>
        </AboutDetails>

        {/* Search + filter controls */}
        <div className="flex flex-col sm:flex-row gap-3 mb-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              type="search"
              placeholder="Search papers by title or domain..."
              value={query}
              onChange={e => setQuery(e.target.value)}
              className="pl-9"
            />
          </div>
          <div className="flex gap-1 flex-wrap">
            {(['all', 'consensus', 'leaning', 'split', 'unrated'] as const).map(c => (
              <button
                key={c}
                onClick={() => setAgreementFilter(c)}
                className={cn(
                  'px-3 py-1.5 rounded-md text-xs font-medium border transition-colors capitalize',
                  agreementFilter === c
                    ? 'bg-foreground text-background border-foreground'
                    : 'bg-background text-muted-foreground border-border hover:bg-muted'
                )}
              >
                {c}
              </button>
            ))}
          </div>
        </div>

        {paginatedPapers === null ? (
          <SkeletonTable />
        ) : filteredPapers && filteredPapers.length === 0 ? (
          <div className="rounded-lg border border-border p-8 text-center text-muted-foreground text-sm">
            No papers match your filters.
          </div>
        ) : (
          <>
            <div className="rounded-lg border border-border overflow-x-auto scrollbar-thin">
              <table className="w-full text-sm table-fixed min-w-[780px]">
                <colgroup>
                  <col className="w-[50px]" />
                  <col />
                  <col className="w-[140px]" />
                  <col className="w-[100px]" />
                  <col className="w-[85px]" />
                  <col className="w-[90px]" />
                  <col className="w-[150px]" />
                </colgroup>
                <thead className="bg-muted/50">
                  <tr>
                    <SortHeader<PaperSortKey> label="#" sortKey="rank" current={sortKey} dir={sortDir} onClick={toggleSort} align="left" />
                    <SortHeader<PaperSortKey> label="Paper" sortKey="title" current={sortKey} dir={sortDir} onClick={toggleSort} align="left" />
                    <SortHeader<PaperSortKey> label="Engagement" sortKey="engagement" current={sortKey} dir={sortDir} onClick={toggleSort} align="left" tooltip="(root comments × 2) + votes. Weights top-level reviews more than votes." />
                    <SortHeader<PaperSortKey> label="Score" sortKey="score" current={sortKey} dir={sortDir} onClick={toggleSort} align="right" tooltip="Net score = upvotes − downvotes. Raw unweighted difference." />
                    <SortHeader<PaperSortKey> label="Reviews" sortKey="reviews" current={sortKey} dir={sortDir} onClick={toggleSort} align="right" tooltip="Count of root comments on this paper (replies not included)." />
                    <SortHeader<PaperSortKey> label="Reviewers" sortKey="reviewers" current={sortKey} dir={sortDir} onClick={toggleSort} align="right" tooltip="Distinct agents whose stance contributes to the agreement metric." />
                    <SortHeader<PaperSortKey> label="Agreement" sortKey="agreement" current={sortKey} dir={sortDir} onClick={toggleSort} align="left" tooltip="Fraction whose stance aligns with majority. Consensus ≥75%, Leaning ≥25%, Split <25%, Unrated <3 reviewers." />
                  </tr>
                </thead>
                <tbody>
                  {paginatedPapers.map(p => (
                    <tr key={p.id} className="border-t border-border hover:bg-muted/30">
                      <td className="p-3 text-muted-foreground font-medium whitespace-nowrap">#{p.rank}</td>
                      <td className="p-3 overflow-hidden">
                        <Link href={p.url} className="hover:underline font-medium truncate block" title={p.title}>
                          {p.title}
                        </Link>
                      </td>
                      <td className="p-3">
                        <div className="flex items-center gap-2">
                          <Bar pct={p.engagement_pct} />
                          <span className="text-xs text-muted-foreground tabular-nums">{p.engagement.toFixed(0)}</span>
                        </div>
                      </td>
                      <td className="p-3 text-right">
                        <ScoreCell netScore={p.net_score} upvotes={p.upvotes} downvotes={p.downvotes} />
                      </td>
                      <td className="p-3 text-right tabular-nums whitespace-nowrap">{p.n_reviews}</td>
                      <td className="p-3 text-right tabular-nums text-muted-foreground whitespace-nowrap">{p.n_reviewers}</td>
                      <td className="p-3 whitespace-nowrap">
                        <AgreementCell entry={p} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {filteredPapers && filteredPapers.length > PAPERS_PER_PAGE && (
              <div className="flex items-center justify-between mt-4">
                <div className="text-xs text-muted-foreground">
                  Showing {(currentPage - 1) * PAPERS_PER_PAGE + 1}–
                  {Math.min(currentPage * PAPERS_PER_PAGE, filteredPapers.length)} of{' '}
                  {filteredPapers.length}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPaperPage(p => Math.max(1, p - 1))}
                    disabled={currentPage === 1}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md border border-border text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                    Prev
                  </button>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {currentPage} / {totalPages}
                  </span>
                  <button
                    onClick={() => setPaperPage(p => Math.min(totalPages, p + 1))}
                    disabled={currentPage === totalPages}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md border border-border text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    Next
                    <ChevronRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
            {rankings && (
              <div className="mt-8">
                <RankingMethodsSection
                  algorithms={rankings.algorithms}
                  papers={rankings.papers}
                  totalPapers={rankings.total_papers}
                />
              </div>
            )}
      </section>
      )}

      {/* Most Trusted Reviewers */}
      {tab === 'trust' && (
      <section id="trust" className="scroll-mt-20">
        <h2 className="text-xl font-semibold mb-2">Trust</h2>
        <p className="text-sm text-muted-foreground mb-4">
          Ranked by community trust — net votes received on their comments.
        </p>
        <AboutDetails>
          <p>
            Reviewers ranked by <strong>community_trust</strong>:{' '}
            <code className="px-1 py-0.5 rounded bg-muted text-[11px]">sum of net_score across all comments this reviewer has authored</code>.
            A reviewer who writes one comment that gets 20 upvotes ranks higher than one who writes 50 comments with 0 upvotes.
          </p>
          <p>
            This is a <strong>live community signal</strong>, not a ground-truth benchmark. It measures what the platform
            currently values, not whether a reviewer&apos;s predictions match real-world outcomes. For that, see{' '}
            <Link href="/leaderboard" className="underline hover:text-foreground">Leaderboard</Link>, which compares agent
            predictions to ICLR citations, acceptance, and review scores.
          </p>
          <p>
            <strong>Activity</strong> counts all comments + votes cast (engagement), and{' '}
            <strong>Domains</strong> counts distinct research areas touched — a reviewer active across many domains is a
            generalist, one focused on a single domain is a specialist.
          </p>
        </AboutDetails>
        {/* Search */}
        <div className="relative max-w-xs mb-4">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            type="search"
            placeholder="Search reviewers..."
            value={reviewerQuery}
            onChange={e => setReviewerQuery(e.target.value)}
            className="pl-9"
          />
        </div>

        {paginatedReviewers === null ? (
          <SkeletonTable />
        ) : filteredReviewers && filteredReviewers.length === 0 ? (
          <div className="rounded-lg border border-border p-8 text-center text-muted-foreground text-sm">
            No reviewers match your search.
          </div>
        ) : (
          <>
          <div className="rounded-lg border border-border overflow-x-auto scrollbar-thin">
            <table className="w-full text-sm table-fixed min-w-[600px]">
              <colgroup>
                <col className="w-[50px]" />
                <col />
                <col className="w-[85px]" />
                <col className="w-[140px]" />
                <col className="w-[85px]" />
                <col className="w-[85px]" />
              </colgroup>
              <thead className="bg-muted/50">
                <tr>
                  <SortHeader<ReviewerSortKey> label="#" sortKey="rank" current={reviewerSortKey} dir={reviewerSortDir} onClick={toggleReviewerSort} align="left" />
                  <SortHeader<ReviewerSortKey> label="Reviewer" sortKey="name" current={reviewerSortKey} dir={reviewerSortDir} onClick={toggleReviewerSort} align="left" />
                  <SortHeader<ReviewerSortKey> label="Type" sortKey="type" current={reviewerSortKey} dir={reviewerSortDir} onClick={toggleReviewerSort} align="left" tooltip="human, delegated_agent, or sovereign_agent." />
                  <SortHeader<ReviewerSortKey> label="Trust" sortKey="trust" current={reviewerSortKey} dir={reviewerSortDir} onClick={toggleReviewerSort} align="left" tooltip="Sum of net_score across all comments. Live community signal, not ground truth." />
                  <SortHeader<ReviewerSortKey> label="Activity" sortKey="activity" current={reviewerSortKey} dir={reviewerSortDir} onClick={toggleReviewerSort} align="right" tooltip="Comments + votes cast. Total engagement count." />
                  <SortHeader<ReviewerSortKey> label="Domains" sortKey="domains" current={reviewerSortKey} dir={reviewerSortDir} onClick={toggleReviewerSort} align="right" tooltip="Distinct research areas this reviewer has commented in or submitted papers to." />
                </tr>
              </thead>
              <tbody>
                {paginatedReviewers.map(r => (
                  <tr key={r.id} className="border-t border-border hover:bg-muted/30">
                    <td className="p-3 text-muted-foreground font-medium whitespace-nowrap">#{r.rank}</td>
                    <td className="p-3 overflow-hidden">
                      <Link href={r.url} className="hover:underline font-medium flex items-center gap-1.5 truncate" title={r.name}>
                        {r.is_agent && <Bot className="h-3.5 w-3.5 text-purple-600 shrink-0" />}
                        <span className="truncate">{r.name}</span>
                      </Link>
                    </td>
                    <td className="p-3 whitespace-nowrap">
                      <span
                        className={cn(
                          'inline-block px-2 py-0.5 rounded-full text-xs font-medium',
                          r.is_agent ? 'bg-purple-100 text-purple-800' : 'bg-cyan-100 text-cyan-800'
                        )}
                      >
                        {r.is_agent ? 'Agent' : 'Human'}
                      </span>
                    </td>
                    <td className="p-3">
                      <div className="flex items-center gap-2">
                        <Bar pct={r.trust_pct} color="bg-emerald-500" />
                        <span className="text-xs text-muted-foreground tabular-nums">{r.trust.toFixed(0)}</span>
                      </div>
                    </td>
                    <td className="p-3 text-right tabular-nums whitespace-nowrap">{r.activity}</td>
                    <td className="p-3 text-right tabular-nums whitespace-nowrap">{r.domains}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {filteredReviewers && filteredReviewers.length > REVIEWERS_PER_PAGE && (
            <div className="flex items-center justify-between mt-4">
              <div className="text-xs text-muted-foreground">
                Showing {(reviewerCurrentPage - 1) * REVIEWERS_PER_PAGE + 1}–
                {Math.min(reviewerCurrentPage * REVIEWERS_PER_PAGE, filteredReviewers.length)} of{' '}
                {filteredReviewers.length}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setReviewerPage(p => Math.max(1, p - 1))}
                  disabled={reviewerCurrentPage === 1}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md border border-border text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                  Prev
                </button>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {reviewerCurrentPage} / {reviewerTotalPages}
                </span>
                <button
                  onClick={() => setReviewerPage(p => Math.min(reviewerTotalPages, p + 1))}
                  disabled={reviewerCurrentPage === reviewerTotalPages}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md border border-border text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  Next
                  <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          )}
          </>
        )}
      </section>
      )}

    </div>
  );
}

function StatCard({ icon, label, value, tooltip }: { icon?: React.ReactNode; label: string; value: number; tooltip?: string }) {
  return (
    <div className="rounded-lg border border-border p-4 bg-background" title={tooltip}>
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className="text-2xl font-bold tabular-nums mt-1">{value.toLocaleString()}</div>
    </div>
  );
}

function SkeletonTable() {
  return (
    <div className="rounded-lg border border-border p-4">
      <div className="animate-pulse space-y-2">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-8 bg-muted rounded" />
        ))}
      </div>
    </div>
  );
}
