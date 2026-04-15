'use client';

import { useState, useMemo } from 'react';
import Link from 'next/link';
import { Info, ChevronRight, ChevronLeft, ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';
import { cn } from '@/lib/utils';

const PAGE_SIZE = 25;

export interface Algorithm {
  name: string;
  label: string;
  description: string;
  degenerate: boolean;
}

export interface RankingEntry {
  id: string;
  title: string;
  url: string;
  ranks: Record<string, number | null>;
  outliers: string[];
}

interface RankingMethodsSectionProps {
  algorithms: Algorithm[];
  papers: RankingEntry[];
  totalPapers: number;
}

type SortDir = 'asc' | 'desc';

function rankTierClass(rank: number | null, total: number): string {
  if (rank === null) return 'bg-muted text-foreground';
  const third = total / 3;
  if (rank <= third) return 'bg-green-50 text-green-800';
  if (rank <= third * 2) return 'bg-muted text-foreground';
  return 'bg-red-50 text-red-800';
}

export function RankingMethodsSection({
  algorithms,
  papers,
  totalPapers,
}: RankingMethodsSectionProps) {
  const active = algorithms.filter((a) => !a.degenerate);
  const defaultSort = active.find((a) => a.name === 'weighted_log')?.name ?? active[0]?.name ?? '';

  const [sortCol, setSortCol] = useState<string>(defaultSort);
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [page, setPage] = useState(0);

  function handleHeaderClick(col: string) {
    if (col === sortCol) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortCol(col);
      setSortDir('asc');
    }
    setPage(0);
  }

  const sorted = useMemo(
    () =>
      [...papers].sort((a, b) => {
        const ra = a.ranks[sortCol] ?? Infinity;
        const rb = b.ranks[sortCol] ?? Infinity;
        return sortDir === 'asc' ? ra - rb : rb - ra;
      }),
    [papers, sortCol, sortDir],
  );

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const paged = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  function SortIcon({ col }: { col: string }) {
    if (col !== sortCol) return <ArrowUpDown className="inline h-3 w-3 ml-1 opacity-50" />;
    return sortDir === 'asc'
      ? <ArrowUp className="inline h-3 w-3 ml-1" />
      : <ArrowDown className="inline h-3 w-3 ml-1" />;
  }

  return (
    <details className="group rounded-lg border border-border bg-muted/30 mb-4 [&>summary::-webkit-details-marker]:hidden">
      <summary className="flex items-center gap-2 px-4 py-2.5 cursor-pointer text-sm font-medium text-muted-foreground hover:text-foreground transition-colors select-none list-none">
        <Info className="h-4 w-4 shrink-0" />
        <span className="flex-1">Do ranking methods agree?</span>
        <span className="text-xs font-normal mr-2">
          {totalPapers} papers · {active.length} algorithms
        </span>
        <ChevronRight className="h-4 w-4 shrink-0 transition-transform group-open:rotate-90" />
      </summary>

      <div className="px-4 pb-4 pt-2 flex flex-col gap-4 text-sm text-muted-foreground leading-relaxed">
        <p>
          Five algorithms rank the same papers. Where they agree, the ranking is robust. Where they
          diverge, the choice of scoring philosophy matters more than the data.
        </p>

        <ul className="flex flex-col gap-1.5">
          {algorithms.map((alg) => (
            <li key={alg.name}>
              <span className="font-medium text-foreground">{alg.label}</span>
              {alg.degenerate && (
                <span className="ml-1 text-xs text-muted-foreground">(degenerate — excluded from table)</span>
              )}
              {': '}
              {alg.description}
            </li>
          ))}
        </ul>

        <div className="flex items-center gap-4 text-xs">
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 rounded-sm bg-green-100 border border-green-300" />
            top third
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 rounded-sm bg-muted border border-border" />
            middle
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 rounded-sm bg-red-100 border border-red-300" />
            bottom third
          </span>
          <span className="flex items-center gap-1">
            <span className="font-bold text-foreground">bold</span>
            &nbsp;= outlier (&gt;30% deviation)
          </span>
        </div>

        <div className="overflow-x-auto scrollbar-thin">
          <table className="min-w-[640px] w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-2 pr-3 font-medium text-foreground">Paper</th>
                {active.map((alg) => (
                  <th
                    key={alg.name}
                    className="text-center py-2 px-2 font-medium text-foreground cursor-pointer hover:text-foreground/80 whitespace-nowrap"
                    onClick={() => handleHeaderClick(alg.name)}
                  >
                    {alg.label}
                    <SortIcon col={alg.name} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {paged.map((paper) => (
                <tr key={paper.id} className="border-b border-border/50 hover:bg-muted/40">
                  <td className="py-1.5 pr-3 max-w-[260px]">
                    <Link
                      href={`/paper/${paper.id}`}
                      className="hover:underline text-foreground line-clamp-2"
                    >
                      {paper.title}
                    </Link>
                  </td>
                  {active.map((alg) => {
                    const rank = paper.ranks[alg.name] ?? null;
                    const isOutlier = paper.outliers.includes(alg.name);
                    return (
                      <td key={alg.name} className="text-center py-1.5 px-2">
                        {rank !== null ? (
                          <span
                            className={cn(
                              'inline-block rounded px-1.5 py-0.5 text-xs',
                              rankTierClass(rank, totalPapers),
                              isOutlier && 'font-bold text-base'
                            )}
                          >
                            #{rank}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {totalPages > 1 && (
          <div className="flex items-center justify-between pt-2 text-xs text-muted-foreground">
            <span>
              {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, sorted.length)} of {sorted.length} papers
            </span>
            <div className="flex items-center gap-1">
              <button
                className="px-2 py-1 rounded hover:bg-muted disabled:opacity-30 disabled:cursor-default"
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              <span>{page + 1} / {totalPages}</span>
              <button
                className="px-2 py-1 rounded hover:bg-muted disabled:opacity-30 disabled:cursor-default"
                disabled={page >= totalPages - 1}
                onClick={() => setPage((p) => p + 1)}
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>
    </details>
  );
}
