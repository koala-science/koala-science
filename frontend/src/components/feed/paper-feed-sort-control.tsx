'use client';

import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';

export type PaperSort = 'popular' | 'recent';

export function parseSort(raw: string | undefined): PaperSort {
  return raw === 'recent' ? 'recent' : 'popular';
}

const OPTIONS: { value: PaperSort; label: string }[] = [
  { value: 'popular', label: 'Popular' },
  { value: 'recent', label: 'Recent' },
];

export function PaperFeedSortControl({ current }: { current: PaperSort }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  function hrefFor(sort: PaperSort): string {
    const params = new URLSearchParams(searchParams.toString());
    if (sort === 'popular') {
      params.delete('sort');
    } else {
      params.set('sort', sort);
    }
    const qs = params.toString();
    return qs ? `${pathname}?${qs}` : pathname;
  }

  return (
    <div className="inline-flex rounded-md border bg-white text-sm" role="tablist" aria-label="Sort papers">
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
