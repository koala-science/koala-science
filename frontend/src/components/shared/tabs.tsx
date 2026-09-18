/**
 * One tab style for the whole site: text with an underline under the current
 * tab. Scrolls sideways rather than overflowing on a narrow screen.
 *
 * LinkTabs switch pages (each tab is a URL); ButtonTabs switch a panel in place.
 *
 * Deliberately not 'use client': server pages pass icon components to LinkTabs,
 * which can't cross into a client component. ButtonTabs takes an onChange, so it
 * is only usable from client components, which is where it runs.
 */

import Link from 'next/link';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';

const ROW = 'scrollbar-thin -mx-1 flex overflow-x-auto border-b px-1';
const TAB =
  '-mb-px inline-flex flex-shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors';
const ON = 'border-primary font-medium text-foreground';
const OFF = 'border-transparent text-muted-foreground hover:text-foreground';

function Label({ icon: Icon, label, count }: { icon?: LucideIcon; label: string; count?: number }) {
  return (
    <>
      {Icon && <Icon className="h-4 w-4" aria-hidden />}
      {label}
      {count !== undefined && (
        <span className="rounded-full bg-muted px-1.5 text-xs tabular-nums text-muted-foreground">{count}</span>
      )}
    </>
  );
}

export interface LinkTab {
  href: string;
  label: string;
  current: boolean;
  icon?: LucideIcon;
  count?: number;
  /** Passed through as data-agent-action, for agents driving the site. */
  action?: string;
}

export function LinkTabs({ tabs, label, className }: { tabs: LinkTab[]; label: string; className?: string }) {
  return (
    <nav aria-label={label} className={cn(ROW, className)}>
      {tabs.map((tab) => (
        <Link
          key={tab.href}
          href={tab.href}
          aria-current={tab.current ? 'page' : undefined}
          data-agent-action={tab.action}
          className={cn(TAB, tab.current ? ON : OFF)}
        >
          <Label icon={tab.icon} label={tab.label} count={tab.count} />
        </Link>
      ))}
    </nav>
  );
}

export interface ButtonTab<T extends string> {
  value: T;
  label: string;
  icon?: LucideIcon;
  count?: number;
}

export function ButtonTabs<T extends string>({
  tabs,
  active,
  onChange,
  label,
  idPrefix,
  className,
}: {
  tabs: ButtonTab<T>[];
  active: T;
  onChange: (value: T) => void;
  label: string;
  /** Tabs get id `${idPrefix}-tab-${value}` and control `${idPrefix}-panel`. */
  idPrefix: string;
  className?: string;
}) {
  return (
    <div role="tablist" aria-label={label} className={cn(ROW, className)}>
      {tabs.map((tab) => {
        const selected = tab.value === active;
        return (
          <button
            key={tab.value}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${tab.value}`}
            aria-selected={selected}
            aria-controls={`${idPrefix}-panel`}
            onClick={() => onChange(tab.value)}
            className={cn(TAB, selected ? ON : OFF)}
          >
            <Label icon={tab.icon} label={tab.label} count={tab.count} />
          </button>
        );
      })}
    </div>
  );
}
