'use client';

import { useCallback } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

const SELECTION_PARAM = 'a';

export interface UseStandingsSelectionResult {
  selectedAgentId: string | null;
  setAgent: (agentId: string | null) => void;
}

// URL-synced selected agent. `router.replace` (not `push`) so the back
// button leaves the page rather than cycling selections. `scroll: false`
// prevents the scatter-click from jerking the viewport to the top.
export function useStandingsSelection(): UseStandingsSelectionResult {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const selectedAgentId = searchParams.get(SELECTION_PARAM);

  const setAgent = useCallback(
    (agentId: string | null) => {
      const next = new URLSearchParams(searchParams.toString());
      if (agentId == null) {
        next.delete(SELECTION_PARAM);
      } else {
        next.set(SELECTION_PARAM, agentId);
      }
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  return { selectedAgentId, setAgent };
}
