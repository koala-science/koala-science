'use client';

import { useEffect } from 'react';
import { X } from 'lucide-react';
import { createPortal } from 'react-dom';
import { cn } from '@/lib/utils';

interface StandingsLayoutProps {
  gateStrip: React.ReactNode;
  masterList: React.ReactNode;
  detailPane: React.ReactNode;
  thesisRibbon?: React.ReactNode;
  isDetailOpenMobile: boolean;
  onCloseDetail: () => void;
}

// Responsive master-detail shell.
// - lg: master and detail side-by-side (~38% / ~62%).
// - md: stacked (master above detail).
// - <md: master full-width; detail is a portaled full-screen drawer.
export function StandingsLayout({
  gateStrip,
  masterList,
  detailPane,
  thesisRibbon,
  isDetailOpenMobile,
  onCloseDetail,
}: StandingsLayoutProps) {
  useEffect(() => {
    if (!isDetailOpenMobile) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseDetail();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isDetailOpenMobile, onCloseDetail]);

  return (
    <div className="space-y-4">
      {gateStrip}
      <div className="grid gap-4 lg:grid-cols-[38fr_62fr] lg:items-start">
        <div className="min-w-0">{masterList}</div>
        <div className="hidden md:block min-w-0">{detailPane}</div>
      </div>
      {thesisRibbon}

      {/* Mobile drawer, portaled so ancestor stacking contexts can't trap it. */}
      {isDetailOpenMobile &&
        typeof document !== 'undefined' &&
        createPortal(
          <div
            role="dialog"
            aria-modal="true"
            className={cn(
              'fixed inset-0 z-50 md:hidden',
              'bg-background/95 backdrop-blur',
              'flex flex-col',
            )}
          >
            <div className="flex items-center justify-between p-3 border-b border-border">
              <span className="text-sm font-medium">Agent breakdown</span>
              <button
                type="button"
                onClick={onCloseDetail}
                className="rounded-md p-1 hover:bg-muted"
                aria-label="Close detail"
              >
                <X className="h-5 w-5" aria-hidden />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-3">{detailPane}</div>
          </div>,
          document.body,
        )}
    </div>
  );
}
