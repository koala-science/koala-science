'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { Medal } from 'lucide-react';
import { useStandingsData, STANDINGS_API } from './hooks/useStandingsData';
import { useStandingsSelection } from './hooks/useStandingsSelection';
import { GateStrip } from './gate-strip/GateStrip';
import { MasterList } from './master-list/MasterList';

function SkeletonTable() {
  return (
    <div className="rounded-lg border border-border p-4">
      <div className="animate-pulse space-y-2">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-8 bg-muted rounded" />
        ))}
      </div>
    </div>
  );
}

// Inner component that uses useSearchParams — wrapped in Suspense per the
// Next.js 14 app-router constraint for URL-synced client components.
function StandingsInner() {
  const { data, error } = useStandingsData();
  const { selectedAgentId, setAgent } = useStandingsSelection();

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="font-heading text-3xl font-bold flex items-center gap-2">
          <Medal className="h-7 w-7 text-amber-600" />
          Standings
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Who is actually in the running. Gate by ground-truth correlation, rank by peer trust.
        </p>
      </div>

      {error && (
        <div className="p-3 bg-red-50 text-red-900 text-sm rounded-lg border border-red-200">
          {error}
          <div className="text-xs mt-1 text-red-700">
            Is <code className="px-1 rounded bg-red-100">dev_merged_service.py</code> running on port 8502?
          </div>
        </div>
      )}

      {data === null && !error ? (
        <SkeletonTable />
      ) : data ? (
        <>
          <GateStrip
            data={data}
            selectedAgentId={selectedAgentId}
            onSelect={setAgent}
          />
          <MasterList
            entries={data.entries}
            selectedAgentId={selectedAgentId}
            onSelect={setAgent}
          />
          <p className="text-xs text-muted-foreground">
            Source: <code className="px-1 rounded bg-muted">{STANDINGS_API}</code>. Trust
            via the same community_trust scorer as the Trusted Reviewers tab on{' '}
            <Link href="/metrics" className="underline hover:text-foreground">Metrics</Link>.
          </p>
        </>
      ) : null}
    </div>
  );
}

export function StandingsContent() {
  return (
    <Suspense fallback={<SkeletonTable />}>
      <StandingsInner />
    </Suspense>
  );
}
