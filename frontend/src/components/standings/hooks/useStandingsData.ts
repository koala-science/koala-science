import { useEffect, useState } from 'react';
import type { StandingsResponse } from '../lib/types';

const EVAL_API = '/eval/api';
export const STANDINGS_API = `${EVAL_API}/merged`;

const CACHE_MAX_AGE_MS = 5 * 60 * 1000;

interface StandingsCache {
  data: StandingsResponse | null;
  ts: number;
}

let _cache: StandingsCache = { data: null, ts: 0 };

async function fetchJsonRetry(url: string, retries = 2): Promise<unknown> {
  let lastErr: unknown;
  for (let i = 0; i <= retries; i++) {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      lastErr = e;
      if (i < retries) await new Promise(r => setTimeout(r, 1500));
    }
  }
  throw lastErr;
}

export interface UseStandingsDataResult {
  data: StandingsResponse | null;
  error: string | null;
}

export function useStandingsData(): UseStandingsDataResult {
  const [data, setData] = useState<StandingsResponse | null>(_cache.data);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const age = Date.now() - _cache.ts;
    if (_cache.data && age < CACHE_MAX_AGE_MS) return;

    let cancelled = false;
    (async () => {
      try {
        const d = (await fetchJsonRetry(STANDINGS_API)) as StandingsResponse;
        if (cancelled) return;
        _cache = { data: d, ts: Date.now() };
        setData(d);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Failed to load standings');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return { data, error };
}
