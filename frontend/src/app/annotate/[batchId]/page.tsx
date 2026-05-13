'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { AnnotatorGate } from '@/components/annotate/annotator-gate';
import { apiCall } from '@/lib/api';

interface PaperRow {
  paper_id: string;
  paper_title: string;
  pdf_url: string | null;
  comments_total: number;
  facts_total: number;
  facts_answered: number;
}

export default function BatchQueuePage() {
  return (
    <AnnotatorGate>
      <Queue />
    </AnnotatorGate>
  );
}

function Queue() {
  const params = useParams();
  const batchId = params.batchId as string;
  const [papers, setPapers] = useState<PaperRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiCall<PaperRow[]>(`/annotation/batches/${batchId}/queue`)
      .then(setPapers)
      .catch((e) => setError((e as Error).message));
  }, [batchId]);

  if (error) return <div className="p-4 text-red-600">{error}</div>;
  if (papers === null)
    return <div className="p-4 text-muted-foreground">Loading...</div>;

  return (
    <div className="max-w-4xl mx-auto space-y-8 p-6">
      <header>
        <Link href="/annotate" className="text-sm text-muted-foreground hover:underline">
          ← All batches
        </Link>
        <h1 className="font-heading text-3xl font-bold mt-1">Queue</h1>
      </header>

      {papers.length === 0 ? (
        <div className="text-muted-foreground">No assignments in this batch.</div>
      ) : (
        <div className="space-y-6">
          {papers.map((paper) => (
            <div
              key={paper.paper_id}
              className="border rounded bg-white px-4 py-3"
            >
              <Link
                href={`/annotate/${batchId}/paper/${paper.paper_id}`}
                className="font-semibold text-primary hover:underline"
              >
                {paper.paper_title}
              </Link>
              <div className="text-xs text-muted-foreground mt-1 flex items-center gap-4 flex-wrap">
                <span>
                  {paper.comments_total} comment{paper.comments_total === 1 ? '' : 's'}
                </span>
                <span>
                  {paper.facts_answered}/{paper.facts_total} arguments
                </span>
                <Link
                  href={`/p/${paper.paper_id}`}
                  target="_blank"
                  className="text-primary hover:underline"
                >
                  Conversation ↗
                </Link>
                {paper.pdf_url && (
                  <a
                    href={paper.pdf_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    PDF ↗
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
