'use client';

import { useEffect, useRef, useState } from 'react';
import { apiCall } from '@/lib/api';

interface DraftUpsert {
  question_id: string;
  agent_id: string;
  paper_id?: string;
  comment_id?: string;
  fact_id?: string;
  response_value: unknown;
}

export function useDebouncedDraftSave(batchId: string, delayMs = 500) {
  const queueRef = useRef<Map<string, DraftUpsert>>(new Map());
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<Date | null>(null);

  const flush = async () => {
    if (queueRef.current.size === 0) return;
    const batch = Array.from(queueRef.current.values());
    queueRef.current.clear();
    try {
      await apiCall('/annotation/responses/draft', {
        method: 'PATCH',
        body: JSON.stringify({ batch_id: batchId, upserts: batch }),
      });
      setError(null);
      setSavedAt(new Date());
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const enqueue = (upsert: DraftUpsert) => {
    const key = [
      upsert.question_id,
      upsert.agent_id,
      upsert.paper_id ?? '',
      upsert.comment_id ?? '',
      upsert.fact_id ?? '',
    ].join('|');
    queueRef.current.set(key, upsert);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      flush();
    }, delayMs);
  };

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return { enqueue, flush, error, savedAt };
}
