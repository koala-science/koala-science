'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, ChevronDown, ChevronUp, Code, FileText, MessageSquare, Scale } from 'lucide-react';

import { apiFetch } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { timeAgo } from '@/lib/utils';
import { VoteControls } from '@/components/paper/vote-controls';
import { PaperThread } from '@/components/paper/paper-thread';
import { ShareButton } from '@/components/paper/share-button';
import { VerdictSection } from '@/components/paper/verdict-section';
import { ActorBadge } from '@/components/shared/actor-badge';
import { LaTeX } from '@/components/shared/latex';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

type PaperRecord = {
  id: string;
  domains?: string[];
  submitter_id: string;
  submitter_type: string;
  submitter_name?: string;
  title: string;
  abstract: string;
  pdf_url?: string | null;
  github_repo_url?: string | null;
  net_score?: number;
  arxiv_id?: string | null;
};

const storageBase = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1').replace('/api/v1', '');

function resolvePdfUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.startsWith('/storage/') ? `${storageBase}${url}` : url;
}

type PaperRevisionRecord = {
  id: string;
  paper_id: string;
  version: number;
  title: string;
  abstract: string;
  pdf_url?: string | null;
  github_repo_url?: string | null;
  preview_image_url?: string | null;
  changelog?: string | null;
  created_by_id: string;
  created_by_type: string;
  created_by_name?: string | null;
  created_at: string;
  updated_at: string;
};

type RevisionDraft = {
  title: string;
  abstract: string;
  pdf_url: string;
  github_repo_url: string;
  changelog: string;
};

function revisionToDraft(revision: PaperRevisionRecord): RevisionDraft {
  return {
    title: revision.title,
    abstract: revision.abstract,
    pdf_url: revision.pdf_url ?? '',
    github_repo_url: revision.github_repo_url ?? '',
    changelog: '',
  };
}

export function PaperDetailClient({
  paper,
  comments,
  verdicts,
  revisions,
}: {
  paper: PaperRecord;
  comments: any[];
  verdicts: any[];
  revisions: PaperRevisionRecord[];
}) {
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const [revisionList, setRevisionList] = useState<PaperRevisionRecord[]>(revisions);
  const [selectedVersion, setSelectedVersion] = useState<number>(revisions[0]?.version ?? 1);
  const [draft, setDraft] = useState<RevisionDraft>(
    revisions[0]
      ? revisionToDraft(revisions[0])
      : {
          title: paper.title,
          abstract: paper.abstract,
          pdf_url: paper.pdf_url ?? '',
          github_repo_url: paper.github_repo_url ?? '',
          changelog: '',
        }
  );
  const [submittingRevision, setSubmittingRevision] = useState(false);
  const [revisionError, setRevisionError] = useState<string | null>(null);
  const [revisionSuccess, setRevisionSuccess] = useState<string | null>(null);
  const [revisionPanelOpen, setRevisionPanelOpen] = useState(false);

  const activeRevision =
    revisionList.find((revision) => revision.version === selectedVersion) ??
    revisionList[0] ?? {
      id: paper.id,
      paper_id: paper.id,
      version: 1,
      title: paper.title,
      abstract: paper.abstract,
      pdf_url: paper.pdf_url,
      github_repo_url: paper.github_repo_url,
      preview_image_url: null,
      changelog: null,
      created_by_id: paper.submitter_id,
      created_by_type: paper.submitter_type,
      created_by_name: paper.submitter_name,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

  const commentCount = comments.length;
  const latestVersion = revisionList[0]?.version ?? activeRevision.version;
  const canSubmitRevision = isAuthenticated && user?.actor_id === paper.submitter_id;
  const isViewingLatest = activeRevision.version === latestVersion;

  async function handleSubmitRevision(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmittingRevision(true);
    setRevisionError(null);
    setRevisionSuccess(null);

    try {
      const response = await apiFetch(`/papers/${paper.id}/revisions`, {
        method: 'POST',
        body: JSON.stringify({
          title: draft.title,
          abstract: draft.abstract,
          pdf_url: draft.pdf_url || null,
          github_repo_url: draft.github_repo_url || null,
          changelog: draft.changelog || null,
        }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || 'Failed to submit revision');
      }

      const newRevision: PaperRevisionRecord = await response.json();
      setRevisionList((current) => [newRevision, ...current]);
      setSelectedVersion(newRevision.version);
      setDraft(revisionToDraft(newRevision));
      setRevisionSuccess(`Revision v${newRevision.version} submitted.`);
      setRevisionPanelOpen(true);
    } catch (error) {
      setRevisionError(error instanceof Error ? error.message : 'Failed to submit revision');
    } finally {
      setSubmittingRevision(false);
    }
  }

  const activePdfUrl = resolvePdfUrl(activeRevision.pdf_url);

  return (
    <main className="max-w-2xl mx-auto" role="main" aria-label="Paper Detail">
      <div className="inline-flex items-center gap-1.5 text-sm text-muted-foreground mb-4">
        <ArrowLeft className="h-4 w-4" />
        {(paper.domains || []).map((d: string) => (
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
        {activePdfUrl && (
          <>
            <span>·</span>
            <a href={activePdfUrl} target="_blank" rel="noreferrer" className="hover:text-foreground inline-flex items-center gap-1" data-agent-action="download-pdf">
              <FileText className="h-3 w-3" /> PDF
            </a>
          </>
        )}
        {activeRevision.github_repo_url && (
          <>
            <span>·</span>
            <a href={activeRevision.github_repo_url} target="_blank" rel="noreferrer" className="hover:text-foreground inline-flex items-center gap-1" data-agent-action="view-code">
              <Code className="h-3 w-3" /> Code
            </a>
          </>
        )}
      </div>

      <h1 className="text-2xl font-bold leading-tight mb-3">{activeRevision.title}</h1>
      <p className="text-muted-foreground leading-relaxed mb-4"><LaTeX>{activeRevision.abstract}</LaTeX></p>

      {!isViewingLatest && (
        <div className="mb-4 rounded-lg border border-amber-300/60 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Viewing revision v{activeRevision.version}. The latest revision is v{latestVersion}.
          <button
            type="button"
            onClick={() => setSelectedVersion(latestVersion)}
            className="ml-2 underline underline-offset-4"
          >
            Switch to latest
          </button>
        </div>
      )}

      <div className="mb-5">
        <button
          type="button"
          onClick={() => setRevisionPanelOpen((current) => !current)}
          className="inline-flex items-center gap-2 rounded-full border bg-background px-3 py-2 text-sm text-muted-foreground hover:border-foreground/40 hover:text-foreground transition-colors"
        >
          <FileText className="h-4 w-4" />
          <span className="font-medium">Revisions</span>
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-foreground">
            {revisionList.length}
          </span>
          {revisionPanelOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>

        {revisionPanelOpen && (
          <section className="mt-3 rounded-xl border bg-muted/20 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold">Revision History</h2>
                <p className="text-xs text-muted-foreground">The paper page, votes, and thread stay attached to the canonical paper while content can evolve across versions.</p>
              </div>
              <span className="text-xs text-muted-foreground">{revisionList.length} version{revisionList.length === 1 ? '' : 's'}</span>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {revisionList.map((revision) => (
                <button
                  key={revision.id}
                  type="button"
                  onClick={() => setSelectedVersion(revision.version)}
                  className={revision.version === activeRevision.version
                    ? 'rounded-full border border-foreground bg-foreground px-3 py-1.5 text-xs font-medium text-background'
                    : 'rounded-full border px-3 py-1.5 text-xs text-muted-foreground hover:border-foreground/40 hover:text-foreground'}
                >
                  v{revision.version} · {timeAgo(revision.created_at)}
                </button>
              ))}
            </div>

            <div className="mt-4 rounded-lg border bg-background px-4 py-3">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="font-medium text-foreground">v{activeRevision.version}</span>
                <span>·</span>
                <ActorBadge
                  actorType={activeRevision.created_by_type}
                  actorName={activeRevision.created_by_name ?? undefined}
                  actorId={activeRevision.created_by_id}
                />
                <span>·</span>
                <span>{timeAgo(activeRevision.created_at)}</span>
              </div>
              {activeRevision.changelog && (
                <p className="mt-2 text-sm text-muted-foreground">{activeRevision.changelog}</p>
              )}
            </div>

            {canSubmitRevision && (
              <form onSubmit={handleSubmitRevision} className="mt-4 space-y-3 border-t pt-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold">Submit Revision</h3>
                    <p className="text-xs text-muted-foreground">This creates a new version and updates the canonical paper snapshot used by the rest of the site.</p>
                  </div>
                  <span className="text-xs text-muted-foreground">Next: v{latestVersion + 1}</span>
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="revision-title" className="text-sm font-medium">Title</label>
                  <Input
                    id="revision-title"
                    value={draft.title}
                    onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
                    required
                  />
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="revision-abstract" className="text-sm font-medium">Abstract</label>
                  <Textarea
                    id="revision-abstract"
                    value={draft.abstract}
                    onChange={(event) => setDraft((current) => ({ ...current, abstract: event.target.value }))}
                    className="min-h-[120px]"
                    required
                  />
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="revision-pdf" className="text-sm font-medium">PDF URL</label>
                  <Input
                    id="revision-pdf"
                    type="url"
                    value={draft.pdf_url}
                    onChange={(event) => setDraft((current) => ({ ...current, pdf_url: event.target.value }))}
                  />
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="revision-github" className="text-sm font-medium">GitHub Repo URL</label>
                  <Input
                    id="revision-github"
                    type="url"
                    value={draft.github_repo_url}
                    onChange={(event) => setDraft((current) => ({ ...current, github_repo_url: event.target.value }))}
                  />
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="revision-changelog" className="text-sm font-medium">Changelog</label>
                  <Textarea
                    id="revision-changelog"
                    value={draft.changelog}
                    onChange={(event) => setDraft((current) => ({ ...current, changelog: event.target.value }))}
                    placeholder="Summarize what changed in this revision."
                    className="min-h-[90px]"
                  />
                </div>

                {revisionError && <p className="text-sm text-red-600">{revisionError}</p>}
                {revisionSuccess && <p className="text-sm text-emerald-700">{revisionSuccess}</p>}

                <div className="flex justify-end">
                  <Button type="submit" disabled={submittingRevision}>
                    {submittingRevision ? 'Submitting...' : 'Submit Revision'}
                  </Button>
                </div>
              </form>
            )}
          </section>
        )}
      </div>

      {activePdfUrl && (
        <div className="w-full h-[500px] border rounded-lg overflow-hidden bg-muted/30 mb-3">
          <iframe src={activePdfUrl} className="w-full h-full" title="Paper PDF Viewer" />
        </div>
      )}

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

      <div id="verdicts">
        <VerdictSection verdicts={verdicts} />
      </div>

      <div id="thread">
        <PaperThread paperId={paper.id} comments={comments} />
      </div>
    </main>
  );
}
