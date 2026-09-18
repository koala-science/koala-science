'use client';

import { PaperFeed } from '@/components/feed/paper-feed';
import { ShowMoreList } from '@/components/shared/show-more-list';
import { ActivityCard } from './activity-card';

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
      emptyMessage="No papers submitted"
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

interface UserArgumentsTabProps {
  arguments: any[];
  userId: string;
}

export function UserArgumentsTab({ arguments: argumentList, userId }: UserArgumentsTabProps) {
  return (
    <ShowMoreList
      initialItems={argumentList}
      fetchPath={`/users/${userId}/arguments`}
      emptyMessage="No arguments yet"
      renderItem={(c: any) => (
        <ActivityCard key={c.id} item={{ ...c, _type: 'argument' }} profileUserId={userId} />
      )}
    />
  );
}
