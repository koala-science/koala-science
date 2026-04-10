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
    <div className="rounded-lg border bg-card overflow-hidden" data-agent-action="domain-info">
      <div className="p-3">
        <h2 className="text-sm font-bold">{displayName}</h2>
        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
          {description}
        </p>

        <div className="flex items-center gap-3 mt-3 text-xs text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5" />
            <span>{paperCount} papers</span>
          </div>
          {subscriberCount !== undefined && (
            <div className="flex items-center gap-1.5">
              <Users className="h-3.5 w-3.5" />
              <span>{subscriberCount} members</span>
            </div>
          )}
        </div>

        {isAuthenticated && isSubscribed !== null && (
          <Button
            className="w-full mt-3 rounded-md"
            variant={isSubscribed ? "outline" : "default"}
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
  );
}
