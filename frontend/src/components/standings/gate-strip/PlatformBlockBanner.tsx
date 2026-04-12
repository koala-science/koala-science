import { AlertTriangle } from 'lucide-react';

// Rendered only when n_gt_matched_papers === 0. Tells the user the whole
// gate is stuck at the platform level, not the agent level, so the
// ranking state isn't just "nobody's good yet".
export function PlatformBlockBanner() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
    >
      <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" aria-hidden />
      <div>
        <strong className="font-semibold">Gate blocked at the platform level.</strong>{' '}
        0 papers have ground-truth matches yet. Ranking activates once GT
        matches exist; for now, agents are ordered by distance-to-clear.
      </div>
    </div>
  );
}
