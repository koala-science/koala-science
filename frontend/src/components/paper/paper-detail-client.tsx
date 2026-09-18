'use client';

import Link from 'next/link';
import { Archive, ArrowLeft, ExternalLink, FileText, MessageSquare } from 'lucide-react';

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

import { ShareButton } from '@/components/paper/share-button';
import { ArgumentSection, type ArgumentRecord } from '@/components/paper/argument-section';
import { ActorBadge } from '@/components/shared/actor-badge';
import { DomainChips } from '@/components/shared/domain-chip';
import { LaTeX } from '@/components/shared/latex';
import { PageShell, SectionLabel } from '@/components/shared/page';
import { buttonVariants } from '@/components/ui/button';
import { formatFullDate, timeAgo } from '@/lib/utils';


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
  created_at?: string;
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
  arguments: argumentList,
}: {
  paper: PaperRecord;
  arguments: ArgumentRecord[];
}) {
  const pdfUrl = resolvePdfUrl(paper.pdf_url);
  const tarballUrl = resolvePdfUrl(paper.tarball_url);

  return (
    <PageShell width="default">
      <div className="mb-5">
        <Link href="/papers" className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
          <ArrowLeft className="h-4 w-4" />
          <span>Back to feed</span>
        </Link>
      </div>

      <h1 className="font-heading text-2xl sm:text-3xl md:text-4xl font-bold leading-tight tracking-tight mb-4 break-words">{paper.title}</h1>

      <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-muted-foreground">
        <span className="inline-flex items-center gap-2">
          Submitted by
          <ActorBadge actorType={paper.submitter_type} actorName={paper.submitter_name} actorId={paper.submitter_id} />
        </span>
        {paper.created_at && (
          <time dateTime={paper.created_at} title={timeAgo(paper.created_at)} suppressHydrationWarning>
            {formatFullDate(paper.created_at)}
          </time>
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

      <DomainChips domains={paper.domains} className="mb-6" />

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
            <SectionLabel id="resources-heading">Resources</SectionLabel>
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
                    className={buttonVariants({ variant: 'outline', size: 'lg' })}
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
        <SectionLabel id="abstract-heading">Abstract</SectionLabel>
        <p className="text-base leading-relaxed text-foreground/90"><LaTeX>{paper.abstract}</LaTeX></p>
      </section>

      {pdfUrl && (
        <div className="w-full h-[60vh] sm:h-[500px] border rounded-lg overflow-hidden bg-muted/30 mb-3">
          <iframe src={pdfUrl} className="w-full h-full" title="Paper PDF Viewer" />
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-y py-2 text-xs text-muted-foreground">
        <a href="#arguments" className="inline-flex items-center gap-1 hover:text-foreground">
          <MessageSquare className="h-3.5 w-3.5" />
          <span>{argumentList.length} argument{argumentList.length !== 1 ? 's' : ''}</span>
        </a>

        <ShareButton />
      </div>

      <div id="arguments">
        <ArgumentSection arguments={argumentList} paperId={paper.id} />
      </div>
    </PageShell>
  );
}
