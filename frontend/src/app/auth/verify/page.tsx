'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { getApiUrl } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

function Verify() {
  const token = useSearchParams().get('token');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  // Deliberately submitted by hand rather than on mount. The token is
  // single-use, and institutional mail scanners fetch and render links before
  // anyone sees them — an automatic POST would let a scanner spend the link, and
  // would mean a click was never required to finish an account.
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${getApiUrl()}/auth/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, name, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const detail = Array.isArray(data.detail)
          ? data.detail.map((d: { msg?: string }) => d.msg ?? '').filter(Boolean).join(', ')
          : data.detail?.detail ?? data.detail;
        throw new Error(detail || 'That link could not be used');
      }
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That link could not be used');
    } finally {
      setBusy(false);
    }
  };

  if (!token) {
    return (
      <p className="text-sm text-muted-foreground" data-agent-action="verify-no-token">
        This link is missing its token. Use the link from your email.
      </p>
    );
  }

  if (done) {
    return (
      <div className="space-y-4" data-agent-action="verify-success">
        <h1 className="font-heading text-2xl font-bold tracking-tight">Account ready</h1>
        <p className="text-sm text-muted-foreground">
          Your email is verified and your password is set.
        </p>
        <Link href="/auth/login" className="text-sm font-medium underline underline-offset-4">
          Log in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="w-full space-y-4" data-agent-action="verify-form">
      <div className="space-y-1">
        <h1 className="font-heading text-2xl font-bold tracking-tight">Finish your account</h1>
        <p className="text-sm text-muted-foreground">
          This link proves you can read this address. Choose how you appear and a
          password to sign in with.
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="name">Display name</Label>
        <Input
          id="name"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Dr. Jane Smith"
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          required
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Min 8 characters"
        />
      </div>

      {error && (
        <p role="alert" aria-live="polite" className="text-sm text-red-600">
          {error}
        </p>
      )}

      <Button type="submit" className="w-full" disabled={busy}>
        {busy ? 'Creating your account…' : 'Create my account'}
      </Button>
    </form>
  );
}

export default function VerifyPage() {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-sm items-center px-4">
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
        <Verify />
      </Suspense>
    </div>
  );
}
