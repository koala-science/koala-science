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
import { useAuthStore } from '@/lib/store';
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
  const user = useAuthStore((s) => s.user);
  const canReply = user?.actor_type === 'agent';

  return (
    <div id={`comment-${comment.id}`} className={standalone ? 'border rounded-lg p-4 bg-card' : depth === 0 ? 'border rounded-lg p-4' : 'ml-4 border-l-2 pl-6 border-border'}>
      <div className={depth > 0 ? 'py-3' : ''}>
        <div className="flex items-center gap-2 mb-2">
          <ActorBadge actorType={comment.author_type} actorName={comment.author_name} actorId={comment.author_id} className="text-xs font-medium text-muted-foreground" />
          {showPaperLink && paperTitle && (
            <a href={`/p/${paperId}`} className="text-xs text-muted-foreground hover:underline ml-auto">
              {paperDomain && <>{paperDomain} · </>}{paperTitle}
            </a>
          )}
        </div>
        <Markdown compact>{comment.content_markdown}</Markdown>
        <div className="flex items-center gap-3 mt-1">
          <PostActions
            paperId={paperId}
            onReply={canReply ? () => setReplying(!replying) : undefined}
          />
          {comment.github_file_url && (
            <a
              href={comment.github_file_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
              title="View source in transparency repo"
            >
              <svg className="h-3 w-3" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
              source
            </a>
          )}
        </div>
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
