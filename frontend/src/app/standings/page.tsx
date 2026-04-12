import { BetaGate } from '@/components/shared/beta-gate';
import { StandingsContent } from '@/components/standings/StandingsContent';

export default function StandingsPage() {
  return (
    <BetaGate flag="standings">
      <StandingsContent />
    </BetaGate>
  );
}
