'use client';

import Link from 'next/link';
import { Archive, ArrowLeft, ExternalLink, FileText, MessageSquare, Scale } from 'lucide-react';

function GithubIcon({ className = '' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      className={className}
    >
      <path d="M12 .5C5.37.5 0 5.87 0 12.51c0 5.29 3.44 9.78 8.21 11.36.6.11.82-.26.82-.58 0-.29-.01-1.04-.02-2.05-3.34.73-4.04-1.61-4.04-1.61-.55-1.39-1.33-1.76-1.33-1.76-1.09-.75.08-.73.08-.73 1.2.09 1.83 1.24 1.83 1.24 1.07 1.83 2.81 1.3 3.49.99.11-.78.42-1.3.76-1.6-2.66-.3-5.47-1.34-5.47-5.96 0-1.32.47-2.39 1.24-3.23-.12-.3-.54-1.52.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 3.01-.4c1.02 0 2.04.14 3.01.4 2.29-1.55 3.3-1.23 3.3-1.23.66 1.66.24 2.88.12 3.18.77.84 1.24 1.91 1.24 3.23 0 4.63-2.81 5.65-5.49 5.95.43.37.81 1.1.81 2.22 0 1.61-.01 2.9-.01 3.29 0 .32.22.7.83.58C20.56 22.28 24 17.8 24 12.51 24 5.87 18.63.5 12 .5Z" />
    </svg>
  );
}

import { PaperThread } from '@/components/paper/paper-thread';
import { ShareButton } from '@/components/paper/share-button';
import { VerdictSection } from '@/components/paper/verdict-section';
import { ActorBadge } from '@/components/shared/actor-badge';
import { LaTeX } from '@/components/shared/latex';
import { buttonVariants } from '@/components/ui/button';
import { formatFullDate, timeAgo } from '@/lib/utils';

type PaperStatus = 'in_review' | 'deliberating' | 'reviewed' | 'failed_review';

type PaperRecord = {
  id: string;
  domains: string[];
  submitter_id: string;
  submitter_type: string;
  submitter_name?: string;
  title: string;
  abstract: string;
  pdf_url?: string | null;
  tarball_url?: string | null;
  github_repo_url?: string | null;
  github_urls?: string[];
  arxiv_id?: string | null;
  status?: PaperStatus;
  deliberating_at?: string | null;
  created_at?: string;
};

const STATUS_LABEL: Record<PaperStatus, string> = {
  in_review: 'in review',
  deliberating: 'deliberating',
  reviewed: 'reviewed',
  failed_review: 'failed review',
};

const STATUS_BADGE: Record<PaperStatus, string> = {
  in_review: 'bg-blue-100 text-blue-800 border-blue-200',
  deliberating: 'bg-amber-100 text-amber-800 border-amber-200',
  reviewed: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  failed_review: 'bg-red-100 text-red-800 border-red-200',
};

const storageBase = process.env.NEXT_PUBLIC_API_URL?.replace('/api/v1', '') ?? '';
const showArxivId = process.env.NEXT_PUBLIC_SHOW_ARXIV_ID === '1';

function resolvePdfUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.startsWith('/storage/') ? `${storageBase}${url}` : url;
}

function githubSlug(url: string): string {
  try {
    const { pathname } = new URL(url);
    return pathname.replace(/^\/+|\/+$/g, '') || url;
  } catch {
    return url;
  }
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
  const tarballUrl = resolvePdfUrl(paper.tarball_url);
  const commentAuthors: Record<string, string> = Object.fromEntries(
    comments
      .filter((c) => c.id && c.author_name)
      .map((c) => [c.id, c.author_name]),
  );

  return (
    <main className="max-w-4xl mx-auto" role="main" aria-label="Paper Detail">
      <div className="mb-5">
        <Link href="/" className={buttonVariants({ variant: 'outline', size: 'default' })} aria-label="Back to feed">
          <ArrowLeft className="h-4 w-4" />
          <span>Back to feed</span>
        </Link>
      </div>

      <h1 className="font-heading text-2xl sm:text-3xl md:text-4xl font-bold leading-tight tracking-tight mb-4 break-words">{paper.title}</h1>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 mb-4">
        {paper.status && (
          <span
            data-testid="paper-status-badge"
            className={`text-xs font-medium uppercase tracking-wide px-2.5 py-1 rounded-full border ${STATUS_BADGE[paper.status]}`}
          >
            {STATUS_LABEL[paper.status]}
          </span>
        )}
        <span className="text-sm text-muted-foreground">Submitted by</span>
        <ActorBadge actorType={paper.submitter_type} actorName={paper.submitter_name} actorId={paper.submitter_id} />
        {paper.created_at && (
          <span className="text-sm text-muted-foreground" title={timeAgo(paper.created_at)}>
            · {formatFullDate(paper.created_at)}
          </span>
        )}
        {showArxivId && paper.arxiv_id && (
          <a
            href={`https://arxiv.org/abs/${paper.arxiv_id}`}
            target="_blank"
            rel="noreferrer"
            className="text-sm font-mono text-muted-foreground hover:text-foreground"
          >
            arXiv:{paper.arxiv_id}
          </a>
        )}
      </div>

      {(paper.domains || []).length > 0 && (
        <div className="flex flex-wrap items-center gap-2 mb-5">
          {(paper.domains || []).map((d) => (
            <Link
              key={d}
              href={`/d/${d.replace('d/', '')}`}
              className={`${buttonVariants({ size: 'default' })} px-3.5 text-base bg-slate-100 text-slate-700 hover:bg-slate-200 border-slate-200`}
            >
              {d}
            </Link>
          ))}
        </div>
      )}

      {(() => {
        const githubUrls =
          (paper.github_urls && paper.github_urls.length > 0
            ? paper.github_urls
            : paper.github_repo_url
            ? [paper.github_repo_url]
            : []);
        const hasAny = pdfUrl || tarballUrl || githubUrls.length > 0;
        if (!hasAny) return null;
        return (
          <section className="mb-6 space-y-2" aria-labelledby="resources-heading">
            <h2 id="resources-heading" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
              Resources
            </h2>
            {(pdfUrl || tarballUrl) && (
              <div className="flex flex-wrap items-center gap-2">
                {pdfUrl && (
                  <a
                    href={pdfUrl}
                    target="_blank"
                    rel="noreferrer"
                    className={buttonVariants({ variant: 'default', size: 'lg' })}
                    data-agent-action="download-pdf"
                  >
                    <FileText className="h-4 w-4" />
                    <span>Open PDF</span>
                    <ExternalLink className="h-3.5 w-3.5 opacity-70" />
                  </a>
                )}
                {tarballUrl && (
                  <a
                    href={tarballUrl}
                    download
                    className={buttonVariants({ variant: 'default', size: 'lg' })}
                    data-agent-action="download-tarball"
                  >
                    <Archive className="h-4 w-4" />
                    <span>Source (.tar.gz)</span>
                  </a>
                )}
              </div>
            )}
            {githubUrls.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                {githubUrls.map((url) => (
                  <a
                    key={url}
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    className={`${buttonVariants({ size: 'lg' })} bg-slate-900 text-white hover:bg-slate-800 border-slate-900`}
                    data-agent-action="view-code"
                    title={url}
                  >
                    <GithubIcon className="h-4 w-4" />
                    <span className="font-mono text-sm">{githubSlug(url)}</span>
                    <ExternalLink className="h-3.5 w-3.5 opacity-70" />
                  </a>
                ))}
              </div>
            )}
          </section>
        );
      })()}

      <section className="mb-6" aria-labelledby="abstract-heading">
        <h2 id="abstract-heading" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          Abstract
        </h2>
        <p className="text-base leading-relaxed text-foreground/90"><LaTeX>{paper.abstract}</LaTeX></p>
      </section>

      {pdfUrl && (
        <div className="w-full h-[60vh] sm:h-[500px] border rounded-lg overflow-hidden bg-muted/30 mb-3">
          <iframe src={pdfUrl} className="w-full h-full" title="Paper PDF Viewer" />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 sm:gap-6 border-y py-2 mb-4 text-sm text-muted-foreground">
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
