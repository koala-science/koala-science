'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardHeader } from '@/components/ui/card';

export default function SubmitPaperPage() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isAuthenticated) {
    return (
      <div className="max-w-xl mx-auto py-12 text-center">
        <h1 className="text-2xl font-bold mb-2">Submit a Paper</h1>
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

    const formData = new FormData(e.currentTarget);
    const payload = {
      title: formData.get('title') as string,
      abstract: formData.get('abstract') as string,
      domain: formData.get('domain') as string,
      pdf_url: formData.get('pdf_url') as string,
      github_repo_url: (formData.get('github_repo_url') as string) || null,
    };

    try {
      const res = await apiFetch('/papers/', {
        method: 'POST',
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Failed to submit paper');
      }

      const paper = await res.json();
      router.push(`/paper/${paper.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Submission failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-xl mx-auto py-8">
      <h1 className="text-2xl font-bold mb-6">Submit a Paper</h1>

      <Card className="ring-0 border pb-4">
        <CardHeader className="pb-0" />
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="title" className="text-sm font-medium">Title</label>
              <Input id="title" name="title" required placeholder="Paper title" />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="abstract" className="text-sm font-medium">Abstract</label>
              <Textarea
                id="abstract"
                name="abstract"
                required
                placeholder="Paste the paper abstract..."
                className="min-h-[120px]"
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="domain" className="text-sm font-medium">Domain</label>
              <Input id="domain" name="domain" required placeholder="e.g. d/LLM-Alignment" />
              <p className="text-xs text-muted-foreground">Choose an existing domain or create a new one.</p>
            </div>

            <div className="space-y-1.5">
              <label htmlFor="pdf_url" className="text-sm font-medium">arXiv PDF URL</label>
              <Input id="pdf_url" name="pdf_url" type="url" required placeholder="https://arxiv.org/pdf/..." />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="github_repo_url" className="text-sm font-medium">GitHub Repo <span className="text-muted-foreground font-normal">(optional)</span></label>
              <Input id="github_repo_url" name="github_repo_url" type="url" placeholder="https://github.com/..." />
            </div>

            {error && <p className="text-sm text-red-600">{error}</p>}

            <div className="flex justify-end pt-2">
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
