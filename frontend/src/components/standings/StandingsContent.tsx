'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { Medal } from 'lucide-react';
import { useStandingsData } from './hooks/useStandingsData';
import { useStandingsSelection } from './hooks/useStandingsSelection';
import { useStandingsFilters } from './hooks/useStandingsFilters';
import { GateStrip } from './gate-strip/GateStrip';
import { MasterList } from './master-list/MasterList';
import { DetailPane } from './detail-pane/DetailPane';
import { StandingsLayout } from './StandingsLayout';

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

// Inner component that uses useSearchParams; wrapped in Suspense per the
// Next.js 14 app-router constraint.
function StandingsInner() {
  const { data, error } = useStandingsData();
  const { selectedAgentId, setAgent } = useStandingsSelection();
  const filterResult = useStandingsFilters(data?.entries ?? []);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);

  // Default selection: first passer, else first-by-distance. Written to
  // URL only when the param is absent so sharable links win.
  useEffect(() => {
    if (!data || selectedAgentId) return;
    const entries = data.entries;
    if (!entries.length) return;
    const first = entries.find(e => e.passed_gate) ?? entries[0];
    if (first) setAgent(first.agent_id);
  }, [data, selectedAgentId, setAgent]);

  const selectedEntry = useMemo(() => {
    if (!data || !selectedAgentId) return null;
    return data.entries.find(e => e.agent_id === selectedAgentId) ?? null;
  }, [data, selectedAgentId]);

  const handleSelect = (agentId: string) => {
    setAgent(agentId);
    if (typeof window !== 'undefined' && window.innerWidth < 768) {
      setMobileDrawerOpen(true);
    }
  };

  return (
    <div className="max-w-7xl mx-auto space-y-4">
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
        <SkeletonBlock />
      ) : data ? (
        <StandingsLayout
          gateStrip={
            <GateStrip
              data={data}
              selectedAgentId={selectedAgentId}
              onSelect={handleSelect}
            />
          }
          masterList={
            <MasterList
              data={data}
              entries={filterResult.filteredEntries}
              selectedAgentId={selectedAgentId}
              onSelect={handleSelect}
              filters={filterResult.filters}
              setSort={filterResult.setSort}
              toggleReason={filterResult.toggleReason}
              setPassersOnly={filterResult.setPassersOnly}
              setQuery={filterResult.setQuery}
            />
          }
          detailPane={<DetailPane entry={selectedEntry} data={data} />}
          isDetailOpenMobile={mobileDrawerOpen}
          onCloseDetail={() => setMobileDrawerOpen(false)}
        />
      ) : null}
    </div>
  );
}

export function StandingsContent() {
  return (
    <Suspense fallback={<SkeletonBlock />}>
      <StandingsInner />
    </Suspense>
  );
}
