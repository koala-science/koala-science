'use client';

import { useEffect, useState } from 'react';
import { notFound } from 'next/navigation';

import { apiFetch } from '@/lib/api';
import { PaperDetailClient, type PaperRecord } from '@/components/paper/paper-detail-client';
import type { ArgumentRecord } from '@/components/paper/argument-section';
import { PageShell } from '@/components/shared/page';
import { ErrorState } from '@/components/shared/state';

type Loaded = { paper: PaperRecord; arguments: ArgumentRecord[] };

/**
 * The paper page for a paper the server could not show. The server renders
 * without the reader's token, so a private paper is a 404 there; this asks
 * again from the browser, where the token is, and is a 404 only if that is too.
 */
export function PrivatePaperLoader({ id }: { id: string }) {
  const [state, setState] = useState<'loading' | 'missing' | 'failed' | Loaded>('loading');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [paperRes, argumentsRes] = await Promise.all([
          apiFetch(`/papers/${id}`),
          apiFetch(`/papers/${id}/arguments?limit=1000`),
        ]);
        if (cancelled) return;
        if (paperRes.status === 404) return setState('missing');
        if (!paperRes.ok || !argumentsRes.ok) return setState('failed');
        setState({ paper: await paperRes.json(), arguments: await argumentsRes.json() });
      } catch {
        if (!cancelled) setState('failed');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (state === 'missing') notFound();
  if (state === 'loading') {
    return <PageShell width="default"><p className="text-sm text-muted-foreground">Loading…</p></PageShell>;
  }
  if (state === 'failed') {
    return <PageShell width="default"><ErrorState title="This paper could not be loaded" /></PageShell>;
  }
  return <PaperDetailClient paper={state.paper} arguments={state.arguments} />;
}
