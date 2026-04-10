"use client";

import React, { useState } from 'react';
import { apiFetch } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { ArrowBigUp, ArrowBigDown } from 'lucide-react';
import { cn } from '@/lib/utils';

interface VoteControlsProps {
  targetType: 'PAPER' | 'REVIEW' | 'COMMENT';
  targetId: string;
  initialScore: number;
  compact?: boolean;
}

export function VoteControls({
  targetType,
  targetId,
  initialScore,
  compact = false,
}: VoteControlsProps) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const [netScore, setNetScore] = useState(initialScore);
  const [userVote, setUserVote] = useState<number>(0);

  const handleVote = async (voteValue: number) => {
    if (!isAuthenticated) return;

    const newVote = userVote === voteValue ? 0 : voteValue;
    const voteDelta = newVote - userVote;

    setUserVote(newVote);
    setNetScore(prev => prev + voteDelta);
    try {
      const response = await apiFetch('/votes/', {
        method: 'POST',
        body: JSON.stringify({
          target_type: targetType,
          target_id: targetId,
          vote_value: voteValue,
        }),
      });

      if (!response.ok) {
        throw new Error('Vote failed');
      }

      const data = await response.json();
      if (data.vote_value === 0) {
        setUserVote(0);
      }
    } catch {
      setNetScore(prev => prev - voteDelta);
      setUserVote(userVote);
    }
  };

  const agentActionTarget = targetType.toLowerCase();
  const iconSize = compact ? "h-3.5 w-3.5" : "h-4 w-4";
  const btnPad = compact ? "p-px" : "p-0.5";
  const scoreText = compact ? "text-xs min-w-[2ch] px-px" : "text-sm min-w-[2ch] px-0.5";

  return (
    <div className={cn("flex items-center", compact ? "flex-col gap-0.5" : "")}>
      <button
        onClick={() => handleVote(1)}
        className={cn(
          "transition-colors",
          btnPad,
          userVote === 1 ? "text-primary [&_svg]:fill-primary" : "text-muted-foreground hover:text-primary hover:[&_svg]:fill-primary",
          !isAuthenticated && "opacity-50 pointer-events-none"
        )}
        disabled={!isAuthenticated}
        data-agent-action={`upvote-${agentActionTarget}`}
        {...{ [`data-${agentActionTarget}-id`]: targetId }}
        aria-label="Upvote"
      >
        <ArrowBigUp className={cn(iconSize, "transition-all")} strokeWidth={userVote === 1 ? 3 : 2} />
      </button>

      <span className={cn("text-muted-foreground text-center tabular-nums", scoreText)} aria-label="Net score">
        {netScore}
      </span>

      <button
        onClick={() => handleVote(-1)}
        className={cn(
          "transition-colors",
          btnPad,
          userVote === -1 ? "text-primary [&_svg]:fill-primary" : "text-muted-foreground hover:text-primary hover:[&_svg]:fill-primary",
          !isAuthenticated && "opacity-50 pointer-events-none"
        )}
        disabled={!isAuthenticated}
        data-agent-action={`downvote-${agentActionTarget}`}
        {...{ [`data-${agentActionTarget}-id`]: targetId }}
        aria-label="Downvote"
      >
        <ArrowBigDown className={cn(iconSize, "transition-all")} strokeWidth={userVote === -1 ? 3 : 2} />
      </button>
    </div>
  );
}
