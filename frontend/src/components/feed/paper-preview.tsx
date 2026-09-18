'use client';

import { useEffect, useRef, useState } from 'react';
import { FileText } from 'lucide-react';

/** A paper's first-page preview, or the placeholder when there is none or it fails to load. */
export function PaperPreview({ src, title }: { src?: string | null; title: string }) {
  const [failed, setFailed] = useState(false);
  const img = useRef<HTMLImageElement>(null);

  // An image that failed before hydration fired its error before onError was attached.
  useEffect(() => {
    const el = img.current;
    if (el && el.complete && el.naturalWidth === 0) setFailed(true);
  }, []);

  if (!src || failed) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <FileText className="h-14 w-14 text-muted-foreground/30" aria-hidden />
      </div>
    );
  }

  return (
    <img
      ref={img}
      src={src}
      alt={`Preview of ${title}`}
      className="h-full w-full object-cover object-top"
      onError={() => setFailed(true)}
    />
  );
}
