import Link from 'next/link';
import { PostActions } from '@/components/shared/post-actions';
import { DomainChips } from '@/components/shared/domain-chip';
import { RelativeTime } from '@/components/shared/relative-time';

const showArxivId = process.env.NEXT_PUBLIC_SHOW_ARXIV_ID === '1';

export function ActivityCard({ item, profileUserId }: { item: any; profileUserId?: string }) {
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

  const typeLabel = type === 'paper' ? 'Submitted' : 'Argued';

  return (
    <div className="border rounded-lg p-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground mb-1">
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
        {domains.length > 0 && (
          <>
            <span>·</span>
            <DomainChips domains={domains} />
          </>
        )}
        {showArxivId && type === 'paper' && item.arxiv_id && (
          <><span>·</span><span className="font-mono">arXiv:{item.arxiv_id}</span></>
        )}
        {item.created_at && <><span>·</span><RelativeTime date={item.created_at} /></>}
      </div>
      {type !== 'paper' && item.claim && (
        <p className="text-sm line-clamp-3 mt-1">{item.claim}</p>
      )}
      {type !== 'paper' && (
        <Link href={`/p/${paperId}#argument-${item.id}`} className="text-xs text-muted-foreground hover:underline mt-1 block">
          on {paperTitle}
        </Link>
      )}
      {type === 'paper' && (
        <Link href={`/p/${paperId}`} className="text-sm font-medium hover:underline">
          {paperTitle}
        </Link>
      )}
      <PostActions paperId={paperId} argumentId={type !== 'paper' ? item.id : undefined} />
    </div>
  );
}
