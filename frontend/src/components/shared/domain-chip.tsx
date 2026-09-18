/** A paper's domain, linking to that domain's page. The one style used everywhere. */

import Link from 'next/link';
import { cn } from '@/lib/utils';

export function domainHref(domain: string) {
  return `/d/${domain.replace(/^d\//, '')}`;
}

export function DomainChip({ domain, className }: { domain: string; className?: string }) {
  return (
    <Link
      href={domainHref(domain)}
      className={cn(
        'inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground',
        className,
      )}
    >
      {domain}
    </Link>
  );
}

export function DomainChips({ domains, className }: { domains?: string[] | null; className?: string }) {
  if (!domains || domains.length === 0) return null;
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-1.5', className)}>
      {domains.map((d) => (
        <DomainChip key={d} domain={d} />
      ))}
    </span>
  );
}
