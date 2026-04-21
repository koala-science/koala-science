import React from 'react';

import { getApiUrl } from '@/lib/api';
import { PaperDetailClient } from '@/components/paper/paper-detail-client';

export default async function PaperDetailView({ params }: { params: { id: string } }) {
  const apiUrl = getApiUrl();
  const { id } = params;

  let paper: any = null;
  let comments: any[] = [];
  let verdicts: any[] = [];

  try {
    const [paperRes, commentsRes, verdictsRes] = await Promise.all([
      fetch(`${apiUrl}/papers/${id}`, { cache: 'no-store' }),
      fetch(`${apiUrl}/comments/paper/${id}?limit=1000`, { cache: 'no-store' }),
      fetch(`${apiUrl}/verdicts/paper/${id}?limit=1000`, { cache: 'no-store' }),
    ]);

    if (paperRes.ok) paper = await paperRes.json();
    if (commentsRes.ok) comments = await commentsRes.json();
    if (verdictsRes.ok) verdicts = await verdictsRes.json();
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error('Failed to fetch data:', error);
  }

  if (!paper) {
    return <div className="p-8 text-muted-foreground text-center">Paper not found or API unavailable.</div>;
  }

  return (
    <PaperDetailClient
      paper={paper}
      comments={comments}
      verdicts={verdicts}
    />
  );
}
