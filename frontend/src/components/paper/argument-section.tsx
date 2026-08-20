'use client';

import { useState } from 'react';
import { ActorBadge } from '@/components/shared/actor-badge';
import { timeAgo } from '@/lib/utils';
import { CheckCircle2, ChevronDown, Loader2, Minus, Plus, XCircle } from 'lucide-react';

export interface ArgumentCheck {
  name: string;
  version: string;
  status: 'pending' | 'passed' | 'failed';
  detail: string | null;
}

export interface ArgumentRecord {
  id: string;
  paper_id: string;
  author_id: string;
  author_name?: string;
  claim: string;
  position: 'positive' | 'negative';
  evidence: string;
  state: 'pending' | 'accepted' | 'rejected';
  created_at: string;
  checks: ArgumentCheck[];
}

type Bucket = 'negative' | 'positive' | 'rejected';

/** A rejected argument leaves its position bucket, whichever side it argued. */
function bucketOf(argument: ArgumentRecord): Bucket {
  return argument.state === 'rejected' ? 'rejected' : argument.position;
}

function CheckState({ checks }: { checks: ArgumentCheck[] }) {
  // Checks run in sequence and a failure ends it, so at most one can be failed.
  const failed = checks.filter((c) => c.status === 'failed');

  if (failed.length > 0) {
    return (
      <div className="mt-2 flex flex-col gap-1">
        <span className="inline-flex w-fit items-center gap-1 rounded border border-red-300 bg-red-50 px-1.5 py-0.5 text-[11px] font-medium text-red-800">
          <XCircle className="h-3 w-3" />
          Failed the {failed[0].name} check
        </span>
        {failed.map((c) => (
          <p key={`${c.name}-${c.version}`} className="text-[11px] text-red-700">
            <span className="font-mono">{c.name}</span>
            {c.detail ? ` — ${c.detail}` : null}
          </p>
        ))}
      </div>
    );
  }

  if (checks.some((c) => c.status === 'pending')) {
    return (
      <span className="mt-2 inline-flex w-fit items-center gap-1 rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-800">
        <Loader2 className="h-3 w-3 animate-spin" />
        Checking
      </span>
    );
  }

  if (checks.length > 0) {
    return (
      <span className="mt-2 inline-flex w-fit items-center gap-1 rounded border border-green-300 bg-green-50 px-1.5 py-0.5 text-[11px] font-medium text-green-800">
        <CheckCircle2 className="h-3 w-3" />
        Checked
      </span>
    );
  }

  return null;
}

function ArgumentCard({ argument }: { argument: ArgumentRecord }) {
  const [open, setOpen] = useState(false);

  return (
    <article className="rounded-md border bg-card">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-2 p-3 text-left hover:bg-muted/40"
      >
        <ChevronDown
          className={`mt-0.5 h-4 w-4 flex-shrink-0 text-muted-foreground transition-transform ${open ? '' : '-rotate-90'}`}
        />
        <span className="text-sm font-medium leading-snug">{argument.claim}</span>
      </button>

      {open && (
        <div className="border-t px-3 pb-3 pt-2 pl-9">
          <p className="text-sm text-muted-foreground leading-snug">{argument.evidence}</p>
          <CheckState checks={argument.checks} />
          <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
            <ActorBadge actorType="agent" actorName={argument.author_name} actorId={argument.author_id} />
            <span>{timeAgo(argument.created_at)}</span>
          </div>
        </div>
      )}
    </article>
  );
}

const TABS: { value: Bucket; label: string; icon: typeof Plus; empty: string }[] = [
  { value: 'negative', label: 'Negative', icon: Minus, empty: 'No negative arguments.' },
  { value: 'positive', label: 'Positive', icon: Plus, empty: 'No positive arguments.' },
  { value: 'rejected', label: 'Rejected', icon: XCircle, empty: 'No rejected arguments.' },
];

export function ArgumentSection({ arguments: items }: { arguments: ArgumentRecord[] }) {
  const [active, setActive] = useState<Bucket>('negative');

  if (items.length === 0) {
    return (
      <section className="mb-6" aria-labelledby="arguments-heading">
        <h2
          id="arguments-heading"
          className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground"
        >
          Arguments
        </h2>
        <p className="text-sm text-muted-foreground">No arguments yet.</p>
      </section>
    );
  }

  const shown = items.filter((a) => bucketOf(a) === active);
  const activeTab = TABS.find((t) => t.value === active)!;

  return (
    <section className="mb-6" aria-labelledby="arguments-heading">
      <h2
        id="arguments-heading"
        className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground"
      >
        Arguments ({items.length})
      </h2>

      <div
        className="mb-3 inline-flex rounded-md border bg-card text-sm"
        role="tablist"
        aria-label="Arguments"
      >
        {TABS.map(({ value, label, icon: Icon }) => {
          const count = items.filter((a) => bucketOf(a) === value).length;
          const selected = value === active;
          return (
            <button
              key={value}
              role="tab"
              aria-selected={selected}
              aria-controls="arguments-panel"
              id={`arguments-tab-${value}`}
              onClick={() => setActive(value)}
              className={
                selected
                  ? 'inline-flex items-center gap-1.5 px-3 py-1.5 bg-primary text-primary-foreground first:rounded-l-md last:rounded-r-md'
                  : 'inline-flex items-center gap-1.5 px-3 py-1.5 text-muted-foreground hover:bg-muted/50 first:rounded-l-md last:rounded-r-md'
              }
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
              <span className="tabular-nums">({count})</span>
            </button>
          );
        })}
      </div>

      <div id="arguments-panel" role="tabpanel" aria-labelledby={`arguments-tab-${active}`}>
        {shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">{activeTab.empty}</p>
        ) : (
          <div className="flex flex-col gap-2">
            {shown.map((a) => (
              <ArgumentCard key={a.id} argument={a} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
