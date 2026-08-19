import React from 'react';

import { getApiUrl } from '@/lib/api';
import { PaperDetailClient } from '@/components/paper/paper-detail-client';

export default async function PaperDetailView({ params }: { params: { id: string } }) {
  const apiUrl = getApiUrl();
  const { id } = params;

  let paper: any = null;
  let argumentList: any[] = [];

  try {
    const [paperRes, argumentsRes] = await Promise.all([
      fetch(`${apiUrl}/papers/${id}`, { cache: 'no-store' }),
      fetch(`${apiUrl}/papers/${id}/arguments?limit=1000`, { cache: 'no-store' }),
    ]);

    if (paperRes.ok) paper = await paperRes.json();
    if (argumentsRes.ok) argumentList = await argumentsRes.json();
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error('Failed to fetch data:', error);
  }

  if (!paper) {
    return <div className="p-8 text-muted-foreground text-center">Paper not found or API unavailable.</div>;
  }

  return <PaperDetailClient paper={paper} arguments={argumentList} />;
}
