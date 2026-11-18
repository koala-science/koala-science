import React from 'react';
import { notFound } from 'next/navigation';

import { getApiUrl } from '@/lib/api';
import { PaperDetailClient } from '@/components/paper/paper-detail-client';
import { PrivatePaperLoader } from '@/components/paper/private-paper-loader';
import { PageShell } from '@/components/shared/page';
import { ErrorState } from '@/components/shared/state';

export default async function PaperDetailView({ params }: { params: { id: string } }) {
  const apiUrl = getApiUrl();
  const { id } = params;

  let paper: any = null;
  let argumentList: any[] = [];
  let status = 0;

  try {
    const [paperRes, argumentsRes] = await Promise.all([
      fetch(`${apiUrl}/papers/${id}`, { cache: 'no-store' }),
      fetch(`${apiUrl}/papers/${id}/arguments?limit=1000`, { cache: 'no-store' }),
    ]);

    status = paperRes.status;
    if (paperRes.ok) paper = await paperRes.json();
    if (argumentsRes.ok) argumentList = await argumentsRes.json();
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error('Failed to fetch data:', error);
  }

  // A malformed id is answered 422, which for the reader is the same as no such paper.
  if (status === 422) notFound();
  // A 404 here may be a private paper the reader can see: only their browser has the token.
  if (status === 404) return <PrivatePaperLoader id={id} />;
  if (!paper) {
    return (
      <PageShell width="default">
        <ErrorState title="This paper could not be loaded" />
      </PageShell>
    );
  }

  return <PaperDetailClient paper={paper} arguments={argumentList} />;
}
