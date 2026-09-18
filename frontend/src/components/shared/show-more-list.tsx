'use client';

import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { apiCall } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/shared/state';

interface ShowMoreListProps<T> {
  /** Initial items (from server-side fetch) */
  initialItems: T[];
  /** API path for fetching more (e.g. "/users/{id}/papers") */
  fetchPath: string;
  /** Items per page */
  limit?: number;
  /** Render each item */
  renderItem: (item: T, index: number) => React.ReactNode;
  /** Empty state message */
  emptyMessage?: string;
}

export function ShowMoreList<T>({
  initialItems,
  fetchPath,
  limit = 20,
  renderItem,
  emptyMessage = 'Nothing here yet',
}: ShowMoreListProps<T>) {
  const [items, setItems] = useState<T[]>(initialItems);
  const [hasMore, setHasMore] = useState(initialItems.length === limit);
  const [loading, setLoading] = useState(false);

  const loadMore = async () => {
    setLoading(true);
    try {
      const sep = fetchPath.includes('?') ? '&' : '?';
      const data = await apiCall<T[]>(`${fetchPath}${sep}limit=${limit}&skip=${items.length}`);
      setItems((prev) => [...prev, ...data]);
      setHasMore(data.length === limit);
    } catch {
      setHasMore(false);
    } finally {
      setLoading(false);
    }
  };

  if (items.length === 0) {
    return <EmptyState title={emptyMessage} />;
  }

  return (
    <div className="space-y-3">
      {items.map((item, i) => renderItem(item, i))}
      {hasMore && (
        <Button variant="outline" className="w-full" onClick={loadMore} disabled={loading}>
          <ChevronDown />
          {loading ? 'Loading…' : 'Show more'}
        </Button>
      )}
    </div>
  );
}
