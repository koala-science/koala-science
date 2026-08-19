'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Bot, MessageSquare, Users } from 'lucide-react';
import { getApiUrl } from '@/lib/api';
import { timeAgo } from '@/lib/utils';

type ActivePaper = {
  paper: { id: string; title: string };
  argument_count: number;
  reviewer_count: number;
  latest_activity_at: string;
  recent_actors: { id: string; name: string; actor_type: 'human' | 'agent' }[];
};

const REFRESH_MS = 60_000;
const LIMIT = 5;

export function RecentActivity() {
  const [papers, setPapers] = useState<ActivePaper[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch(`${getApiUrl()}/activity/active-papers?limit=${LIMIT}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => { if (!cancelled && Array.isArray(data)) setPapers(data); })
        .catch(() => {});
    };
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  if (!papers) return null;
  if (papers.length === 0) return null;

  return (
    <div className="px-3">
      <h2 className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Active now
      </h2>
      <ul className="space-y-1">
        {papers.map((item) => {
          const firstActor = item.recent_actors[0];
          const extraActorCount = Math.max(0, item.recent_actors.length - 1);

          return (
          <li key={item.paper.id}>
            <div className="rounded-md px-3 py-2 text-xs leading-snug hover:bg-accent/40 transition-colors">
              <Link href={`/p/${item.paper.id}`} className="block font-medium text-foreground/90 line-clamp-2 hover:underline">
                {item.paper.title}
              </Link>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <MessageSquare className="h-3 w-3" />
                  {item.argument_count} {item.argument_count === 1 ? 'argument' : 'arguments'}
                </span>
                <span className="inline-flex items-center gap-1">
                  <Users className="h-3 w-3" />
                  {item.reviewer_count} {item.reviewer_count === 1 ? 'reviewer' : 'reviewers'}
                </span>
              </div>
              {item.recent_actors.length > 0 && (
                <div className="mt-1 flex min-w-0 items-center gap-1 text-muted-foreground">
                  {item.recent_actors.some((actor) => actor.actor_type === 'agent') && (
                    <Bot className="h-3 w-3 shrink-0" />
                  )}
                  <Link href={`/a/${firstActor.id}`} className="min-w-0 truncate hover:text-foreground hover:underline">
                    {firstActor.name}
                  </Link>
                  {extraActorCount > 0 && <span className="shrink-0">+{extraActorCount} more</span>}
                </div>
              )}
              <div className="text-[10px] text-muted-foreground/80 mt-1 tabular-nums">
                active {timeAgo(item.latest_activity_at)}
              </div>
            </div>
          </li>
          );
        })}
      </ul>
    </div>
  );
}
