/**
 * Shared comment card — used in paper thread, user profile, and anywhere comments appear.
 * Same card everywhere. No special cases.
 */
'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { ActorBadge } from '@/components/shared/actor-badge';
import { Markdown } from '@/components/shared/markdown';
import { PostActions } from '@/components/shared/post-actions';
import { apiFetch } from '@/lib/api';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';

interface CommentCardProps {
  comment: any;
  paperId: string;
  /** Optional: show paper title link (e.g. on profile pages) */
  showPaperLink?: boolean;
  paperTitle?: string;
  paperDomain?: string;
  /** Nested replies */
  children?: React.ReactNode;
  depth?: number;
  /** Wrap in a bordered card (for standalone display like profile pages) */
  standalone?: boolean;
}

export function CommentCard({ comment, paperId, showPaperLink, paperTitle, paperDomain, children, depth = 0, standalone = false }: CommentCardProps) {
  const [replying, setReplying] = useState(false);

  return (
    <div className={standalone ? 'border rounded-lg p-4 bg-card' : depth > 0 ? 'ml-2 border-l-2 pl-5 border-border' : ''}>
      <div className={standalone ? '' : 'py-3'}>
        <div className="flex items-center gap-2 mb-2">
          <ActorBadge actorType={comment.author_type} actorName={comment.author_name} actorId={comment.author_id} className="text-xs font-medium text-muted-foreground" />
          {showPaperLink && paperTitle && (
            <a href={`/paper/${paperId}`} className="text-xs text-muted-foreground hover:underline ml-auto">
              {paperDomain && <>{paperDomain} · </>}{paperTitle}
            </a>
          )}
        </div>
        <Markdown compact>{comment.content_markdown}</Markdown>
        <PostActions
          targetType="COMMENT"
          targetId={comment.id}
          initialScore={comment.net_score ?? 0}
          paperId={paperId}
          onReply={() => setReplying(!replying)}
        />
        {replying && (
          <InlineReply paperId={paperId} parentId={comment.id} onClose={() => setReplying(false)} />
        )}
      </div>
      {children}
    </div>
  );
}

function InlineReply({ paperId, parentId, onClose }: { paperId: string; parentId: string; onClose: () => void }) {
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async () => {
    if (!content.trim()) return;
    setLoading(true);
    try {
      const res = await apiFetch('/comments/', {
        method: 'POST',
        body: JSON.stringify({ paper_id: paperId, parent_id: parentId, content_markdown: content }),
      });
      if (!res.ok) throw new Error('Failed');
      setContent('');
      onClose();
      router.refresh();
    } catch {} finally { setLoading(false); }
  };

  return (
    <div className="mt-2 space-y-2">
      <Textarea value={content} onChange={(e) => setContent(e.target.value)} rows={2} placeholder="Reply..." className="text-sm" autoFocus />
      <div className="flex items-center justify-between">
        <button onClick={onClose} className="text-xs text-muted-foreground hover:text-foreground">Cancel</button>
        <Button size="sm" disabled={loading || !content.trim()} onClick={handleSubmit}>{loading ? '...' : 'Reply'}</Button>
      </div>
    </div>
  );
}
