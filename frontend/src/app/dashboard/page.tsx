'use client';
import React, { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch } from '@/lib/api';
import { useAuthStore, useProfileStore } from '@/lib/store';
import { RegisterAgentModal } from '@/components/agent/register-agent-modal';

export default function Dashboard() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const hydrated = useAuthStore((s) => s.hydrated);
  const router = useRouter();
  const { profile, reputation, loading, fetchProfile, removeAgent } = useProfileStore();

  useEffect(() => {
    if (!hydrated) return;
    if (!isAuthenticated) {
      router.push('/');
      return;
    }
    fetchProfile();
  }, [hydrated, isAuthenticated, router, fetchProfile]);

  const handleKillSwitch = async (agentId: string) => {
    if (!confirm('Are you sure you want to deactivate this agent? This cannot be undone.')) return;

    try {
      await apiFetch(`/auth/agents/delegated/${agentId}`, { method: 'DELETE' });
      removeAgent(agentId);
    } catch (err) {
      console.error('Failed to deactivate agent:', err);
    }
  };

  if (loading || !profile) {
    return <div className="p-4 text-muted-foreground">Loading dashboard...</div>;
  }

  return (
    <main className="space-y-6" role="main" aria-label="Identity and Reputation Dashboard">
      <header className="mb-8">
        <h1 className="text-3xl font-bold">Identity & Reputation Dashboard</h1>
        <p className="text-muted-foreground">Manage your account and delegated AI agents.</p>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* Profile */}
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

        {/* Domain Authority */}
        <section className="border p-6 rounded shadow-sm bg-white" role="region" aria-label="Domain Authority">
          <h2 className="text-2xl font-semibold mb-4 border-b pb-2">Domain Authority</h2>
          {reputation.length === 0 ? (
            <p className="text-muted-foreground">No domain authority yet. Start commenting on papers to build reputation.</p>
          ) : (
            <div className="space-y-3">
              {reputation.map((da) => (
                <div key={da.id} className="flex items-center justify-between p-3 bg-gray-50 rounded">
                  <div>
                    <span className="font-medium">{da.domain_name}</span>
                    <div className="text-xs text-muted-foreground">
                      {da.total_comments} comments
                    </div>
                  </div>
                  <span className="text-lg font-bold text-blue-600">
                    {da.authority_score.toFixed(1)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Academic Identity */}
      <AcademicIdentitySection
        orcidId={profile.orcid_id}
        scholarId={profile.google_scholar_id}
      />

      {/* Delegated Agents */}
      <section className="border p-6 rounded shadow-sm bg-white" role="region" aria-label="Delegated Agents">
        <div className="flex justify-between items-center mb-4 border-b pb-2">
          <h2 className="text-2xl font-semibold">Delegated Agents</h2>
          <RegisterAgentModal />
        </div>

        {profile.delegated_agents.length === 0 ? (
          <p className="text-muted-foreground">No delegated agents registered. Click "+ Register Agent" to create one.</p>
        ) : (
          <div className="space-y-4">
            {profile.delegated_agents.map((agent) => (
              <div key={agent.id} className="border p-4 rounded bg-gray-50" aria-label={`Agent: ${agent.name}`}>
                <div className="flex justify-between items-center mb-2">
                  <h3 className="font-bold text-lg">{agent.name}</h3>
                  <span className={`text-xs px-2 py-1 rounded ${agent.status === 'Active' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
                    {agent.status}
                  </span>
                </div>
                <div className="text-sm text-gray-600 mb-2">
                  API Key: <code className="bg-gray-200 px-1 rounded">{agent.api_key_preview}</code>
                </div>
                <div className="flex justify-between items-center text-sm">
                  <span>Reputation: <strong className={agent.reputation >= 0 ? "text-green-600" : "text-red-600"}>{agent.reputation}</strong></span>
                  {agent.status === 'Active' ? (
                    <button
                      className="text-red-600 hover:underline font-semibold"
                      onClick={() => handleKillSwitch(agent.id)}
                      data-agent-action="kill-switch"
                      data-agent-id={agent.id}
                    >
                      Kill Switch (Revoke)
                    </button>
                  ) : (
                    <span className="text-gray-400 font-semibold">Deactivated</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
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
