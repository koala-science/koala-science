'use client';

import { useEffect } from 'react';
import { useAuthStore } from './store';

/**
 * Root provider — restores auth from localStorage and syncs body classes.
 * No Context needed — components use Zustand stores directly.
 */
export function AppProvider({ children }: { children: React.ReactNode }) {
  const restore = useAuthStore((s) => s.restore);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  useEffect(() => {
    restore();
  }, [restore]);

  useEffect(() => {
    const cl = document.body.classList;
    cl.toggle('authenticated', isAuthenticated);
    cl.toggle('guest', !isAuthenticated);
  }, [isAuthenticated]);

  return <>{children}</>;
}
