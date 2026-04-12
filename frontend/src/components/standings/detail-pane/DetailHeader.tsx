import Link from 'next/link';
import { Bot, Cpu, ExternalLink, User } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { StandingsEntry } from '../lib/types';
import { formatDistance } from '../lib/distance-fmt';

function actorIcon(actorType: string) {
  if (actorType === 'human') return User;
  if (actorType === 'delegated_agent') return Bot;
  return Cpu;
}

export function DetailHeader({ entry }: { entry: StandingsEntry }) {
  const Icon = actorIcon(entry.actor_type);
  return (
    <div className="flex items-start gap-3 border-b border-border pb-3">
      <div className="flex items-center justify-center h-10 w-10 rounded-full bg-muted">
        <Icon className="h-5 w-5 text-muted-foreground" aria-hidden />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h2 className="font-heading text-lg font-semibold truncate" title={entry.agent_id}>
            {entry.agent_name}
          </h2>
          <span className="text-xs rounded-full px-2 py-0.5 bg-muted text-muted-foreground whitespace-nowrap">
            {entry.actor_type || 'agent'}
          </span>
        </div>
        <Link
          href={`/a/${entry.agent_id}`}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground underline decoration-dotted"
        >
          profile
          <ExternalLink className="h-3 w-3" aria-hidden />
        </Link>
      </div>
      <div className="text-right shrink-0">
        {entry.passed_gate ? (
          <>
            <div className="font-heading text-2xl font-bold tabular-nums">
              #{entry.rank}
            </div>
            <div
              className={cn(
                'text-xs rounded-full px-2 py-0.5 bg-emerald-100 text-emerald-800',
              )}
            >
              past gate
            </div>
          </>
        ) : (
          <>
            <div className="font-mono text-lg tabular-nums">
              {formatDistance(entry.distance_to_clear)}
            </div>
            <div className="text-xs text-muted-foreground">to clear</div>
          </>
        )}
      </div>
    </div>
  );
}
