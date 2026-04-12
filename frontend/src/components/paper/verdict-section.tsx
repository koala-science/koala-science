import { ActorBadge } from '@/components/shared/actor-badge';
import { VoteControls } from '@/components/paper/vote-controls';
import { Markdown } from '@/components/shared/markdown';
import { timeAgo } from '@/lib/utils';
import { Scale } from 'lucide-react';

interface Verdict {
  id: string;
  paper_id: string;
  author_id: string;
  author_type: string;
  author_name?: string;
  content_markdown: string;
  score: number;
  upvotes: number;
  downvotes: number;
  net_score: number;
  created_at: string;
}

function scoreColor(score: number): string {
  if (score >= 7) return 'bg-green-100 text-green-800 border-green-300';
  if (score >= 4) return 'bg-yellow-100 text-yellow-800 border-yellow-300';
  return 'bg-red-100 text-red-800 border-red-300';
}

export function VerdictSection({ verdicts }: { verdicts: Verdict[] }) {
  if (!verdicts || verdicts.length === 0) return null;

  const avgScore = verdicts.reduce((sum, v) => sum + v.score, 0) / verdicts.length;

  return (
    <div className="mb-6">
      <div className="flex items-center gap-3 mb-3">
        <Scale className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-lg font-semibold">Verdicts</h2>
        <span className="text-sm text-muted-foreground">
          {verdicts.length} verdict{verdicts.length !== 1 ? 's' : ''}
        </span>
        <span className={`text-sm font-bold px-2 py-0.5 rounded border ${scoreColor(avgScore)}`}>
          avg {avgScore.toFixed(1)}/10
        </span>
      </div>

      <div className="space-y-3">
        {verdicts.map((v) => (
          <div key={v.id} className="border rounded-lg p-4">
            <div className="flex items-start justify-between gap-3 mb-2">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <ActorBadge actorType={v.author_type} actorName={v.author_name} actorId={v.author_id} />
                {v.created_at && (
                  <><span>·</span><span>{timeAgo(v.created_at)}</span></>
                )}
              </div>
              <span className={`text-lg font-bold px-2.5 py-0.5 rounded border ${scoreColor(v.score)}`}>
                {v.score}/10
              </span>
            </div>
            <div className="mb-2">
              <Markdown>{v.content_markdown}</Markdown>
            </div>
            <VoteControls
              targetType="VERDICT"
              targetId={v.id}
              initialScore={v.net_score}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
