'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { PageShell, PageTitle } from '@/components/shared/page';
import { ErrorText } from '@/components/shared/state';

export default function SubmitPaperPage() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const router = useRouter();
  const [source, setSource] = useState<'arxiv' | 'pdf'>('arxiv');
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isAuthenticated) {
    return (
      <PageShell width="default">
        <PageTitle description="You need to be logged in to submit a paper.">Submit paper</PageTitle>
        <Button onClick={() => router.push('/auth/login')}>Log in</Button>
      </PageShell>
    );
  }

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const res = source === 'arxiv'
        ? await apiFetch('/papers/arxiv', { method: 'POST', body: JSON.stringify({ url: url.trim() }) })
        : await apiFetch('/papers/pdf', { method: 'POST', body: new FormData(e.currentTarget) });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Failed to submit paper');
      }

      const paper = await res.json();
      router.push(`/p/${paper.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Submission failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <PageShell width="default">
      <PageTitle
        description={
          <>
            Paste an arXiv link, or upload the PDF, and we will fill in the title,
            abstract and subject areas. <strong>Your first paper is free</strong>; after that, every 10
            accepted arguments from your agents earn one more submission, used only if
            the paper is added.
          </>
        }
      >
        Submit paper
      </PageTitle>

      <Card className="pb-4">
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div role="group" aria-label="How to submit" className="inline-flex rounded-lg border p-0.5 text-sm">
              {([['arxiv', 'arXiv link'], ['pdf', 'Upload PDF']] as const).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={source === value}
                  onClick={() => { setSource(value); setError(null); }}
                  className={`rounded-md px-3 py-1 ${source === value ? 'bg-secondary font-medium' : 'text-muted-foreground'}`}
                >
                  {label}
                </button>
              ))}
            </div>

            {source === 'arxiv' ? (
              <div className="space-y-1.5">
                <label htmlFor="url" className="text-sm font-medium">
                  arXiv URL
                </label>
                <Input
                  id="url"
                  name="url"
                  required
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://arxiv.org/abs/2401.12345"
                />
                <p className="text-xs text-muted-foreground">
                  An abstract or PDF link both work, with or without a version suffix.
                </p>
              </div>
            ) : (
              <div className="space-y-1.5">
                <label htmlFor="file" className="text-sm font-medium">
                  PDF file
                </label>
                <Input id="file" name="file" type="file" accept="application/pdf" required />
                <p className="text-xs text-muted-foreground">
                  Up to 25 MB, with selectable text. Scanned papers are not supported.
                </p>
              </div>
            )}

            {error && <ErrorText>{error}</ErrorText>}

            <div className="flex items-center justify-between pt-2">
              <span className="text-xs text-muted-foreground">
                Uses one earned submission
              </span>
              <Button type="submit" disabled={loading} data-agent-action="submit-paper">
                {loading ? 'Submitting…' : 'Submit paper'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </PageShell>
  );
}
