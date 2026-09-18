'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { getApiUrl } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PageTitle } from '@/components/shared/page';
import { ErrorText } from '@/components/shared/state';

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
      <p className="text-center text-sm text-muted-foreground" data-agent-action="verify-no-token">
        This link is missing its token. Use the link from your email.
      </p>
    );
  }

  if (done) {
    return (
      <div className="space-y-4 text-center" data-agent-action="verify-success">
        <PageTitle className="mb-0 justify-center text-center">Account ready</PageTitle>
        <p className="text-sm text-muted-foreground">
          Your email is verified and your password is set.
        </p>
        <Link href="/auth/login" className="text-sm font-medium text-primary hover:underline">
          Log in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4" data-agent-action="verify-form">
      <PageTitle
        className="mb-0 justify-center text-center"
        description="This link proves you can read this address. Choose how you appear and a password to log in with."
      >
        Finish your account
      </PageTitle>

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

      {error && <ErrorText>{error}</ErrorText>}

      <Button type="submit" className="w-full" disabled={busy}>
        {busy ? 'Creating your account…' : 'Create my account'}
      </Button>
    </form>
  );
}

export default function VerifyPage() {
  return (
    <div className="flex items-center justify-center min-h-[60vh] px-4">
      <div className="w-full max-w-sm">
        <Suspense fallback={<p className="text-center text-sm text-muted-foreground">Loading…</p>}>
          <Verify />
        </Suspense>
      </div>
    </div>
  );
}
