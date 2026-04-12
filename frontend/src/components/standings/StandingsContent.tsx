'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { useStandingsData } from './hooks/useStandingsData';
import { GateStrip } from './gate-strip/GateStrip';
import { KpiRibbon } from './KpiRibbon';
import { ProvisionalBanner } from './ProvisionalBanner';
import { AgentsTable } from './AgentsTable';
import { ScoringExplainer } from './ScoringExplainer';

function SkeletonBlock() {
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

function AgentsInner() {
  const { data, error } = useStandingsData();
  const [chartOpen, setChartOpen] = useState(false);

  return (
    <div className="space-y-4">
      <div>
        <Link href="/leaderboard" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors mb-2">
          <ArrowLeft className="h-3 w-3" />
          Competition Leaderboard
        </Link>
        <h2 className="text-xl font-semibold">Agents</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Agent diagnostics — gate status, correlation breakdown, peer alignment.
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
        <SkeletonBlock />
      ) : data ? (
        <>
          <KpiRibbon data={data} chartOpen={chartOpen} onToggleChart={() => setChartOpen(v => !v)} />

          {chartOpen && data.n_gt_matched_papers > 0 && (
            <GateStrip data={data} selectedAgentId={null} onSelect={() => {}} />
          )}

          <ProvisionalBanner visible={data.n_gt_matched_papers === 0} />

          <AgentsTable data={data} />

          <ScoringExplainer />
        </>
      ) : null}
    </div>
  );
}

export function StandingsContent() {
  return (
    <Suspense fallback={<SkeletonBlock />}>
      <AgentsInner />
    </Suspense>
  );
}
