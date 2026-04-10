'use client';

import Link from 'next/link';
import { PaperFeed } from '@/components/feed/paper-feed';
import { ShowMoreList } from '@/components/shared/show-more-list';
import { PostActions } from '@/components/shared/post-actions';
import { timeAgo } from '@/lib/utils';

interface UserPapersTabProps {
  papers: any[];
  userId: string;
  actorType: string;
  userName: string;
}

export function UserPapersTab({ papers, userId, actorType, userName }: UserPapersTabProps) {
  return (
    <ShowMoreList
      initialItems={papers}
      fetchPath={`/users/${userId}/papers`}
      emptyMessage="No papers submitted."
      renderItem={(p: any) => (
        <div key={p.id} className="mb-4">
          <PaperFeed papers={[{
            ...p,
            submitter_id: userId,
            submitter_type: actorType,
            submitter_name: userName,
          }]} />
        </div>
      )}
    />
  );
}

interface UserCommentsTabProps {
  comments: any[];
  userId: string;
}

export function UserCommentsTab({ comments, userId }: UserCommentsTabProps) {
  return (
    <ShowMoreList
      initialItems={comments}
      fetchPath={`/users/${userId}/comments`}
      emptyMessage="No comments yet."
      renderItem={(c: any) => (
        <ActivityCard key={c.id} item={{ ...c, _type: 'comment' }} />
      )}
    />
  );
}

function ActivityCard({ item }: { item: any }) {
  const type = item._type;
  const paperId = type === 'paper' ? item.id : item.paper_id;
  const paperTitle = type === 'paper' ? item.title : item.paper_title;
  const domain = type === 'paper' ? item.domain : item.paper_domain;
  const targetType = type === 'paper' ? 'PAPER' as const : 'COMMENT' as const;
  const targetId = item.id;

  const typeLabel = type === 'paper' ? 'Submitted' : 'Commented';

  return (
    <div className="border rounded-lg p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
        <span className="font-medium">{typeLabel}</span>
        <span>·</span>
        <span>{domain}</span>
        {type === 'paper' && item.arxiv_id && (
          <><span>·</span><span className="font-mono">arXiv:{item.arxiv_id}</span></>
        )}
        {item.created_at && <><span>·</span><span>{timeAgo(item.created_at)}</span></>}
      </div>
      {type !== 'paper' && item.content_preview && (
        <p className="text-sm line-clamp-3 mt-1">{item.content_preview}</p>
      )}
      {type !== 'paper' && (
        <Link href={`/paper/${paperId}`} className="text-xs text-muted-foreground hover:underline mt-1 block">
          on {paperTitle}
        </Link>
      )}
      {type === 'paper' && (
        <Link href={`/paper/${paperId}`} className="text-sm font-medium hover:underline">
          {paperTitle}
        </Link>
      )}
      <PostActions
        targetType={targetType}
        targetId={targetId}
        initialScore={item.net_score ?? 0}
        paperId={paperId}
      />
    </div>
  );
}
