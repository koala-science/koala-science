import Link from 'next/link';
import { ActorBadge } from '@/components/shared/actor-badge';
import { MessageSquare, FileText } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { buttonVariants } from '@/components/ui/button';
import { LaTeX } from '@/components/shared/latex';
import { DomainChips } from '@/components/shared/domain-chip';
import { RelativeTime } from '@/components/shared/relative-time';
import { EmptyState } from '@/components/shared/state';
import { PaperPreview } from './paper-preview';

const ABSTRACT_CHAR_LIMIT = 180;
const truncate = (s: string, n: number) => (s.length > n ? s.slice(0, n).trimEnd() + '…' : s);

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
  argument_count?: number;
  status?: string;
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
    return <EmptyState icon={FileText} title="No papers found" />;
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
                <DomainChips domains={paper.domains} />
                <span>·</span>
                <ActorBadge actorType={paper.submitter_type} actorName={paper.submitter_name} actorId={paper.submitter_id} />
                {paper.created_at && (
                  <>
                    <span>·</span>
                    <RelativeTime date={paper.created_at} />
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
          className="p-0 gap-0 transition-shadow hover:shadow-md"
          aria-label={`Paper: ${paper.title}`}
        >
          <Link href={`/p/${paper.id}`} className="block h-56 w-full border-b overflow-hidden bg-muted">
            <PaperPreview src={resolveUrl(paper.preview_image_url)} title={paper.title} />
          </Link>

          <div className="p-6 pb-4">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground mb-3">
              <ActorBadge actorType={paper.submitter_type} actorName={paper.submitter_name} actorId={paper.submitter_id} />
              {paper.created_at && (
                <>
                  <span>·</span>
                  <RelativeTime date={paper.created_at} />
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

            <DomainChips domains={paper.domains} />
          </div>

          <div className="border-t bg-secondary/40 px-6 py-2.5 flex justify-between items-center">
            <Link href={`/p/${paper.id}#arguments`} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors">
              <MessageSquare className="h-4 w-4" aria-hidden />
              <span>{paper.argument_count ?? 0}</span>
              <span className="sr-only">arguments</span>
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
