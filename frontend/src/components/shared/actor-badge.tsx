/**
 * Displays an actor's identity: icon (human/agent) + name.
 * Optionally links to the user's profile page.
 */

import Link from 'next/link';
import { User, Bot } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ActorBadgeProps {
  actorType: string;
  actorName?: string | null;
  actorId?: string | null;
  className?: string;
}

export function ActorBadge({ actorType, actorName, actorId, className }: ActorBadgeProps) {
  const Icon = actorType === 'human' ? User : Bot;
  const label = actorName || actorType;

  const content = (
    <span className={cn("inline-flex items-center gap-1", actorId && "hover:underline", className)}>
      <Icon className={cn("h-3.5 w-3.5", actorType === 'human' && "fill-muted-foreground")} />
      <span>{label}</span>
    </span>
  );

  if (actorId) {
    return <Link href={`/user/${actorId}`}>{content}</Link>;
  }

  return content;
}
