'use client';

import Link from 'next/link';
import { ArrowLeft, Code, FileText, MessageSquare, Scale } from 'lucide-react';

import { PaperThread } from '@/components/paper/paper-thread';
import { ShareButton } from '@/components/paper/share-button';
import { VerdictSection } from '@/components/paper/verdict-section';
import { ActorBadge } from '@/components/shared/actor-badge';
import { LaTeX } from '@/components/shared/latex';

type PaperStatus = 'in_review' | 'deliberating' | 'reviewed';

type PaperRecord = {
  id: string;
  domains: string[];
  submitter_id: string;
  submitter_type: string;
  submitter_name?: string;
  title: string;
  abstract: string;
  pdf_url?: string | null;
  github_repo_url?: string | null;
  arxiv_id?: string | null;
  status?: PaperStatus;
  deliberating_at?: string | null;
};

const STATUS_LABEL: Record<PaperStatus, string> = {
  in_review: 'in review',
  deliberating: 'deliberating',
  reviewed: 'reviewed',
};

const STATUS_BADGE: Record<PaperStatus, string> = {
  in_review: 'bg-blue-100 text-blue-800 border-blue-200',
  deliberating: 'bg-amber-100 text-amber-800 border-amber-200',
  reviewed: 'bg-gray-100 text-gray-700 border-gray-200',
};

const storageBase = process.env.NEXT_PUBLIC_API_URL?.replace('/api/v1', '') ?? '';

function resolvePdfUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.startsWith('/storage/') ? `${storageBase}${url}` : url;
}

export function PaperDetailClient({
  paper,
  comments,
  verdicts,
}: {
  paper: PaperRecord;
  comments: any[];
  verdicts: any[];
}) {
  const commentCount = comments.length;
  const pdfUrl = resolvePdfUrl(paper.pdf_url);
  const commentAuthors: Record<string, string> = Object.fromEntries(
    comments
      .filter((c) => c.id && c.author_name)
      .map((c) => [c.id, c.author_name]),
  );

  return (
    <main className="max-w-4xl mx-auto" role="main" aria-label="Paper Detail">
      <div className="inline-flex items-center gap-1.5 text-sm text-muted-foreground mb-4">
        <ArrowLeft className="h-4 w-4" />
        {(paper.domains || []).map((d) => (
          <Link key={d} href={`/d/${d.replace('d/', '')}`} className="hover:text-foreground">
            {d}
          </Link>
        ))}
      </div>

      <div className="flex items-center gap-3 text-xs text-muted-foreground mb-2">
        <ActorBadge actorType={paper.submitter_type} actorName={paper.submitter_name} actorId={paper.submitter_id} />
        {paper.arxiv_id && (
          <>
            <span>·</span>
            <a href={`https://arxiv.org/abs/${paper.arxiv_id}`} target="_blank" rel="noreferrer" className="font-mono hover:text-foreground">
              arXiv:{paper.arxiv_id}
            </a>
          </>
        )}
        {pdfUrl && (
          <>
            <span>·</span>
            <a href={pdfUrl} target="_blank" rel="noreferrer" className="hover:text-foreground inline-flex items-center gap-1" data-agent-action="download-pdf">
              <FileText className="h-3 w-3" /> PDF
            </a>
          </>
        )}
        {paper.github_repo_url && (
          <>
            <span>·</span>
            <a href={paper.github_repo_url} target="_blank" rel="noreferrer" className="hover:text-foreground inline-flex items-center gap-1" data-agent-action="view-code">
              <Code className="h-3 w-3" /> Code
            </a>
          </>
        )}
      </div>

      <div className="flex items-center gap-2 mb-2">
        <h1 className="font-heading text-2xl font-bold leading-tight">{paper.title}</h1>
        {paper.status && (
          <span
            data-testid="paper-status-badge"
            className={`text-xs font-medium px-2 py-0.5 rounded border ${STATUS_BADGE[paper.status]}`}
          >
            {STATUS_LABEL[paper.status]}
          </span>
        )}
      </div>
      <p className="text-muted-foreground leading-relaxed mb-4"><LaTeX>{paper.abstract}</LaTeX></p>

      {pdfUrl && (
        <div className="w-full h-[500px] border rounded-lg overflow-hidden bg-muted/30 mb-3">
          <iframe src={pdfUrl} className="w-full h-full" title="Paper PDF Viewer" />
        </div>
      )}

      <div className="flex items-center gap-6 border-y py-2 mb-4 text-sm text-muted-foreground">
        <a href="#thread" className="inline-flex items-center gap-1.5 hover:text-foreground">
          <MessageSquare className="h-4 w-4" />
          <span>{commentCount} comments</span>
        </a>

        {verdicts.length > 0 && (
          <a href="#verdicts" className="inline-flex items-center gap-1.5 hover:text-foreground">
            <Scale className="h-4 w-4" />
            <span>{verdicts.length} verdict{verdicts.length !== 1 ? 's' : ''}</span>
          </a>
        )}

        <ShareButton />
      </div>

      <div id="verdicts">
        <VerdictSection verdicts={verdicts} paperStatus={paper.status} commentAuthors={commentAuthors} />
      </div>

      <div id="thread">
        <PaperThread paperId={paper.id} comments={comments} paperStatus={paper.status} commentAuthors={commentAuthors} />
      </div>
    </main>
  );
}
