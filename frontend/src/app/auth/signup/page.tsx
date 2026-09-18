'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { getApiUrl } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PageTitle } from '@/components/shared/page';
import { ErrorText } from '@/components/shared/state';

export default function SignupPage() {
  const router = useRouter();
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
        throw new Error(detail || 'Could not create your account');
      }

      // Signup no longer signs anyone in: the account cannot act until the
      // address it claims has been proven, and the name and password are chosen
      // on the page the link leads to.
      //
      // When the backend hands the token back — self-serve onboarding, before a
      // mail sender is configured — go there directly. Telling someone to check
      // an inbox nothing will reach is worse than no instruction at all.
      const { verification_token: token } = await res.json();
      if (token) {
        // `replace`, not `push`: this step is done, and Back landing on an empty
        // signup form whose resubmit now 409s on the OpenReview ID is a dead end.
        router.replace(`/auth/verify?token=${encodeURIComponent(token)}`);
        return;
      }
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create your account');
    } finally {
      setLoading(false);
    }
  };

  if (submitted) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] px-4">
        <div className="w-full max-w-sm space-y-4 text-center" data-agent-action="signup-check-email">
          <PageTitle className="mb-0 justify-center text-center">Check your email</PageTitle>
          <p className="text-sm text-muted-foreground">
            We sent a verification link to <span className="font-medium text-foreground">{email}</span>.
            Click it to finish creating your account.
          </p>
          <button
            type="button"
            onClick={resend}
            className="text-sm font-medium text-primary hover:underline"
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
        <PageTitle className="mb-0 justify-center text-center" description="Join Koala Science as a researcher">
          Create your account
        </PageTitle>

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
          {error && <ErrorText>{error}</ErrorText>}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? 'Creating account…' : 'Create account'}
          </Button>
        </form>

        <p className="text-center text-sm text-muted-foreground">
          Already have an account?{' '}
          <Link href="/auth/login" className="text-primary hover:underline">Log in</Link>
        </p>
      </div>
    </div>
  );
}
