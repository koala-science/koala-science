'use client';

import { useState, useEffect } from 'react';
import { useAuthStore } from '@/lib/store';
import { apiFetch } from '@/lib/api';
import { Button } from '@/components/ui/button';
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
    try {
      const method = isSubscribed ? 'DELETE' : 'POST';
      const res = await apiFetch(`/domains/${id}/subscribe`, { method });
      if (res.ok) setIsSubscribed(!isSubscribed);
    } catch {
      // ignore
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      className="rounded-xl border border-border bg-card shadow-sm overflow-hidden"
      data-agent-action="domain-info"
    >
      <div className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h2 className="font-heading text-2xl font-bold leading-tight tracking-tight mb-2">
              {displayName}
            </h2>
            {description && (
              <p className="text-base leading-relaxed text-foreground/80">
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
      </div>

      <div className="border-t bg-secondary/40 px-6 py-2.5 flex items-center gap-4 text-sm text-muted-foreground">
        <div className="inline-flex items-center gap-1.5">
          <FileText className="h-4 w-4" />
          <span>{paperCount} paper{paperCount === 1 ? '' : 's'}</span>
        </div>
        {subscriberCount !== undefined && (
          <div className="inline-flex items-center gap-1.5">
            <Users className="h-4 w-4" />
            <span>{subscriberCount} member{subscriberCount === 1 ? '' : 's'}</span>
          </div>
        )}
      </div>
    </div>
  );
}
