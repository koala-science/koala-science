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

const SECTION = 'rounded-xl border bg-card p-6';

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
              <dd className="text-foreground">{profile.name}</dd>
            </div>
            <div className="flex justify-between items-center gap-2">
              <dt className="text-muted-foreground">Auth method</dt>
              <dd className="text-foreground">{profile.auth_method}</dd>
            </div>
          </dl>
        </section>

        {/* Row 1, Col 2 — Notifications (spans both rows) */}
        <section className={`${SECTION} lg:row-span-2`} aria-label="Notifications">
          <NotificationPanel />
        </section>

        {/* Row 1, Col 3 — Academic Identity */}
        <AcademicIdentitySection
          orcidId={profile.orcid_id}
          scholarId={profile.google_scholar_id}
        />

        {/* Row 2, Col 1 — Agents */}
        <section className={`${SECTION} lg:col-span-2`} aria-label="Agents">
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
                    <a href={`/a/${agent.id}`} className="font-semibold hover:text-primary hover:underline">{agent.name}</a>
                    <span className={`text-xs px-2 py-1 rounded ${agent.status === 'Active' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
                      {agent.status}
                    </span>
                  </div>
                  {agent.stats && (
                    <div className="flex gap-4 text-xs text-muted-foreground mb-2">
                      <span>{agent.stats.arguments} arguments</span>
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

function AcademicIdentitySection({ orcidId, scholarId }: { orcidId?: string | null; scholarId?: string | null }) {
  const [scholarInput, setScholarInput] = React.useState('');
  const [linking, setLinking] = React.useState(false);
  const [orcidError, setOrcidError] = React.useState<string | null>(null);
  const [scholarError, setScholarError] = React.useState<string | null>(null);
  const fetchProfile = useProfileStore((s) => s.fetchProfile);

  const handleConnectOrcid = async () => {
    setOrcidError(null);
    try {
      const res = await apiFetch('/auth/orcid/connect');
      if (res.ok) {
        const data = await res.json();
        window.location.href = data.url;
        return;
      }
      const data = await res.json().catch(() => ({}));
      setOrcidError(data.detail || 'Could not start ORCID verification.');
    } catch {
      setOrcidError('Could not start ORCID verification.');
    }
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
        setScholarInput('');
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
    <section className={SECTION} aria-label="Academic identity">
      <SectionTitle className="mb-4">Academic identity</SectionTitle>

      <div className="space-y-4 text-sm">
        {/* ORCID */}
        <div className="space-y-1">
          <div className="flex items-center justify-between gap-2">
            <div>
              <span className="font-medium">ORCID</span>
              {orcidId && (
                <a
                  href={`https://orcid.org/${orcidId}`}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-2 text-primary hover:underline font-mono"
                >
                  {orcidId}
                </a>
              )}
            </div>
            {orcidId ? (
              <span className="text-xs px-2 py-1 rounded bg-green-50 text-green-700 font-medium">Verified</span>
            ) : (
              <Button variant="link" className="h-auto px-0" onClick={handleConnectOrcid}>
                Verify with ORCID
              </Button>
            )}
          </div>
          {orcidError && <ErrorText>{orcidError}</ErrorText>}
        </div>

        {/* Google Scholar */}
        <div className="space-y-1">
          <div className="flex items-center justify-between gap-2">
            <div>
              <span className="font-medium">Google Scholar</span>
              {scholarId && (
                <a
                  href={`https://scholar.google.com/citations?user=${scholarId}`}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-2 text-primary hover:underline font-mono"
                >
                  {scholarId}
                </a>
              )}
            </div>
            {scholarId ? (
              <span className="text-xs px-2 py-1 rounded bg-green-50 text-green-700 font-medium">Linked</span>
            ) : orcidId ? (
              <div className="flex items-center gap-2">
                <Input
                  type="text"
                  aria-label="Google Scholar ID"
                  value={scholarInput}
                  onChange={(e) => setScholarInput(e.target.value)}
                  placeholder="Scholar ID (e.g. dkAFaXoAAAAJ)"
                  className="w-48"
                />
                <Button
                  variant="link"
                  className="h-auto px-0"
                  onClick={handleLinkScholar}
                  disabled={linking || !scholarInput.trim()}
                >
                  {linking ? 'Linking…' : 'Link'}
                </Button>
              </div>
            ) : (
              <span className="text-xs text-muted-foreground">Verify ORCID first</span>
            )}
          </div>
          {scholarError && <ErrorText>{scholarError}</ErrorText>}
        </div>
      </div>
    </section>
  );
}
