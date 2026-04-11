'use client';

import { useAuthStore } from './store';
import { isBetaAllowed } from './beta-flags';

export interface BetaFlagState {
  allowed: boolean;
  loading: boolean;
}

export function useBetaFlag(flag: string): BetaFlagState {
  const hydrated = useAuthStore((s) => s.hydrated);
  const user = useAuthStore((s) => s.user);
  if (!hydrated) return { allowed: false, loading: true };
  return { allowed: isBetaAllowed(flag, user ?? null), loading: false };
}
