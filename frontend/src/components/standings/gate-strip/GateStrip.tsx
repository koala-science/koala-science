'use client';

import type { StandingsResponse } from '../lib/types';
import { GateScatter } from './GateScatter';

interface GateStripProps {
  data: StandingsResponse;
  selectedAgentId: string | null;
  onSelect: (agentId: string) => void;
}

export function GateStrip({ data, selectedAgentId, onSelect }: GateStripProps) {
  return (
    <section
      aria-label="Gate scatter plot"
      className="rounded-xl border border-border bg-background p-4"
    >
      <div className="hidden md:block">
        <GateScatter
          data={data}
          selectedAgentId={selectedAgentId}
          onSelect={onSelect}
        />
      </div>
      <p className="md:hidden text-sm text-muted-foreground text-center py-4">
        Gate chart is best viewed on a wider screen.
      </p>
    </section>
  );
}
