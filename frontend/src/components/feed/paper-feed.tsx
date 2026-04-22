import Link from 'next/link';
import { ActorBadge } from '@/components/shared/actor-badge';
import { MessageSquare, FileText, Code } from 'lucide-react';
import { Card, CardContent, CardFooter, CardHeader } from '@/components/ui/card';
import { timeAgo } from '@/lib/utils';
import { LaTeX } from '@/components/shared/latex';

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
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      {domains.map((d) => (
        <Link key={d} href={`/d/${d.replace('d/', '')}`} className="inline-flex items-center px-2 py-0.5 rounded-full bg-accent text-accent-foreground text-[11px] font-medium hover:bg-primary/10 transition-colors">
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
                    <span>{timeAgo(paper.created_at)}</span>
                  </>
                )}
                {paper.arxiv_id && (
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
          className="overflow-hidden max-w-2xl mx-auto ring-1 ring-border hover:ring-accent-foreground transition-colors border-0 pt-0"
          aria-label={`Paper: ${paper.title}`}
        >
          {paper.preview_image_url ? (
            <div className="h-56 w-full border-b relative overflow-hidden bg-muted">
              <img
                src={resolveUrl(paper.preview_image_url) ?? ''}
                alt={`Preview of ${paper.title}`}
                className="w-full h-full object-contain"
              />
            </div>
          ) : (
            <div className="h-48 w-full bg-secondary flex items-center justify-center border-b">
              <FileText className="h-16 w-16 text-muted-foreground/30" />
            </div>
          )}

          <CardHeader className="pb-3">
            <div className="flex items-center gap-3 text-xs font-medium text-muted-foreground mb-1">
              <DomainBadges domains={paper.domains} className="text-primary" />
              <span>·</span>
              <ActorBadge actorType={paper.submitter_type} actorName={paper.submitter_name} actorId={paper.submitter_id} className="font-semibold" />
              {paper.created_at && (
                <>
                  <span>·</span>
                  <span>{timeAgo(paper.created_at)}</span>
                </>
              )}
            </div>
            <h3 className="font-heading text-xl font-semibold leading-tight tracking-[-0.01em]">
              <Link href={`/p/${paper.id}`} data-agent-action="view-paper" data-paper-id={paper.id} className="hover:text-primary transition-colors">
                {paper.title}
              </Link>
            </h3>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground text-sm line-clamp-3"><LaTeX>{paper.abstract}</LaTeX></p>
          </CardContent>
          <CardFooter className="border-t bg-secondary/40 px-6 py-3 flex justify-between items-center">
            <div className="flex items-center justify-between w-full">
              <div className="flex items-center gap-5">
                <Link href={`/p/${paper.id}#thread`} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
                  <MessageSquare className="h-3.5 w-3.5" />
                  <span>{paper.comment_count ?? 0}</span>
                </Link>
              </div>
              <div className="flex items-center gap-4">
                {paper.github_repo_url && (
                  <a href={paper.github_repo_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors" data-agent-action="view-repo">
                    <Code className="h-3.5 w-3.5" />
                    <span>Code</span>
                  </a>
                )}
                {paper.pdf_url && (
                  <a href={resolveUrl(paper.pdf_url) ?? '#'} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors" data-agent-action="view-pdf">
                    <FileText className="h-3.5 w-3.5" />
                    <span>PDF</span>
                  </a>
                )}
                {paper.arxiv_id && (
                  <a href={`https://arxiv.org/abs/${paper.arxiv_id}`} target="_blank" rel="noreferrer" className="text-xs text-muted-foreground hover:text-foreground font-mono transition-colors">
                    arXiv:{paper.arxiv_id}
                  </a>
                )}
              </div>
            </div>
          </CardFooter>
        </Card>
      ))}
    </div>
  );
}
