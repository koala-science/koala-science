'use client';
import { useState } from 'react';
import Link from 'next/link';
import { getApiUrl } from '@/lib/api';
import { extractApiErrorMessage } from '@/lib/api-error';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export default function SignupPage() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [openreviewIds, setOpenreviewIds] = useState<[string, string, string]>(['', '', '']);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [submittedEmail, setSubmittedEmail] = useState<string | null>(null);
  const [resendStatus, setResendStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');

  const updateOpenreviewId = (index: number, value: string) => {
    setOpenreviewIds((prev) => {
      const next = [...prev] as [string, string, string];
      next[index] = value;
      return next;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const ids = openreviewIds.map((v) => v.trim()).filter((v) => v.length > 0);

    try {
      const apiUrl = getApiUrl();
      const res = await fetch(`${apiUrl}/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password, openreview_ids: ids }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(extractApiErrorMessage(data, 'Signup failed'));
      }

      const data = await res.json();
      setSubmittedEmail(data.email ?? email);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Signup failed');
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    if (!submittedEmail) return;
    setResendStatus('sending');
    try {
      const apiUrl = getApiUrl();
      const res = await fetch(`${apiUrl}/auth/resend-verification`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: submittedEmail }),
      });
      if (!res.ok) throw new Error('resend failed');
      setResendStatus('sent');
    } catch {
      setResendStatus('error');
    }
  };

  if (submittedEmail) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] px-4">
        <div className="w-full max-w-sm space-y-6 text-center">
          <h1 className="text-2xl font-bold">Check your email</h1>
          <p className="text-muted-foreground">
            We sent a verification link to <strong>{submittedEmail}</strong>. Click the link to
            activate your account.
          </p>
          <div className="space-y-2">
            <Button
              type="button"
              variant="secondary"
              onClick={handleResend}
              disabled={resendStatus === 'sending' || resendStatus === 'sent'}
              className="w-full"
            >
              {resendStatus === 'sending'
                ? 'Resending...'
                : resendStatus === 'sent'
                ? 'Email resent'
                : 'Resend verification email'}
            </Button>
            {resendStatus === 'error' && (
              <p className="text-sm text-red-600" role="alert">
                Could not resend right now. Please try again later.
              </p>
            )}
          </div>
          <p className="text-sm text-muted-foreground">
            <Link href="/auth/login" className="text-blue-600 hover:underline">
              Back to sign in
            </Link>
          </p>
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
            <Label htmlFor="name">Display Name</Label>
            <Input id="name" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Dr. Jane Smith" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="openreview_id_0">OpenReview ID</Label>
            <Input
              id="openreview_id_0"
              required
              value={openreviewIds[0]}
              onChange={(e) => updateOpenreviewId(0, e.target.value)}
              placeholder="~First_Last1"
            />
            <p className="text-xs text-muted-foreground">Your OpenReview profile ID, e.g. <code>~Jane_Smith1</code>. Find it at openreview.net/profile.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="openreview_id_1">Additional OpenReview ID (optional)</Label>
            <Input
              id="openreview_id_1"
              value={openreviewIds[1]}
              onChange={(e) => updateOpenreviewId(1, e.target.value)}
              placeholder="~First_Last2"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="openreview_id_2">Additional OpenReview ID (optional)</Label>
            <Input
              id="openreview_id_2"
              value={openreviewIds[2]}
              onChange={(e) => updateOpenreviewId(2, e.target.value)}
              placeholder="~First_Last3"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Min 8 characters" />
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
