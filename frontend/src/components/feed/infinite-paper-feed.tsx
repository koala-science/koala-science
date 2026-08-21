'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { PaperFeed, Paper } from './paper-feed';
import { apiCall } from '@/lib/api';

interface InfinitePaperFeedProps {
  initialPapers: Paper[];
  fetchPath: string;
  view?: string;
  limit?: number;
}

export function InfinitePaperFeed({
  initialPapers,
  fetchPath,
  view = 'card',
  limit = 20,
}: InfinitePaperFeedProps) {
  const [papers, setPapers] = useState<Paper[]>(initialPapers);
  // Rows consumed from the server, which is not the same as rows rendered: the
  // `active` order re-ranks as arguments land, so a page can re-serve a paper
  // already on screen. Paging on the rendered count would then slide `skip`
  // back over rows already seen, and once a whole page deduped away it would
  // stop advancing entirely and refetch the same page forever.
  const [offset, setOffset] = useState(initialPapers.length);
  const [hasMore, setHasMore] = useState(initialPapers.length >= limit);
  const [loading, setLoading] = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);

  const loadMore = useCallback(async () => {
    if (loading || !hasMore) return;
    setLoading(true);
    try {
      const sep = fetchPath.includes('?') ? '&' : '?';
      const data = await apiCall<Paper[]>(
        `${fetchPath}${sep}limit=${limit}&skip=${offset}`
      );
      setPapers((prev) => {
        const seen = new Set(prev.map((paper) => paper.id));
        return [...prev, ...data.filter((paper) => !seen.has(paper.id))];
      });
      setOffset((consumed) => consumed + data.length);
      setHasMore(data.length >= limit);
    } catch {
      setHasMore(false);
    } finally {
      setLoading(false);
    }
  }, [fetchPath, limit, offset, loading, hasMore]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          loadMore();
        }
      },
      { rootMargin: '200px' }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loadMore]);

  if (papers.length === 0) {
    return null;
  }

  return (
    <div>
      <PaperFeed papers={papers} view={view} />
      {hasMore && (
        <div ref={sentinelRef} className="py-8 text-center text-sm text-muted-foreground">
          {loading ? 'Loading more papers...' : ''}
        </div>
      )}
    </div>
  );
}
