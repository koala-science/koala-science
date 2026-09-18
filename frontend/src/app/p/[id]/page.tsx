import React from 'react';
import { notFound } from 'next/navigation';

import { getApiUrl } from '@/lib/api';
import { PaperDetailClient } from '@/components/paper/paper-detail-client';
import { PageShell } from '@/components/shared/page';
import { ErrorState } from '@/components/shared/state';

export default async function PaperDetailView({ params }: { params: { id: string } }) {
  const apiUrl = getApiUrl();
  const { id } = params;

  let paper: any = null;
  let argumentList: any[] = [];
  let missing = false;

  try {
    const [paperRes, argumentsRes] = await Promise.all([
      fetch(`${apiUrl}/papers/${id}`, { cache: 'no-store' }),
      fetch(`${apiUrl}/papers/${id}/arguments?limit=1000`, { cache: 'no-store' }),
    ]);

    // A malformed id is answered 422, which for the reader is the same as no such paper.
    missing = paperRes.status === 404 || paperRes.status === 422;
    if (paperRes.ok) paper = await paperRes.json();
    if (argumentsRes.ok) argumentList = await argumentsRes.json();
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error('Failed to fetch data:', error);
  }

  if (missing) notFound();
  if (!paper) {
    return (
      <PageShell width="default">
        <ErrorState title="This paper could not be loaded" />
      </PageShell>
    );
  }

  return <PaperDetailClient paper={paper} arguments={argumentList} />;
}
