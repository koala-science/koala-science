/**
 * The frame every page sits in: one of three widths, and a title block.
 *
 * narrow  — feeds and profiles, a single column of cards
 * default — reading pages (a paper) and forms that need room
 * wide    — tables (admin)
 */

import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

const WIDTHS = {
  narrow: 'max-w-2xl',
  default: 'max-w-4xl',
  wide: 'max-w-6xl',
} as const;

export function PageShell({
  width = 'narrow',
  className,
  children,
  ...rest
}: {
  width?: keyof typeof WIDTHS;
  className?: string;
  children: ReactNode;
} & Omit<React.ComponentProps<'div'>, 'className' | 'children'>) {
  return (
    <div className={cn('mx-auto w-full', WIDTHS[width], className)} {...rest}>
      {children}
    </div>
  );
}

/** The page's one h1, with an optional line under it and actions to its right. */
export function PageTitle({
  children,
  description,
  actions,
  className,
}: {
  children: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('mb-6 flex flex-wrap items-start justify-between gap-3', className)}>
      <div className="min-w-0">
        <h1 className="font-heading text-2xl font-bold tracking-tight sm:text-3xl">{children}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

/** A heading for a section inside a page or card. */
export function SectionTitle({
  children,
  className,
  id,
}: {
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <h2 id={id} className={cn('text-lg font-semibold tracking-tight', className)}>
      {children}
    </h2>
  );
}

/** The small uppercase label over a block of metadata (Abstract, Resources, Arguments). */
export function SectionLabel({
  children,
  className,
  id,
}: {
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <h2
      id={id}
      className={cn('mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground', className)}
    >
      {children}
    </h2>
  );
}
