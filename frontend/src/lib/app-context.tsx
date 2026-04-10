'use client';

import { useEffect } from 'react';
import { useAuthStore, useUIStore } from './store';

/**
 * Root provider — restores auth from localStorage and syncs body classes.
 * No Context needed — components use Zustand stores directly.
 */
export function AppProvider({ children }: { children: React.ReactNode }) {
  const restore = useAuthStore((s) => s.restore);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isAgentView = useUIStore((s) => s.isAgentView);

  useEffect(() => {
    restore();
  }, [restore]);

  useEffect(() => {
    const cl = document.body.classList;
    cl.toggle('agent-view-active', isAgentView);
    cl.toggle('authenticated', isAuthenticated);
    cl.toggle('guest', !isAuthenticated);
  }, [isAgentView, isAuthenticated]);

  return <>{children}</>;
}
