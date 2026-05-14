'use client';
import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { getApiUrl } from '@/lib/api';
import { getApiErrorCode } from '@/lib/api-error';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

type Status = 'pending' | 'success' | 'error';

function VerifyContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get('token');
  const [status, setStatus] = useState<Status>('pending');
  const [errorMessage, setErrorMessage] = useState<string>('');
  const [resendEmail, setResendEmail] = useState('');
  const [resendState, setResendState] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setErrorMessage('Missing verification token.');
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${getApiUrl()}/auth/verify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        });
        if (cancelled) return;
        if (res.ok) {
          setStatus('success');
        } else {
          const body = await res.json().catch(() => ({}));
          setStatus('error');
          setErrorMessage(
            getApiErrorCode(body) === 'INVALID_OR_EXPIRED_TOKEN'
              ? 'This verification link is invalid or has expired.'
              : 'Verification failed. Please try again.'
          );
        }
      } catch {
        if (!cancelled) {
          setStatus('error');
          setErrorMessage('Could not reach the server. Please try again.');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const handleResend = async (e: React.FormEvent) => {
    e.preventDefault();
    setResendState('sending');
    try {
      const res = await fetch(`${getApiUrl()}/auth/resend-verification`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: resendEmail }),
      });
      if (!res.ok) throw new Error('failed');
      setResendState('sent');
    } catch {
      setResendState('error');
    }
  };

  if (status === 'pending') {
    return (
      <div className="text-center space-y-4">
        <h1 className="text-2xl font-bold">Verifying your email...</h1>
        <p className="text-muted-foreground">Just a moment.</p>
      </div>
    );
  }

  if (status === 'success') {
    return (
      <div className="text-center space-y-4">
        <h1 className="text-2xl font-bold">Email verified</h1>
        <p className="text-muted-foreground">You can now sign in to your account.</p>
        <Link href="/auth/login" className="inline-block">
          <Button className="w-full">Go to sign in</Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-4 text-center">
      <h1 className="text-2xl font-bold">Verification failed</h1>
      <p className="text-red-600" role="alert">
        {errorMessage}
      </p>
      <form onSubmit={handleResend} className="space-y-3 text-left">
        <div className="space-y-2">
          <Label htmlFor="resend_email">Resend verification email</Label>
          <Input
            id="resend_email"
            type="email"
            required
            value={resendEmail}
            onChange={(e) => setResendEmail(e.target.value)}
            placeholder="you@example.com"
          />
        </div>
        <Button
          type="submit"
          className="w-full"
          disabled={resendState === 'sending' || resendState === 'sent'}
        >
          {resendState === 'sending'
            ? 'Sending...'
            : resendState === 'sent'
            ? 'Email sent'
            : 'Resend verification email'}
        </Button>
        {resendState === 'error' && (
          <p className="text-sm text-red-600" role="alert">
            Could not resend right now. Please try again later.
          </p>
        )}
      </form>
    </div>
  );
}

export default function VerifyPage() {
  return (
    <div className="flex items-center justify-center min-h-[60vh] px-4">
      <div className="w-full max-w-sm">
        <Suspense fallback={<div className="text-center">Loading...</div>}>
          <VerifyContent />
        </Suspense>
      </div>
    </div>
  );
}
