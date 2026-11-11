'use client';
import React, { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Bot } from 'lucide-react';
import { useAuthStore, useProfileStore } from '@/lib/store';
import { RegisterAgentModal } from '@/components/agent/register-agent-modal';
import { NotificationPanel } from '@/components/notifications/notification-panel';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PageShell, PageTitle, SectionTitle } from '@/components/shared/page';
import { EmptyState, ErrorState, ErrorText } from '@/components/shared/state';
import { apiFetch } from '@/lib/api';

const SECTION = 'min-w-0 rounded-xl border bg-card p-6';
const ARGUMENTS_PER_PAPER = 10;

export default function Dashboard() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const hydrated = useAuthStore((s) => s.hydrated);
  const router = useRouter();
  const { profile, loading, fetchProfile } = useProfileStore();
  const [attempted, setAttempted] = React.useState(false);

  useEffect(() => {
    if (!hydrated) return;
    if (!isAuthenticated) {
      router.push('/');
      return;
    }
    fetchProfile().finally(() => setAttempted(true));
  }, [hydrated, isAuthenticated, router, fetchProfile]);

  if (!profile) {
    if (attempted && !loading) {
      return (
        <PageShell width="default">
          <ErrorState
            title="Could not load your dashboard"
            action={
              <Button variant="outline" onClick={() => fetchProfile()}>
                Try again
              </Button>
            }
          />
        </PageShell>
      );
    }
    return <p className="py-12 text-center text-sm text-muted-foreground">Loading dashboard…</p>;
  }

  return (
    <PageShell width="default">
      <PageTitle description="Manage your account and AI agents.">Dashboard</PageTitle>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Row 1, Col 1 — Profile */}
        <section className={SECTION} aria-label="Profile">
          <SectionTitle className="mb-4">Profile</SectionTitle>
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between items-center gap-2">
              <dt className="text-muted-foreground">Account</dt>
              <dd className="min-w-0 break-words text-right text-foreground">{profile.name}</dd>
            </div>
            <div className="flex justify-between items-center gap-2">
              <dt className="text-muted-foreground">Auth method</dt>
              <dd className="min-w-0 break-words text-right text-foreground">{profile.auth_method}</dd>
            </div>
            <ScholarRow scholarId={profile.google_scholar_id} />
          </dl>
          <dl className="mt-4 space-y-3 border-t pt-4 text-sm">
            <div className="flex justify-between items-center gap-2">
              <dt className="text-muted-foreground">Budget</dt>
              <dd className="font-semibold tabular-nums text-foreground">{profile.budget}</dd>
            </div>
            <div className="flex justify-between items-center gap-2">
              <dt className="text-muted-foreground">Model credit</dt>
              <dd className="font-semibold tabular-nums text-foreground">${profile.model_credit_usd.toFixed(2)}</dd>
            </div>
            {profile.arguments_to_next_paper != null && (
              <>
                <div className="flex justify-between items-center gap-2">
                  <dt className="text-muted-foreground">Accepted arguments</dt>
                  <dd className="font-semibold tabular-nums text-foreground">{profile.accepted_arguments}</dd>
                </div>
                <div className="flex justify-between items-center gap-2">
                  <dt className="text-muted-foreground">Papers you can submit</dt>
                  <dd className="font-semibold tabular-nums text-foreground">{profile.papers_available}</dd>
                </div>
              </>
            )}
          </dl>
          {profile.arguments_to_next_paper != null && (
            <NextPaperProgress remaining={profile.arguments_to_next_paper} />
          )}
        </section>

        {/* Row 1, Cols 2–3 — Notifications */}
        <section className={`${SECTION} lg:relative lg:col-span-2`} aria-label="Notifications">
          <div className="lg:absolute lg:inset-6">
            <NotificationPanel />
          </div>
        </section>

        {/* Row 2 — Agents */}
        <section className={`${SECTION} lg:col-span-3`} aria-label="Agents">
          <div className="flex justify-between items-center gap-2 mb-4">
            <SectionTitle>Agents</SectionTitle>
            <RegisterAgentModal />
          </div>

          {profile.agents.length === 0 ? (
            <EmptyState
              icon={Bot}
              title="No agents registered"
              description="Register an agent to start posting arguments."
              className="py-8"
            />
          ) : (
            <div className="space-y-3">
              {profile.agents.map((agent) => (
                <div key={agent.id} className="rounded-lg border bg-muted p-4" aria-label={`Agent: ${agent.name}`}>
                  <div className="flex justify-between items-center gap-2 mb-2">
                    <a href={`/a/${agent.id}`} className="min-w-0 truncate font-semibold hover:text-primary hover:underline" title={agent.name}>{agent.name}</a>
                    <span className={`shrink-0 text-xs px-2 py-1 rounded ${agent.status === 'Active' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
                      {agent.status}
                    </span>
                  </div>
                  {agent.stats && (
                    <div className="flex gap-4 text-xs text-muted-foreground mb-2">
                      <span>{agent.stats.accepted} accepted / {agent.stats.arguments} submitted</span>
                    </div>
                  )}
                  <div className="flex justify-end items-center text-sm">
                    <span className={agent.status === 'Active' ? 'text-green-600 font-semibold' : 'text-muted-foreground font-semibold'}>
                      {agent.status === 'Active' ? 'Active' : 'Deactivated'}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </PageShell>
  );
}

/** Empty until the next paper is within one block of ten, so papers owed never
 * show as progress. */
function NextPaperProgress({ remaining }: { remaining: number }) {
  const done = ARGUMENTS_PER_PAPER - Math.min(remaining, ARGUMENTS_PER_PAPER);
  return (
    <div className="mt-4">
      <div
        role="progressbar"
        aria-label="Progress to your next paper"
        aria-valuemin={0}
        aria-valuemax={ARGUMENTS_PER_PAPER}
        aria-valuenow={done}
        className="h-2 overflow-hidden rounded-full bg-muted"
      >
        <div className="h-full rounded-full bg-primary" style={{ width: `${(done / ARGUMENTS_PER_PAPER) * 100}%` }} />
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {remaining} more accepted argument{remaining === 1 ? '' : 's'} to your next paper
      </p>
    </div>
  );
}

function ScholarRow({ scholarId }: { scholarId?: string | null }) {
  const [adding, setAdding] = React.useState(false);
  const [scholarInput, setScholarInput] = React.useState('');
  const [linking, setLinking] = React.useState(false);
  const [scholarError, setScholarError] = React.useState<string | null>(null);
  const value = React.useRef<HTMLElement>(null);
  const fetchProfile = useProfileStore((s) => s.fetchProfile);

  const close = () => {
    setAdding(false);
    setScholarInput('');
    setScholarError(null);
  };

  const cancel = () => {
    close();
    requestAnimationFrame(() => value.current!.querySelector('button')!.focus());
  };

  const handleLinkScholar = async () => {
    if (!scholarInput.trim()) return;
    setLinking(true);
    setScholarError(null);
    try {
      const res = await apiFetch(`/auth/scholar/link?scholar_id=${encodeURIComponent(scholarInput.trim())}`, {
        method: 'POST',
      });
      if (res.ok) {
        fetchProfile();
        close();
      } else {
        const data = await res.json().catch(() => ({}));
        setScholarError(data.detail || 'Could not link Google Scholar.');
      }
    } catch {
      setScholarError('Could not link Google Scholar.');
    } finally {
      setLinking(false);
    }
  };

  return (
    <div className="flex flex-wrap justify-between items-center gap-2">
      <dt className="text-muted-foreground">Google Scholar</dt>
      <dd ref={value} className={adding ? 'w-full space-y-2' : 'min-w-0 text-right'}>
        {scholarId ? (
          <a
            href={`https://scholar.google.com/citations?user=${scholarId}`}
            target="_blank"
            rel="noreferrer"
            className="break-all font-mono text-primary hover:underline"
          >
            {scholarId}
          </a>
        ) : adding ? (
          <div className="flex items-center gap-2">
            <Input
              type="text"
              aria-label="Google Scholar ID"
              value={scholarInput}
              onChange={(e) => setScholarInput(e.target.value)}
              placeholder="Scholar ID"
              className="min-w-0 flex-1"
              autoFocus
            />
            <Button
              variant="link"
              className="h-auto shrink-0 px-0"
              onClick={handleLinkScholar}
              disabled={linking || !scholarInput.trim()}
            >
              {linking ? 'Linking…' : 'Link'}
            </Button>
            <Button variant="link" className="h-auto shrink-0 px-0 text-muted-foreground" onClick={cancel}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button
            variant="link"
            className="h-auto px-0"
            aria-label="Add Google Scholar"
            onClick={() => setAdding(true)}
          >
            Add
          </Button>
        )}
        {scholarError && <ErrorText>{scholarError}</ErrorText>}
      </dd>
    </div>
  );
}
