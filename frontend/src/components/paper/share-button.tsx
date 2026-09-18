'use client';

import { useState } from 'react';
import { Share2, Check } from 'lucide-react';
import { ActionLink } from '@/components/shared/action-link';

export function ShareButton() {
  const [copied, setCopied] = useState(false);

  const handleShare = async () => {
    const url = window.location.href;

    if (navigator.share) {
      try {
        await navigator.share({ url });
        return;
      } catch {
        // Fallback to clipboard
      }
    }

    await navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <ActionLink
      icon={copied ? <Check className="h-3.5 w-3.5 text-green-600" /> : <Share2 className="h-3.5 w-3.5" />}
      label={copied ? 'Copied' : 'Share'}
      onClick={handleShare}
      data-agent-action="share-paper"
    />
  );
}
