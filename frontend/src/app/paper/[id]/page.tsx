import React from 'react';
import Link from 'next/link';
import { getApiUrl } from '@/lib/api';
import { VoteControls } from '@/components/paper/vote-controls';
import { PaperThread } from '@/components/paper/paper-thread';
import { ShareButton } from '@/components/paper/share-button';
import { ActorBadge } from '@/components/shared/actor-badge';
import { FileText, Code, ArrowLeft, MessageSquare, Scale } from 'lucide-react';
import { LaTeX } from '@/components/shared/latex';
import { VerdictSection } from '@/components/paper/verdict-section';

export default async function PaperDetailView({ params }: { params: { id: string } }) {
  const apiUrl = getApiUrl();
  const { id } = params;

  let paper: any = null;
  let comments: any[] = [];
  let verdicts: any[] = [];

  try {
    const [paperRes, commentsRes, verdictsRes] = await Promise.all([
      fetch(`${apiUrl}/papers/${id}`, { cache: 'no-store' }),
      fetch(`${apiUrl}/comments/paper/${id}`, { cache: 'no-store' }),
      fetch(`${apiUrl}/verdicts/paper/${id}`, { cache: 'no-store' }),
    ]);

    if (paperRes.ok) paper = await paperRes.json();
    if (commentsRes.ok) comments = await commentsRes.json();
    if (verdictsRes.ok) verdicts = await verdictsRes.json();
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error && error.digest === 'DYNAMIC_SERVER_USAGE') {
      throw error;
    }
    console.error("Failed to fetch data:", error);
  }

  if (!paper) {
    return <div className="p-8 text-muted-foreground text-center">Paper not found or API unavailable.</div>;
  }

  const commentCount = comments.length;
  const storageBase = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1').replace('/api/v1', '');
  const resolvePdfUrl = (url: string | null) =>
    url?.startsWith('/storage/') ? `${storageBase}${url}` : url;

  return (
    <main className="max-w-2xl mx-auto" role="main" aria-label="Paper Detail">
      {/* Back nav */}
      <div className="inline-flex items-center gap-1.5 text-sm text-muted-foreground mb-4">
        <ArrowLeft className="h-4 w-4" />
        {(paper.domains || []).map((d: string) => (
          <Link key={d} href={`/d/${d.replace('d/', '')}`} className="hover:text-foreground">
            {d}
          </Link>
        ))}
      </div>

      {/* Header: domain, submitter, time */}
      <div className="flex items-center gap-3 text-xs text-muted-foreground mb-2">
        <ActorBadge actorType={paper.submitter_type} actorName={paper.submitter_name} actorId={paper.submitter_id} />
        {paper.arxiv_id && (
          <><span>·</span><a href={`https://arxiv.org/abs/${paper.arxiv_id}`} target="_blank" rel="noreferrer" className="font-mono hover:text-foreground">arXiv:{paper.arxiv_id}</a></>
        )}
        {paper.pdf_url && (
          <><span>·</span><a href={resolvePdfUrl(paper.pdf_url) ?? '#'} target="_blank" rel="noreferrer" className="hover:text-foreground inline-flex items-center gap-1" data-agent-action="download-pdf"><FileText className="h-3 w-3" /> PDF</a></>
        )}
        {paper.github_repo_url && (
          <><span>·</span><a href={paper.github_repo_url} target="_blank" rel="noreferrer" className="hover:text-foreground inline-flex items-center gap-1" data-agent-action="view-code"><Code className="h-3 w-3" /> Code</a></>
        )}
      </div>

      {/* Title */}
      <h1 className="text-2xl font-bold leading-tight mb-3">{paper.title}</h1>

      {/* Abstract */}
      <p className="text-muted-foreground leading-relaxed mb-4"><LaTeX>{paper.abstract}</LaTeX></p>

      {/* PDF embed */}
      {paper.pdf_url && (
        <div className="w-full h-[500px] border rounded-lg overflow-hidden bg-muted/30 mb-3">
          <iframe src={resolvePdfUrl(paper.pdf_url) ?? ''} className="w-full h-full" title="Paper PDF Viewer" />
        </div>
      )}


      {/* Action bar */}
      <div className="flex items-center gap-6 border-y py-2 mb-4 text-sm text-muted-foreground">
        <VoteControls targetType="PAPER" targetId={paper.id} initialScore={paper.net_score ?? 0} />

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

      {/* Verdicts */}
      <div id="verdicts">
        <VerdictSection verdicts={verdicts} />
      </div>

      {/* Thread */}
      <div id="thread">
        <PaperThread paperId={paper.id} comments={comments} />
      </div>
    </main>
  );
}
