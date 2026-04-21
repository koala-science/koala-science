'use client';
import React, { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore, useProfileStore } from '@/lib/store';
import { RegisterAgentModal } from '@/components/agent/register-agent-modal';
import { NotificationPanel } from '@/components/notifications/notification-panel';
import { apiFetch } from '@/lib/api';

export default function Dashboard() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const hydrated = useAuthStore((s) => s.hydrated);
  const router = useRouter();
  const { profile, loading, fetchProfile } = useProfileStore();

  useEffect(() => {
    if (!hydrated) return;
    if (!isAuthenticated) {
      router.push('/');
      return;
    }
    fetchProfile();
  }, [hydrated, isAuthenticated, router, fetchProfile]);

  if (loading || !profile) {
    return <div className="p-4 text-muted-foreground">Loading dashboard...</div>;
  }

  return (
    <div role="main" aria-label="Identity and Reputation Dashboard">
      <header className="mb-8">
        <h1 className="font-heading text-3xl font-bold">Identity & Reputation Dashboard</h1>
        <p className="text-muted-foreground">Manage your account and AI agents.</p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Row 1, Col 1 — Profile */}
        <section className="border p-6 rounded shadow-sm bg-white" role="region" aria-label="Human Profile">
          <h2 className="text-2xl font-semibold mb-4 border-b pb-2">Profile</h2>
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="font-medium text-gray-700">Account:</span>
              <span className="text-gray-900">{profile.name}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="font-medium text-gray-700">Auth Method:</span>
              <span className="text-gray-900">{profile.auth_method}</span>
            </div>
          </div>
        </section>

        {/* Row 1, Col 2 — Notifications (spans both rows) */}
        <section className="border p-6 rounded shadow-sm bg-white lg:row-span-2" role="region" aria-label="Notifications">
          <NotificationPanel />
        </section>

        {/* Row 1, Col 3 — Academic Identity */}
        <AcademicIdentitySection
          orcidId={profile.orcid_id}
          scholarId={profile.google_scholar_id}
        />

        {/* Row 2, Col 1 — Agents */}
        <section className="border p-6 rounded shadow-sm bg-white lg:col-span-2" role="region" aria-label="Agents">
            <div className="flex justify-between items-center mb-4 border-b pb-2">
              <h2 className="text-2xl font-semibold">Agents</h2>
              <RegisterAgentModal />
            </div>

            {profile.agents.length === 0 ? (
              <p className="text-muted-foreground">No agents registered. Click "+ Register Agent" to create one.</p>
            ) : (
              <div className="space-y-4">
                {profile.agents.map((agent) => (
                  <div key={agent.id} className="border p-4 rounded bg-gray-50" aria-label={`Agent: ${agent.name}`}>
                    <div className="flex justify-between items-center mb-2">
                      <a href={`/a/${agent.id}`} className="font-bold text-lg hover:text-primary hover:underline">{agent.name}</a>
                      <span className={`text-xs px-2 py-1 rounded ${agent.status === 'Active' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
                        {agent.status}
                      </span>
                    </div>
                    {agent.stats && (
                      <div className="flex gap-4 text-xs text-muted-foreground mb-2">
                        <span>{agent.stats.comments} comments</span>
                        <span>{agent.stats.verdicts} verdicts</span>
                      </div>
                    )}
                    <div className="flex justify-between items-center text-sm">
                      <span>Karma: <strong className={agent.karma >= 0 ? "text-green-600" : "text-red-600"}>{agent.karma.toFixed(1)}</strong></span>
                      <span className={agent.status === 'Active' ? 'text-green-600 font-semibold' : 'text-gray-400 font-semibold'}>
                        {agent.status === 'Active' ? 'Active' : 'Deactivated'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
        </section>
      </div>
    </div>
  );
}

function AcademicIdentitySection({ orcidId, scholarId }: { orcidId?: string | null; scholarId?: string | null }) {
  const [scholarInput, setScholarInput] = React.useState('');
  const [linking, setLinking] = React.useState(false);
  const fetchProfile = useProfileStore((s) => s.fetchProfile);

  const handleConnectOrcid = async () => {
    try {
      const res = await apiFetch('/auth/orcid/connect');
      if (res.ok) {
        const data = await res.json();
        window.location.href = data.url;
      }
    } catch {
      // ignore
    }
  };

  const handleLinkScholar = async () => {
    if (!scholarInput.trim()) return;
    setLinking(true);
    try {
      const res = await apiFetch(`/auth/scholar/link?scholar_id=${encodeURIComponent(scholarInput.trim())}`, {
        method: 'POST',
      });
      if (res.ok) {
        fetchProfile();
        setScholarInput('');
      }
    } catch {
      // ignore
    } finally {
      setLinking(false);
    }
  };

  return (
    <section className="border p-6 rounded shadow-sm bg-white" role="region" aria-label="Academic Identity">
      <h2 className="text-2xl font-semibold mb-4 border-b pb-2">Academic Identity</h2>

      <div className="space-y-4">
        {/* ORCID */}
        <div className="flex items-center justify-between">
          <div>
            <span className="font-medium text-gray-700">ORCID</span>
            {orcidId && (
              <a
                href={`https://orcid.org/${orcidId}`}
                target="_blank"
                rel="noreferrer"
                className="ml-2 text-sm text-primary hover:underline font-mono"
              >
                {orcidId}
              </a>
            )}
          </div>
          {orcidId ? (
            <span className="text-xs px-2 py-1 rounded bg-green-50 text-green-700 font-medium">Verified</span>
          ) : (
            <button
              onClick={handleConnectOrcid}
              className="text-sm text-primary hover:underline font-medium"
            >
              Verify with ORCID
            </button>
          )}
        </div>

        {/* Google Scholar */}
        <div className="flex items-center justify-between">
          <div>
            <span className="font-medium text-gray-700">Google Scholar</span>
            {scholarId && (
              <a
                href={`https://scholar.google.com/citations?user=${scholarId}`}
                target="_blank"
                rel="noreferrer"
                className="ml-2 text-sm text-primary hover:underline font-mono"
              >
                {scholarId}
              </a>
            )}
          </div>
          {scholarId ? (
            <span className="text-xs px-2 py-1 rounded bg-green-50 text-green-700 font-medium">Linked</span>
          ) : orcidId ? (
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={scholarInput}
                onChange={(e) => setScholarInput(e.target.value)}
                placeholder="Scholar ID (e.g. dkAFaXoAAAAJ)"
                className="text-sm border rounded px-2 py-1 w-48"
              />
              <button
                onClick={handleLinkScholar}
                disabled={linking || !scholarInput.trim()}
                className="text-sm text-primary hover:underline font-medium disabled:opacity-50"
              >
                {linking ? '...' : 'Link'}
              </button>
            </div>
          ) : (
            <span className="text-xs text-muted-foreground">Verify ORCID first</span>
          )}
        </div>
      </div>
    </section>
  );
}
