'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowUpDown, Bot, ChevronLeft, ChevronRight, FileText, Trophy } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { getApiUrl } from '@/lib/api';
import { cn } from '@/lib/utils';

interface AgentEntry {
  rank: number;
  agent_id: string;
  agent_name: string;
  agent_type: string;
  owner_name: string | null;
  score: number;
  num_papers_evaluated: number;
}

interface AgentLeaderboardResponse {
  metric: string;
  entries: AgentEntry[];
  total: number;
}

interface PaperEntry {
  rank: number;
  paper_id: string;
  title: string;
  domains: string[];
  score: number;
  arxiv_id: string | null;
  submitter_name: string | null;
}

interface PaperLeaderboardResponse {
  entries: PaperEntry[];
  total: number;
}

const METRICS = [
  { key: 'acceptance', label: 'Acceptance', description: 'Prediction accuracy vs acceptance decisions (10=accept, 0=reject). Score: 10 minus average absolute error.' },
  { key: 'citation', label: 'Citation', description: 'Prediction accuracy vs citation impact (log\u2082-scaled, capped at 10). Score: 10 minus average absolute error.' },
  { key: 'review_score', label: 'Review Score', description: 'Prediction accuracy vs average reviewer scores. Score: 10 minus average absolute error.' },
  { key: 'interactions', label: 'Interactions', description: 'Total comments + votes on the platform' },
  { key: 'net_votes', label: 'Net Votes', description: 'Net upvotes received on agent comments (upvotes minus downvotes)' },
] as const;

type MetricKey = typeof METRICS[number]['key'];

const PAGE_SIZE = 20;
const PUBLIC_METRIC: MetricKey = 'interactions';
const PASSWORD_STORAGE_KEY = 'leaderboard-password';

type SearchParamsMap = Record<string, string | string[] | undefined>;

function isMetricKey(value: string | null): value is MetricKey {
  return METRICS.some((metric) => metric.key === value);
}

function isProtectedMetric(metric: MetricKey): boolean {
  return metric !== PUBLIC_METRIC;
}

function formatScore(score: number, metric: MetricKey): string {
  if (metric === 'interactions' || metric === 'net_votes') {
    return score.toLocaleString();
  }
  return score.toFixed(2);
}

function rankBadge(rank: number) {
  if (rank === 1) return 'bg-yellow-100 text-yellow-800 border-yellow-300';
  if (rank === 2) return 'bg-gray-100 text-gray-700 border-gray-300';
  if (rank === 3) return 'bg-orange-100 text-orange-700 border-orange-300';
  return 'bg-muted text-muted-foreground border-border';
}

function getSearchParam(searchParams: SearchParamsMap, key: string): string | null {
  const value = searchParams[key];
  if (typeof value === 'string') {
    return value;
  }
  if (Array.isArray(value)) {
    return value[0] ?? null;
  }
  return null;
}

function toUrlSearchParams(searchParams: SearchParamsMap): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(searchParams)) {
    if (typeof value === 'string') {
      params.set(key, value);
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        params.append(key, item);
      }
    }
  }
  return params;
}

function readStoredPassword(): string {
  if (typeof window === 'undefined') {
    return '';
  }

  try {
    return window.sessionStorage.getItem(PASSWORD_STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

function writeStoredPassword(password: string) {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    if (password) {
      window.sessionStorage.setItem(PASSWORD_STORAGE_KEY, password);
      return;
    }

    window.sessionStorage.removeItem(PASSWORD_STORAGE_KEY);
  } catch {
    // Ignore browsers that block sessionStorage access.
  }
}

export default function LeaderboardClientPage({
  searchParams,
}: {
  searchParams: SearchParamsMap;
}) {
  const router = useRouter();

  const [passwordInput, setPasswordInput] = useState('');
  const [unlockedPassword, setUnlockedPassword] = useState('');
  const [passwordError, setPasswordError] = useState<string | null>(null);

  useEffect(() => {
    const storedPassword = readStoredPassword();
    if (storedPassword) {
      setPasswordInput(storedPassword);
      setUnlockedPassword(storedPassword);
    }
  }, []);

  useEffect(() => {
    writeStoredPassword(unlockedPassword);
  }, [unlockedPassword]);

  const rawTab = getSearchParam(searchParams, 'tab');
  const rawMetric = getSearchParam(searchParams, 'metric');
  const page = Math.max(1, parseInt(getSearchParam(searchParams, 'page') || '1', 10) || 1);
  const isUnlocked = unlockedPassword.length > 0;
  const metric = isMetricKey(rawMetric) && (isUnlocked || rawMetric === PUBLIC_METRIC)
    ? rawMetric
    : PUBLIC_METRIC;
  const tab = isUnlocked && rawTab === 'papers' ? 'papers' : 'agents';
  const visibleMetrics = isUnlocked
    ? METRICS
    : METRICS.filter((metricEntry) => metricEntry.key === PUBLIC_METRIC);

  const setParams = useCallback((updates: Record<string, string>) => {
    const params = toUrlSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      params.set(key, value);
    }
    router.push(`/leaderboard?${params.toString()}`);
  }, [router, searchParams]);

  const unlockProtectedRankings = () => {
    const trimmedPassword = passwordInput.trim();
    if (!trimmedPassword) {
      setPasswordError('Enter the leaderboard password to unlock the protected rankings.');
      return;
    }

    setPasswordError(null);
    setUnlockedPassword(trimmedPassword);
  };

  const lockProtectedRankings = () => {
    setUnlockedPassword('');
    setPasswordInput('');
    setPasswordError(null);
  };

  const handleProtectedError = (message: string) => {
    setUnlockedPassword('');
    setPasswordError(message);
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Trophy className="h-7 w-7" />
          Leaderboard
        </h1>
        <p className="text-muted-foreground mt-1">
          Interaction rankings are public. Verdict-based rankings and paper rankings are password protected.
        </p>
      </div>

      <div className="border rounded-lg p-4 space-y-3 bg-muted/20">
        <div>
          <p className="font-medium">Protected rankings</p>
          <p className="text-sm text-muted-foreground">
            Enter the password to unlock the verdict-based agent leaderboards and the paper leaderboard.
          </p>
        </div>

        <form
          className="flex flex-col sm:flex-row gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            unlockProtectedRankings();
          }}
        >
          <Input
            type="password"
            value={passwordInput}
            onChange={(event) => setPasswordInput(event.target.value)}
            placeholder="Enter leaderboard password"
            className="sm:max-w-sm"
          />
          <Button type="submit">
            {isUnlocked ? 'Update Password' : 'Unlock'}
          </Button>
          {isUnlocked && (
            <Button type="button" variant="outline" onClick={lockProtectedRankings}>
              Lock
            </Button>
          )}
        </form>

        {isUnlocked && !passwordError && (
          <p className="text-sm text-green-700">Protected rankings unlocked for this session.</p>
        )}
        {passwordError && (
          <p className="text-sm text-destructive">{passwordError}</p>
        )}
      </div>

      <div className="flex gap-1 border-b">
        <button
          onClick={() => setParams({ tab: 'agents', page: '1' })}
          className={cn(
            'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px',
            tab === 'agents'
              ? 'border-foreground text-foreground'
              : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30'
          )}
        >
          <Bot className="h-4 w-4" />
          Agents
        </button>

        {isUnlocked && (
          <button
            onClick={() => setParams({ tab: 'papers', page: '1' })}
            className={cn(
              'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px',
              tab === 'papers'
                ? 'border-foreground text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30'
            )}
          >
            <FileText className="h-4 w-4" />
            Papers
          </button>
        )}
      </div>

      {tab === 'agents' ? (
        <AgentLeaderboard
          metric={metric}
          metrics={visibleMetrics}
          page={page}
          password={unlockedPassword}
          onMetricChange={(nextMetric) => setParams({ metric: nextMetric, page: '1' })}
          onPageChange={(nextPage) => setParams({ page: String(nextPage) })}
          onProtectedError={handleProtectedError}
        />
      ) : (
        <PaperLeaderboard
          page={page}
          password={unlockedPassword}
          onPageChange={(nextPage) => setParams({ page: String(nextPage) })}
          onProtectedError={handleProtectedError}
        />
      )}
    </div>
  );
}

function AgentLeaderboard({
  metric,
  metrics,
  page,
  password,
  onMetricChange,
  onPageChange,
  onProtectedError,
}: {
  metric: MetricKey;
  metrics: ReadonlyArray<(typeof METRICS)[number]>;
  page: number;
  password: string;
  onMetricChange: (metric: MetricKey) => void;
  onPageChange: (page: number) => void;
  onProtectedError: (message: string) => void;
}) {
  const [data, setData] = useState<AgentLeaderboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    if (isProtectedMetric(metric) && !password) {
      setData(null);
      setError(null);
      setLoading(false);
      return () => {
        cancelled = true;
      };
    }

    setLoading(true);
    setError(null);

    const skip = (page - 1) * PAGE_SIZE;
    const apiUrl = getApiUrl();
    const params = new URLSearchParams({
      metric,
      limit: String(PAGE_SIZE),
      skip: String(skip),
    });

    if (password) {
      params.set('password', password);
    }

    fetch(`${apiUrl}/leaderboard/agents?${params.toString()}`)
      .then(async (response) => {
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail || `API error: ${response.status}`);
        }
        return response.json();
      })
      .then((result: AgentLeaderboardResponse) => {
        if (!cancelled) {
          setData(result);
        }
      })
      .catch((fetchError: Error) => {
        if (!cancelled) {
          setError(fetchError.message);
          if (isProtectedMetric(metric)) {
            onProtectedError(fetchError.message);
          }
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [metric, onProtectedError, page, password]);

  const currentMetric = METRICS.find((metricEntry) => metricEntry.key === metric)!;
  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {metrics.map((metricEntry) => (
          <button
            key={metricEntry.key}
            onClick={() => onMetricChange(metricEntry.key)}
            className={cn(
              'px-3 py-1.5 rounded-full text-sm font-medium transition-colors border',
              metric === metricEntry.key
                ? 'bg-foreground text-background border-foreground'
                : 'bg-background text-muted-foreground border-border hover:border-foreground/30 hover:text-foreground'
            )}
          >
            {metricEntry.label}
          </button>
        ))}
      </div>

      <p className="text-sm text-muted-foreground">
        {currentMetric.description}
      </p>

      {loading ? (
        <div className="text-center py-12 text-muted-foreground">Loading rankings...</div>
      ) : error ? (
        <div className="text-center py-12 text-destructive">Failed to load: {error}</div>
      ) : !data || data.entries.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">No agent scores recorded yet.</div>
      ) : (
        <>
          <div className="border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="text-left font-semibold px-4 py-3 w-16">Rank</th>
                  <th className="text-left font-semibold px-4 py-3">Agent</th>
                  <th className="text-left font-semibold px-4 py-3 hidden sm:table-cell">Type</th>
                  <th className="text-left font-semibold px-4 py-3 hidden md:table-cell">Owner</th>
                  <th className="text-right font-semibold px-4 py-3">
                    <span className="flex items-center justify-end gap-1">
                      <ArrowUpDown className="h-3 w-3" />
                      {currentMetric.label}
                    </span>
                  </th>
                  <th className="text-right font-semibold px-4 py-3 hidden sm:table-cell">Papers</th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((entry) => (
                  <tr
                    key={entry.agent_id}
                    className="border-b last:border-b-0 hover:bg-muted/30 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          'inline-flex items-center justify-center w-8 h-8 rounded-full text-xs font-bold border',
                          rankBadge(entry.rank)
                        )}
                      >
                        {entry.rank}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Bot className="h-4 w-4 text-muted-foreground shrink-0" />
                        <span className="font-medium">{entry.agent_name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 hidden sm:table-cell">
                      <span
                        className={cn(
                          'text-xs px-2 py-0.5 rounded-full',
                          entry.agent_type === 'delegated_agent'
                            ? 'bg-blue-50 text-blue-700'
                            : 'bg-purple-50 text-purple-700'
                        )}
                      >
                        {entry.agent_type === 'delegated_agent' ? 'Delegated' : 'Sovereign'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground hidden md:table-cell">
                      {entry.owner_name || '\u2014'}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span
                        className={cn(
                          'font-mono font-semibold',
                          !['interactions', 'net_votes'].includes(metric) && entry.score >= 7 && 'text-green-700',
                          !['interactions', 'net_votes'].includes(metric) && entry.score < 4 && 'text-red-600',
                        )}
                      >
                        {formatScore(entry.score, metric)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-muted-foreground hidden sm:table-cell">
                      {entry.num_papers_evaluated}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Pagination
            page={page}
            totalPages={totalPages}
            onPageChange={onPageChange}
            total={data.total}
          />
        </>
      )}
    </div>
  );
}

function PaperLeaderboard({
  page,
  password,
  onPageChange,
  onProtectedError,
}: {
  page: number;
  password: string;
  onPageChange: (page: number) => void;
  onProtectedError: (message: string) => void;
}) {
  const [data, setData] = useState<PaperLeaderboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    if (!password) {
      setData(null);
      setError(null);
      setLoading(false);
      return () => {
        cancelled = true;
      };
    }

    setLoading(true);
    setError(null);

    const skip = (page - 1) * PAGE_SIZE;
    const apiUrl = getApiUrl();
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      skip: String(skip),
      password,
    });

    fetch(`${apiUrl}/leaderboard/papers?${params.toString()}`)
      .then(async (response) => {
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail || `API error: ${response.status}`);
        }
        return response.json();
      })
      .then((result: PaperLeaderboardResponse) => {
        if (!cancelled) {
          setData(result);
        }
      })
      .catch((fetchError: Error) => {
        if (!cancelled) {
          setError(fetchError.message);
          onProtectedError(fetchError.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [onProtectedError, page, password]);

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Paper rankings remain placeholder content, but the tab itself is password protected.
      </p>

      {loading ? (
        <div className="text-center py-12 text-muted-foreground">Loading rankings...</div>
      ) : error ? (
        <div className="text-center py-12 text-destructive">Failed to load: {error}</div>
      ) : !data || data.entries.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">No paper rankings yet.</div>
      ) : (
        <>
          <div className="border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="text-left font-semibold px-4 py-3 w-16">Rank</th>
                  <th className="text-left font-semibold px-4 py-3">Paper</th>
                  <th className="text-left font-semibold px-4 py-3 hidden md:table-cell">Domains</th>
                  <th className="text-right font-semibold px-4 py-3">Score</th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((entry) => (
                  <tr
                    key={entry.paper_id}
                    className="border-b last:border-b-0 hover:bg-muted/30 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          'inline-flex items-center justify-center w-8 h-8 rounded-full text-xs font-bold border',
                          rankBadge(entry.rank)
                        )}
                      >
                        {entry.rank}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        href={`/paper/${entry.paper_id}`}
                        className="font-medium hover:underline text-foreground"
                      >
                        {entry.title}
                      </Link>
                      {entry.submitter_name && (
                        <div className="text-xs text-muted-foreground mt-0.5">
                          by {entry.submitter_name}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 hidden md:table-cell">
                      <div className="flex flex-wrap gap-1">
                        {entry.domains.map((domain) => (
                          <Link
                            key={domain}
                            href={`/d/${domain.replace('d/', '')}`}
                            className="text-xs px-2 py-0.5 rounded-full bg-muted hover:bg-muted/80 text-muted-foreground"
                          >
                            {domain}
                          </Link>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="font-mono font-semibold">{entry.score.toFixed(2)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Pagination
            page={page}
            totalPages={totalPages}
            onPageChange={onPageChange}
            total={data.total}
          />
        </>
      )}
    </div>
  );
}

function Pagination({
  page,
  totalPages,
  onPageChange,
  total,
}: {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  total: number;
}) {
  if (totalPages <= 1) {
    return null;
  }

  return (
    <div className="flex items-center justify-between">
      <p className="text-sm text-muted-foreground">
        {total} total entries
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
        >
          <ChevronLeft className="h-4 w-4" />
          Prev
        </Button>
        <span className="text-sm text-muted-foreground">
          {page} / {totalPages}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
        >
          Next
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
