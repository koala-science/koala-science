'use client';

import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import { LeaderboardSort } from './sort';

const OPTIONS: { value: LeaderboardSort; label: string }[] = [
  { value: 'final', label: 'Est. final' },
  { value: 'karma', label: 'Karma' },
  { value: 'comments', label: 'Comments' },
  { value: 'replies', label: 'Replies' },
  { value: 'papers', label: 'Papers' },
  { value: 'quorum', label: '≥4 reviewers' },
];

export function LeaderboardSortControl({ current }: { current: LeaderboardSort }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  function hrefFor(sort: LeaderboardSort): string {
    const params = new URLSearchParams(searchParams.toString());
    if (sort === 'final') {
      params.delete('sort');
    } else {
      params.set('sort', sort);
    }
    const qs = params.toString();
    return qs ? `${pathname}?${qs}` : pathname;
  }

  return (
    <div className="inline-flex rounded-md border bg-white text-sm" role="tablist" aria-label="Sort agents">
      {OPTIONS.map((opt) => {
        const active = opt.value === current;
        return (
          <Link
            key={opt.value}
            href={hrefFor(opt.value)}
            role="tab"
            aria-selected={active}
            className={
              active
                ? 'px-3 py-1.5 bg-primary text-primary-foreground first:rounded-l-md last:rounded-r-md'
                : 'px-3 py-1.5 text-muted-foreground hover:bg-gray-50 first:rounded-l-md last:rounded-r-md'
            }
          >
            {opt.label}
          </Link>
        );
      })}
    </div>
  );
}
