import type { StandingsEntry, StandingsResponse } from '../lib/types';
import { DetailHeader } from './DetailHeader';
import { GateGauges } from './GateGauges';
import { SignalBreakdown } from './SignalBreakdown';
import { PeerPosition } from './PeerPosition';
import { TrustDecomposition } from './TrustDecomposition';
import { AdversarialPanel } from './AdversarialPanel';
import { ActivityStrip } from './ActivityStrip';
import { CalibrationSlot } from './CalibrationSlot';

interface DetailPaneProps {
  entry: StandingsEntry | null;
  data: StandingsResponse;
}

export function DetailPane({ entry, data }: DetailPaneProps) {
  if (!entry) {
    return (
      <div className="rounded-lg border border-border bg-background p-6 text-sm text-muted-foreground text-center">
        Select an agent to see their breakdown.
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-border bg-background p-4 space-y-4">
      <DetailHeader entry={entry} />
      <GateGauges entry={entry} data={data} />
      <SignalBreakdown entry={entry} />
      <PeerPosition entry={entry} />
      <TrustDecomposition entry={entry} />
      <AdversarialPanel entry={entry} />
      <ActivityStrip entry={entry} />
      <CalibrationSlot />
    </div>
  );
}
