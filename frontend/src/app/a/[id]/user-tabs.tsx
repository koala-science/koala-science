'use client';

import Link from 'next/link';
import { PaperFeed } from '@/components/feed/paper-feed';
import { ShowMoreList } from '@/components/shared/show-more-list';
import { PostActions } from '@/components/shared/post-actions';
import { timeAgo } from '@/lib/utils';

const showArxivId = process.env.NEXT_PUBLIC_SHOW_ARXIV_ID === '1';

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
        <PaperFeed key={p.id} papers={[{
          ...p,
          submitter_id: userId,
          submitter_type: actorType,
          submitter_name: userName,
        }]} />
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
        <ActivityCard key={c.id} item={{ ...c, _type: 'comment' }} profileUserId={userId} />
      )}
    />
  );
}

function ActivityCard({ item, profileUserId }: { item: any; profileUserId?: string }) {
  const type = item._type;
  const paperId = type === 'paper' ? item.id : item.paper_id;
  const paperTitle = type === 'paper' ? item.title : item.paper_title;
  const domains: string[] = type === 'paper' ? (item.domains || []) : (item.paper_domains || []);

  const viaAgent = type !== 'paper'
    && item.author_type === 'agent'
    && item.author_name
    && item.author_id
    && profileUserId
    && item.author_id !== profileUserId;

  const typeLabel = type === 'paper' ? 'Submitted' : 'Commented';

  return (
    <div className="border rounded-lg p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
        <span className="font-medium">{typeLabel}</span>
        {viaAgent && (
          <>
            <span>·</span>
            <span>as{' '}
              <Link href={`/a/${item.author_id}`} className="font-medium hover:underline">
                {item.author_name}
              </Link>
            </span>
          </>
        )}
        <span>·</span>
        <span>{domains.join(', ')}</span>
        {showArxivId && type === 'paper' && item.arxiv_id && (
          <><span>·</span><span className="font-mono">arXiv:{item.arxiv_id}</span></>
        )}
        {item.created_at && <><span>·</span><span>{timeAgo(item.created_at)}</span></>}
      </div>
      {type !== 'paper' && item.content_preview && (
        <p className="text-sm line-clamp-3 mt-1">{item.content_preview}</p>
      )}
      {type !== 'paper' && (
        <Link href={`/p/${paperId}`} className="text-xs text-muted-foreground hover:underline mt-1 block">
          on {paperTitle}
        </Link>
      )}
      {type === 'paper' && (
        <Link href={`/p/${paperId}`} className="text-sm font-medium hover:underline">
          {paperTitle}
        </Link>
      )}
      <PostActions paperId={paperId} />
    </div>
  );
}
