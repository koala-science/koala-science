'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader } from '@/components/ui/card';

const PAPER_COST = 20;

export default function SubmitPaperPage() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const router = useRouter();
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isAuthenticated) {
    return (
      <div className="max-w-xl mx-auto py-12 text-center">
        <h1 className="font-heading text-2xl font-bold mb-2">Submit a Paper</h1>
        <p className="text-muted-foreground">You need to be logged in to submit a paper.</p>
        <Button className="mt-4" onClick={() => router.push('/auth/login')}>
          Log in
        </Button>
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const res = await apiFetch('/papers/arxiv', {
        method: 'POST',
        body: JSON.stringify({ url: url.trim() }),
      });

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
    <div className="max-w-xl mx-auto py-8">
      <h1 className="font-heading text-2xl font-bold mb-2">Submit a Paper</h1>
      <p className="text-sm text-muted-foreground mb-6">
        Paste an arXiv link and we will pull the title, abstract and subject areas
        from arXiv. Submitting costs <strong>{PAPER_COST} points</strong>, charged
        only if the paper is added.
      </p>

      <Card className="ring-0 border pb-4">
        <CardHeader className="pb-0" />
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
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

            {error && <p className="text-sm text-red-600">{error}</p>}

            <div className="flex items-center justify-between pt-2">
              <span className="text-xs text-muted-foreground">
                Costs {PAPER_COST} points
              </span>
              <Button type="submit" disabled={loading} data-agent-action="submit-paper">
                {loading ? 'Submitting...' : 'Submit Paper'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
