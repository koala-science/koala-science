'use client';

import { ReactNode } from 'react';
import { notFound } from 'next/navigation';
import { useBetaFlag } from '@/lib/use-beta-flag';

interface BetaGateProps {
  flag: string;
  children: ReactNode;
  fallback?: ReactNode;
  loading?: ReactNode;
}

// Page-level gate. Renders children only when the signed-in user is on the
// flag's allow list. When not allowed, triggers the nearest not-found.tsx
// (stock Next 404). Pass `fallback` to render something else instead.
export function BetaGate({ flag, children, fallback, loading }: BetaGateProps) {
  const { allowed, loading: isLoading } = useBetaFlag(flag);
  if (isLoading) return <>{loading ?? null}</>;
  if (!allowed) {
    if (fallback !== undefined) return <>{fallback}</>;
    notFound();
  }
  return <>{children}</>;
}

// Inline visibility gate. Renders children only if allowed, else nothing.
// Use for nav entries, badges, links inside existing UI.
export function BetaVisible({ flag, children }: { flag: string; children: ReactNode }) {
  const { allowed } = useBetaFlag(flag);
  if (!allowed) return null;
  return <>{children}</>;
}
