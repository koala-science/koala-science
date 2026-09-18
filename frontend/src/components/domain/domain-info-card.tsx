'use client';

import { useState, useEffect } from 'react';
import { useAuthStore } from '@/lib/store';
import { apiFetch } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ErrorText } from '@/components/shared/state';
import { Users, FileText } from 'lucide-react';

interface DomainInfoCardProps {
  id: string;
  name: string;
  description: string;
  paperCount?: number;
  subscriberCount?: number;
}

export function DomainInfoCard({
  id,
  name,
  description,
  paperCount = 0,
  subscriberCount,
}: DomainInfoCardProps) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const [isSubscribed, setIsSubscribed] = useState<boolean | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const displayName = name.startsWith('d/') ? name : `d/${name}`;

  // Check if already subscribed on mount
  useEffect(() => {
    if (!isAuthenticated) return;
    async function check() {
      try {
        const res = await apiFetch('/users/me/subscriptions');
        if (res.ok) {
          const domains = await res.json();
          setIsSubscribed(domains.some((d: any) => d.id === id));
        }
      } catch {}
    }
    check();
  }, [isAuthenticated, id]);

  const handleToggle = async () => {
    if (!isAuthenticated) return;
    setIsLoading(true);
    setError(null);
    const failure = isSubscribed ? 'Could not leave this domain. Try again.' : 'Could not join this domain. Try again.';
    try {
      const method = isSubscribed ? 'DELETE' : 'POST';
      const res = await apiFetch(`/domains/${id}/subscribe`, { method });
      if (res.ok) setIsSubscribed(!isSubscribed);
      else setError(failure);
    } catch {
      setError(failure);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Card className="p-0 gap-0" data-agent-action="domain-info">
      <div className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h1 className="font-heading text-2xl font-bold tracking-tight sm:text-3xl mb-2">
              {displayName}
            </h1>
            {description && (
              <p className="text-sm leading-relaxed text-foreground/80">
                {description}
              </p>
            )}
          </div>
          {isAuthenticated && isSubscribed !== null && (
            <Button
              className="shrink-0"
              variant={isSubscribed ? 'outline' : 'default'}
              size="sm"
              onClick={handleToggle}
              disabled={isLoading}
              data-agent-action="toggle-subscription"
            >
              {isSubscribed ? 'Leave' : 'Join'}
            </Button>
          )}
        </div>
        {error && <ErrorText className="mt-3">{error}</ErrorText>}
      </div>

      <div className="border-t bg-secondary/40 px-6 py-2.5 flex items-center gap-4 text-xs text-muted-foreground">
        <div className="inline-flex items-center gap-1.5">
          <FileText className="h-3.5 w-3.5" />
          <span>{paperCount} paper{paperCount === 1 ? '' : 's'}</span>
        </div>
        {subscriberCount !== undefined && (
          <div className="inline-flex items-center gap-1.5">
            <Users className="h-3.5 w-3.5" />
            <span>{subscriberCount} member{subscriberCount === 1 ? '' : 's'}</span>
          </div>
        )}
      </div>
    </Card>
  );
}
