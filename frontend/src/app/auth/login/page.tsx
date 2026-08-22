'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuthStore } from '@/lib/store';
import { getApiUrl } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export default function LoginPage() {
  const router = useRouter();
  const login = useAuthStore((s) => s.login);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [unverified, setUnverified] = useState(false);
  const [resent, setResent] = useState(false);

  const resend = async () => {
    setResent(false);
    await fetch(`${getApiUrl()}/auth/resend-verification`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    setResent(true);
  };
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setUnverified(false);

    try {
      const apiUrl = getApiUrl();
      const res = await fetch(`${apiUrl}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        // Login cannot say whether the account merely needs verifying — doing so
        // would report whether the address is registered — so the resend
        // affordance is offered on any failure and does nothing if it does not
        // apply.
        setUnverified(true);
        const detail = Array.isArray(data.detail)
          ? data.detail.map((d: { msg?: string }) => d.msg ?? '').filter(Boolean).join(', ')
          : data.detail?.detail ?? data.detail;
        throw new Error(detail || 'Login failed');
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
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-[60vh] px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold">Welcome back</h1>
          <p className="text-muted-foreground mt-1">Sign in to your Koala Science account</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" aria-describedby={error ? 'login-error' : undefined} aria-invalid={error ? true : undefined} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} aria-describedby={error ? 'login-error' : undefined} aria-invalid={error ? true : undefined} />
          </div>
          {error && <p id="login-error" role="alert" aria-live="polite" className="text-sm text-red-600">{error}</p>}
          {unverified && (
            <div role="alert" aria-live="polite" className="space-y-1 text-sm" data-agent-action="login-unverified">
              <p className="text-muted-foreground">
                Signed up but never verified? Check your inbox for the link.
              </p>
              <button
                type="button"
                onClick={resend}
                className="font-medium underline underline-offset-4"
                data-agent-action="resend-verification"
              >
                Send it again
              </button>
              {resent && <p className="text-muted-foreground">Sent — it can take a minute.</p>}
            </div>
          )}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? 'Signing in...' : 'Sign In'}
          </Button>
        </form>

        <p className="text-center text-sm text-muted-foreground">
          Don&apos;t have an account?{' '}
          <Link href="/auth/signup" className="text-blue-600 hover:underline">Sign up</Link>
        </p>
      </div>
    </div>
  );
}
