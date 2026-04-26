/**
 * Consistent action bar for all content: reply, share.
 * Used at the bottom of reviews, comments, and paper cards.
 */
'use client';

import { useState } from 'react';
import { ActionLink } from '@/components/shared/action-link';
import { useAuthStore } from '@/lib/store';
import { MessageSquare, Share2, Check } from 'lucide-react';

interface PostActionsProps {
  paperId?: string;
  commentId?: string;
  onReply?: () => void;
  showReply?: boolean;
}

export function PostActions({
  paperId,
  commentId,
  onReply,
  showReply = true,
}: PostActionsProps) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const [copied, setCopied] = useState(false);

  const handleShare = async () => {
    const url = paperId
      ? `${window.location.origin}/p/${paperId}${commentId ? `#comment-${commentId}` : ''}`
      : window.location.href;

    if (navigator.share) {
      try { await navigator.share({ url }); return; } catch {}
    }
    await navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex items-center gap-4 mt-2">
      {showReply && isAuthenticated && onReply && (
        <ActionLink
          icon={<MessageSquare className="h-3.5 w-3.5" />}
          label="Reply"
          onClick={onReply}
        />
      )}
      <ActionLink
        icon={copied ? <Check className="h-3.5 w-3.5 text-green-600" /> : <Share2 className="h-3.5 w-3.5" />}
        label={copied ? 'Copied' : 'Share'}
        onClick={handleShare}
      />
    </div>
  );
}
