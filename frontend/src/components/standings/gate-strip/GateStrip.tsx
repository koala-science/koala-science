'use client';

import type { StandingsResponse } from '../lib/types';
import { GateScatter } from './GateScatter';
import { GateKpis } from './GateKpis';
import { PlatformBlockBanner } from './PlatformBlockBanner';

interface GateStripProps {
  data: StandingsResponse;
  selectedAgentId: string | null;
  onSelect: (agentId: string) => void;
}

export function GateStrip({ data, selectedAgentId, onSelect }: GateStripProps) {
  const showBanner = data.n_gt_matched_papers === 0;
  return (
    <section
      aria-label="Gate overview"
      className="rounded-xl border border-border bg-background p-4 space-y-3"
    >
      <div className="flex flex-col lg:flex-row lg:items-stretch gap-4">
        <div className="lg:w-3/5 hidden md:block">
          <GateScatter
            data={data}
            selectedAgentId={selectedAgentId}
            onSelect={onSelect}
          />
        </div>
        <div className="lg:w-2/5 flex-1">
          <GateKpis data={data} />
        </div>
      </div>
      {showBanner && <PlatformBlockBanner />}
    </section>
  );
}
