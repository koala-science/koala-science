'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { AnnotatorGate } from '@/components/annotate/annotator-gate';
import { apiCall } from '@/lib/api';

interface BatchRow {
  id: string;
  name: string;
  created_at: string;
}

export default function AnnotateIndexPage() {
  return (
    <AnnotatorGate>
      <BatchList />
    </AnnotatorGate>
  );
}

function BatchList() {
  const [batches, setBatches] = useState<BatchRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiCall<BatchRow[]>('/annotation/batches')
      .then(setBatches)
      .catch((e) => setError((e as Error).message));
  }, []);

  if (error) {
    return <div className="p-4 text-red-600">{error}</div>;
  }
  if (batches === null) {
    return <div className="p-4 text-muted-foreground">Loading...</div>;
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6 p-6">
      <header>
        <h1 className="font-heading text-3xl font-bold">Annotation</h1>
        <p className="text-muted-foreground">Batches assigned to you.</p>
      </header>

      {batches.length === 0 ? (
        <div className="text-muted-foreground">No batches assigned.</div>
      ) : (
        <ul className="border rounded divide-y bg-white">
          {batches.map((b) => (
            <li key={b.id}>
              <Link
                href={`/annotate/${b.id}`}
                className="block px-4 py-3 hover:bg-gray-50"
              >
                <div className="font-medium">{b.name}</div>
                <div className="text-xs text-muted-foreground">
                  Created {new Date(b.created_at).toLocaleDateString()}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
