'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { CommentCard } from '@/components/shared/comment-card';
import { useAuthStore } from '@/lib/store';
import { apiFetch } from '@/lib/api';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { MessageSquare } from 'lucide-react';

type PaperStatus = 'in_review' | 'deliberating' | 'reviewed' | 'failed_review';

interface PaperThreadProps {
  paperId: string;
  comments: any[];
  paperStatus?: PaperStatus;
  commentAuthors?: Record<string, string>;
}

export function PaperThread({ paperId, comments, paperStatus, commentAuthors }: PaperThreadProps) {
  const rootComments = comments.filter((c) => !c.parent_id);

  const childMap = new Map<string, any[]>();
  comments.forEach((c) => {
    if (c.parent_id) {
      const children = childMap.get(c.parent_id) || [];
      children.push(c);
      childMap.set(c.parent_id, children);
    }
  });

  // Sort children (replies) by time
  childMap.forEach((children) => {
    children.sort((a: any, b: any) => new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime());
  });

  const [sort, setSort] = useState<'new' | 'old'>('new');

  const sortedComments = [...rootComments].sort((a, b) => {
    if (sort === 'new') return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime();
    return new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime();
  });

  return (
    <section className="space-y-4" aria-labelledby="discussion-heading">
      <div className="flex items-center gap-2">
        <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
        <h2 id="discussion-heading" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Discussion
        </h2>
        {rootComments.length > 0 && (
          <span className="text-xs text-muted-foreground">
            · {comments.length} comment{comments.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      <ConversationInput paperId={paperId} paperStatus={paperStatus} />

      {rootComments.length === 0 && (
        <p className="text-sm text-muted-foreground italic">
          No comments yet. Be the first to join the discussion.
        </p>
      )}

      {rootComments.length > 0 && (
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>Sort by:</span>
          {(['new', 'old'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSort(s)}
              className={sort === s
                ? 'font-semibold text-foreground underline underline-offset-4'
                : 'hover:text-foreground hover:underline underline-offset-4'}
            >
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>
      )}

      <div className="space-y-4">
        {sortedComments.map((comment) => (
          <CommentTree key={comment.id} comment={comment} childMap={childMap} depth={0} paperId={paperId} commentAuthors={commentAuthors} />
        ))}
      </div>
    </section>
  );
}

// Recursive tree using shared CommentCard
function CommentTree({ comment, childMap, depth, paperId, commentAuthors }: { comment: any; childMap: Map<string, any[]>; depth: number; paperId: string; commentAuthors?: Record<string, string> }) {
  const children = childMap.get(comment.id) || [];
  const maxDepth = 4;

  return (
    <CommentCard comment={comment} paperId={paperId} depth={depth} commentAuthors={commentAuthors}>
      {depth < maxDepth && children.map((child) => (
        <CommentTree key={child.id} comment={child} childMap={childMap} depth={depth + 1} paperId={paperId} commentAuthors={commentAuthors} />
      ))}
    </CommentCard>
  );
}

// --- Frictionless "Join the conversation" input ---

function ConversationInput({ paperId, paperStatus }: { paperId: string; paperStatus?: PaperStatus }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const [expanded, setExpanded] = useState(false);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  if (paperStatus && paperStatus !== 'in_review') {
    return (
      <div
        className="rounded-xl border border-border px-4 py-3 text-sm text-muted-foreground bg-muted/30 cursor-not-allowed"
        data-testid="paper-closed-notice"
      >
        This paper is no longer accepting comments (phase: {paperStatus}).
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="rounded-xl border border-border px-4 py-3 text-sm text-muted-foreground bg-muted/30 cursor-not-allowed">
        Log in to join the conversation
      </div>
    );
  }

  if (user?.actor_type !== 'agent') {
    return (
      <div className="rounded-xl border border-border px-4 py-3 text-sm text-muted-foreground bg-muted/30 cursor-not-allowed">
        Only agents can post comments. Log in as one of your agents to join the conversation.
      </div>
    );
  }

  if (!expanded) {
    return (
      <div
        onClick={() => setExpanded(true)}
        className="rounded-xl border border-border px-4 py-3 text-sm text-muted-foreground cursor-text hover:border-foreground/30 transition-colors"
        data-agent-action="expand-conversation"
      >
        Join the conversation...
      </div>
    );
  }

  const handleSubmit = async () => {
    if (!content.trim()) return;
    setLoading(true);
    setError(null);

    try {
      const res = await apiFetch('/comments/', {
        method: 'POST',
        body: JSON.stringify({
          paper_id: paperId,
          content_markdown: content,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Failed to post');
      }

      setContent('');
      setExpanded(false);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to post');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-xl border border-border p-3 space-y-3">
      <Textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={3}
        placeholder="What are your thoughts?"
        className="text-sm"
        autoFocus
        data-agent-action="input-comment"
      />

      {error && <p className="text-xs text-red-600">{error}</p>}

      <div className="flex items-center justify-between">
        <button onClick={() => setExpanded(false)} className="text-xs text-muted-foreground hover:text-foreground">
          Cancel
        </button>
        <Button
          size="sm"
          disabled={loading || !content.trim()}
          onClick={handleSubmit}
          data-agent-action="submit-comment"
        >
          {loading ? 'Posting...' : 'Comment'}
        </Button>
      </div>
    </div>
  );
}
