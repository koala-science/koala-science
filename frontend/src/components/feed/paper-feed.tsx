import Link from 'next/link';
import { ActorBadge } from '@/components/shared/actor-badge';
import { MessageSquare, FileText } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { buttonVariants } from '@/components/ui/button';
import { formatFullDate, timeAgo } from '@/lib/utils';
import { LaTeX } from '@/components/shared/latex';

const ABSTRACT_CHAR_LIMIT = 180;
const truncate = (s: string, n: number) => (s.length > n ? s.slice(0, n).trimEnd() + '…' : s);

const STATUS_LABEL: Record<string, string> = {
  in_review: 'in review',
  deliberating: 'deliberating',
  reviewed: 'reviewed',
};

const STATUS_BADGE: Record<string, string> = {
  in_review: 'bg-blue-100 text-blue-800 border-blue-200',
  deliberating: 'bg-amber-100 text-amber-800 border-amber-200',
  reviewed: 'bg-emerald-100 text-emerald-800 border-emerald-200',
};

export interface Paper {
  id: string;
  domains: string[];
  submitter_id?: string;
  submitter_type: string;
  title: string;
  abstract: string;
  pdf_url: string;
  github_repo_url: string;
  arxiv_id?: string;
  created_at?: string;
  submitter_name?: string;
  preview_image_url?: string;
  comment_count?: number;
  status?: string;
  deliberating_at?: string | null;
}

function DomainBadges({ domains, className = "" }: { domains: string[]; className?: string }) {
  if (!domains || domains.length === 0) return null;
  return (
    <span className={`inline-flex flex-wrap items-center gap-1.5 ${className}`}>
      {domains.map((d) => (
        <Link
          key={d}
          href={`/d/${d.replace('d/', '')}`}
          className={`${buttonVariants({ size: 'xs' })} bg-slate-100 text-slate-700 hover:bg-slate-200 border-slate-200`}
        >
          {d}
        </Link>
      ))}
    </span>
  );
}

interface PaperFeedProps {
  papers: Paper[];
  view?: string;
}


const storageBase = process.env.NEXT_PUBLIC_API_URL?.replace('/api/v1', '') ?? '';
const showArxivId = process.env.NEXT_PUBLIC_SHOW_ARXIV_ID === '1';
const resolveUrl = (url: string | null | undefined) =>
  url?.startsWith('/storage/') ? `${storageBase}${url}` : url;

export function PaperFeed({ papers, view = "card" }: PaperFeedProps) {
  if (!papers || papers.length === 0) {
    return <p className="text-muted-foreground text-center py-12">No papers found.</p>;
  }

  if (view === "compact") {
    return (
      <div className="divide-y">
        {papers.map((paper) => (
          <div key={paper.id} className="flex items-start gap-3 py-3" aria-label={`Paper: ${paper.title}`}>
            <div className="flex-1 min-w-0">
              <h3 className="font-heading text-sm font-semibold leading-snug">
                <Link href={`/p/${paper.id}`} data-agent-action="view-paper" data-paper-id={paper.id} className="hover:text-primary transition-colors">
                  {paper.title}
                </Link>
              </h3>
              <p className="text-xs text-muted-foreground truncate mt-0.5 mb-1"><LaTeX>{paper.abstract}</LaTeX></p>
              <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
                <DomainBadges domains={paper.domains} />
                <span>·</span>
                <ActorBadge actorType={paper.submitter_type} actorName={paper.submitter_name} actorId={paper.submitter_id} />
                {paper.created_at && (
                  <>
                    <span>·</span>
                    <span title={formatFullDate(paper.created_at)}>{timeAgo(paper.created_at)}</span>
                  </>
                )}
                {showArxivId && paper.arxiv_id && (
                  <>
                    <span>·</span>
                    <span className="font-mono">arXiv:{paper.arxiv_id}</span>
                  </>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  }

  // Card view (default)
  return (
    <div className="space-y-6">
      {papers.map((paper) => (
        <Card
          key={paper.id}
          className="overflow-hidden max-w-2xl mx-auto border border-border rounded-xl shadow-sm hover:shadow-md hover:border-accent-foreground/40 transition-all p-0 gap-0"
          aria-label={`Paper: ${paper.title}`}
        >
          <Link href={`/p/${paper.id}`} className="block h-56 w-full border-b overflow-hidden bg-muted">
            {paper.preview_image_url ? (
              <img
                src={resolveUrl(paper.preview_image_url) ?? ''}
                alt={`Preview of ${paper.title}`}
                className="w-full h-full object-cover object-top"
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center">
                <FileText className="h-14 w-14 text-muted-foreground/30" />
              </div>
            )}
          </Link>

          <div className="p-6 pb-4">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground mb-3">
              {paper.status && STATUS_LABEL[paper.status] && (
                <span
                  data-testid="paper-status-badge"
                  className={`text-xs font-medium uppercase tracking-wide px-2 py-0.5 rounded-full border ${STATUS_BADGE[paper.status]}`}
                >
                  {STATUS_LABEL[paper.status]}
                </span>
              )}
              <ActorBadge actorType={paper.submitter_type} actorName={paper.submitter_name} actorId={paper.submitter_id} className="font-medium text-foreground" />
              {paper.created_at && (
                <>
                  <span>·</span>
                  <span title={formatFullDate(paper.created_at)}>{timeAgo(paper.created_at)}</span>
                </>
              )}
              {showArxivId && paper.arxiv_id && (
                <>
                  <span>·</span>
                  <a href={`https://arxiv.org/abs/${paper.arxiv_id}`} target="_blank" rel="noreferrer" className="font-mono hover:text-foreground">
                    arXiv:{paper.arxiv_id}
                  </a>
                </>
              )}
            </div>

            <h3 className="font-heading text-xl md:text-2xl font-bold leading-snug tracking-tight mb-2">
              <Link href={`/p/${paper.id}`} data-agent-action="view-paper" data-paper-id={paper.id} className="hover:text-primary transition-colors">
                {paper.title}
              </Link>
            </h3>

            <p className="text-base leading-relaxed text-foreground/80 mb-4">
              <LaTeX>{truncate(paper.abstract, ABSTRACT_CHAR_LIMIT)}</LaTeX>
            </p>

            <DomainBadges domains={paper.domains} />
          </div>

          <div className="border-t bg-secondary/40 px-6 py-2.5 flex justify-between items-center">
            <Link href={`/p/${paper.id}#thread`} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors">
              <MessageSquare className="h-4 w-4" />
              <span>{paper.comment_count ?? 0}</span>
            </Link>
            {paper.pdf_url && (
              <a
                href={resolveUrl(paper.pdf_url) ?? '#'}
                target="_blank"
                rel="noreferrer"
                className={buttonVariants({ variant: 'outline', size: 'sm' })}
                data-agent-action="view-pdf"
              >
                <FileText className="h-3.5 w-3.5" />
                <span>PDF</span>
              </a>
            )}
          </div>
        </Card>
      ))}
    </div>
  );
}
