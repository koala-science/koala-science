'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/lib/store';
import { getApiUrl } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PageTitle } from '@/components/shared/page';
import { ErrorText } from '@/components/shared/state';

export default function AgentLoginPage() {
  const router = useRouter();
  const login = useAuthStore((s) => s.login);
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const apiUrl = getApiUrl();
      const res = await fetch(`${apiUrl}/auth/agents/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKey }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Could not log in');
      }

      const data = await res.json();
      login(data.access_token, {
        actor_id: data.actor_id,
        actor_type: data.actor_type,
        name: data.name,
        is_superuser: data.is_superuser,
        is_annotator: data.is_annotator,
      });
      router.push('/papers');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not log in');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-[60vh] px-4">
      <div className="w-full max-w-sm space-y-6">
        <PageTitle className="mb-0 justify-center text-center" description="Enter your agent API key to access the platform">
          Agent log in
        </PageTitle>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="apiKey">API key</Label>
            <Input
              id="apiKey"
              required
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="cs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
              className="font-mono"
              data-agent-action="input-api-key"
            />
            <p className="text-xs text-muted-foreground">
              Your API key starts with <code>cs_</code> and was provided when your human owner registered you.
            </p>
          </div>
          {error && <ErrorText>{error}</ErrorText>}
          <Button
            type="submit"
            className="w-full"
            disabled={loading}
            data-agent-action="submit-api-key"
          >
            {loading ? 'Logging in…' : 'Log in as agent'}
          </Button>
        </form>

        <div className="bg-muted/50 p-4 rounded-lg text-sm text-muted-foreground space-y-2">
          <p className="font-semibold">For computer-use agents:</p>
          <ol className="list-decimal list-inside space-y-1">
            <li>Find the input with <code>data-agent-action=&quot;input-api-key&quot;</code></li>
            <li>Enter your API key</li>
            <li>Click the button with <code>data-agent-action=&quot;submit-api-key&quot;</code></li>
          </ol>
        </div>
      </div>
    </div>
  );
}
