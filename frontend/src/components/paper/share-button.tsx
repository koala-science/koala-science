'use client';

import { useState } from 'react';
import { Share2, Check } from 'lucide-react';

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
    <button
      onClick={handleShare}
      className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground"
      data-agent-action="share-paper"
    >
      {copied ? <Check className="h-[1em] w-[1em] text-green-600" /> : <Share2 className="h-[1em] w-[1em]" />}
      <span>{copied ? 'copied' : 'share'}</span>
    </button>
  );
}
