import { ActorBadge } from '@/components/shared/actor-badge';
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
  github_file_url?: string;
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
            {v.github_file_url && (
              <div className="flex items-center gap-3">
                <a
                  href={v.github_file_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
                  title="View source in transparency repo"
                >
                  <svg className="h-3 w-3" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
                  source
                </a>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
