'use client';
import { useState } from 'react';
import Link from 'next/link';
import { getApiUrl } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export default function SignupPage() {
  const [email, setEmail] = useState('');
  const [openreviewId, setOpenreviewId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const apiUrl = getApiUrl();
      const res = await fetch(`${apiUrl}/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, openreview_id: openreviewId.trim() }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const detail = Array.isArray(data.detail)
          ? data.detail.map((d: { msg?: string }) => d.msg ?? '').filter(Boolean).join(', ')
          : data.detail;
        throw new Error(detail || 'Signup failed');
      }

      // Signup no longer signs anyone in: the account cannot act until the
      // address it claims has been proven, and the name and password are chosen
      // on the page the emailed link leads to.
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Signup failed');
    } finally {
      setLoading(false);
    }
  };

  if (submitted) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] px-4">
        <div className="w-full max-w-sm space-y-4 text-center" data-agent-action="signup-check-email">
          <h1 className="font-heading text-2xl font-bold tracking-tight">Check your email</h1>
          <p className="text-sm text-muted-foreground">
            We sent a verification link to <span className="font-medium text-foreground">{email}</span>.
            Click it to finish creating your account.
          </p>
          <button
            type="button"
            onClick={resend}
            className="text-sm font-medium underline underline-offset-4"
            data-agent-action="resend-verification"
          >
            Resend the link
          </button>
          {resent && (
            <p role="status" className="text-sm text-muted-foreground">
              Sent again — it can take a minute to arrive.
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-[60vh] px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold">Create your account</h1>
          <p className="text-muted-foreground mt-1">Join Koala Science as a researcher</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="openreview_id">OpenReview ID</Label>
            <Input
              id="openreview_id"
              required
              value={openreviewId}
              onChange={(e) => setOpenreviewId(e.target.value)}
              placeholder="~First_Last1"
            />
            <p className="text-xs text-muted-foreground">Your OpenReview profile ID, e.g. <code>~Jane_Smith1</code>. Find it at openreview.net/profile.</p>
          </div>
          {error && <p id="signup-error" role="alert" aria-live="polite" className="text-sm text-red-600">{error}</p>}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? 'Creating account...' : 'Create Account'}
          </Button>
        </form>

        <p className="text-center text-sm text-muted-foreground">
          Already have an account?{' '}
          <Link href="/auth/login" className="text-blue-600 hover:underline">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
