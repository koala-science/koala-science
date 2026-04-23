'use client';

import Link from 'next/link';
import { ReactNode, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { apiCall } from '@/lib/api';

interface Column<T> {
  header: string;
  cell: (row: T) => ReactNode;
  className?: string;
}

interface ListResponse<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
}

interface AdminTableProps<T> {
  path: string;
  rowHref?: (row: T) => string;
  columns: Column<T>[];
  emptyMessage?: string;
  pageSize?: number;
}

export function AdminTable<T extends { id: string }>({
  path,
  rowHref,
  columns,
  emptyMessage = 'No records.',
  pageSize = 50,
}: AdminTableProps<T>) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<ListResponse<T> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiCall<ListResponse<T>>(`${path}?page=${page}&limit=${pageSize}`)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path, page, pageSize]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;

  return (
    <div className="space-y-4">
      <div className="border rounded overflow-x-auto bg-white">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              {columns.map((col) => (
                <th
                  key={col.header}
                  className={`text-left px-4 py-2 font-semibold text-gray-700 ${col.className || ''}`}
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y">
            {loading && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-6 text-center text-muted-foreground">
                  Loading...
                </td>
              </tr>
            )}
            {!loading && error && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-6 text-center text-red-600">
                  {error}
                </td>
              </tr>
            )}
            {!loading && !error && data && data.items.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-6 text-center text-muted-foreground">
                  {emptyMessage}
                </td>
              </tr>
            )}
            {!loading && !error && data && data.items.map((row) => (
              <tr key={row.id} className="hover:bg-gray-50">
                {columns.map((col, i) => (
                  <td key={col.header} className={`px-4 py-2 ${col.className || ''}`}>
                    {i === 0 && rowHref ? (
                      <Link href={rowHref(row)} className="text-primary hover:underline">
                        {col.cell(row)}
                      </Link>
                    ) : (
                      col.cell(row)
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data && data.total > 0 && (
        <div className="flex items-center justify-between text-sm">
          <div className="text-muted-foreground">
            {data.total} total
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1 || loading}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Prev
            </Button>
            <span>
              Page {data.page} of {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages || loading}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
