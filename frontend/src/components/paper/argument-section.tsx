'use client';

import { useState } from 'react';
import { ActorBadge } from '@/components/shared/actor-badge';
import { timeAgo } from '@/lib/utils';
import { Check, ChevronDown, Circle, Loader2, Minus, Plus, X, XCircle } from 'lucide-react';

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

type Bucket = 'negative' | 'positive' | 'pending' | 'rejected';

/**
 * Which tab an argument belongs to.
 *
 * The position tabs are the paper's standing case, so only arguments that
 * cleared the whole pipeline appear there. Anything still being checked sits in
 * Pending whichever side it argues — until every check has passed, there is no
 * reason for a reader to weigh it.
 */
function bucketOf(argument: ArgumentRecord): Bucket {
  if (argument.state === 'rejected') return 'rejected';
  if (argument.state === 'pending') return 'pending';
  return argument.position;
}

/**
 * The checks every argument runs, in order.
 *
 * Mirrors CHECKS in backend/app/core/checks.py. Kept in step by
 * backend/tests/test_check_pipeline_ui.py, which fails if the two drift — the
 * rail would otherwise quietly render one stage short when a check is added.
 */
const PIPELINE = ['moderation', 'validity', 'relevance', 'uniqueness'] as const;

type StageStatus = 'passed' | 'failed' | 'pending' | 'not_run';

interface Stage {
  name: string;
  status: StageStatus;
  detail: string | null;
}

/**
 * Where each stage of the pipeline stands for one argument.
 *
 * Checks are queued lazily — only the first exists at submission and each
 * queues its successor when it passes — so a stage with no row has either not
 * been reached yet or never will be, because an earlier one failed. Both read
 * as `not_run`.
 *
 * A name can carry rows at several versions, since re-running at a new version
 * writes a row rather than overwriting. The newest is what the argument stands
 * on, so the last row wins.
 */
function stagesOf(checks: ArgumentCheck[]): Stage[] {
  return PIPELINE.map((name) => {
    const row = checks.findLast((c) => c.name === name);
    return row
      ? { name, status: row.status, detail: row.detail }
      : { name, status: 'not_run' as const, detail: null };
  });
}

const STAGE_LABEL: Record<StageStatus, string> = {
  passed: 'passed',
  failed: 'failed',
  pending: 'checking',
  not_run: 'not run',
};

function StageIcon({ status }: { status: StageStatus }) {
  if (status === 'passed') return <Check className="h-3.5 w-3.5 text-green-600" />;
  if (status === 'failed') return <X className="h-3.5 w-3.5 text-red-600" />;
  if (status === 'pending') {
    return <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-600" />;
  }
  return <Circle className="h-3.5 w-3.5 text-muted-foreground/30" />;
}

/** The compact rail, sitting at the right of an argument's header row. */
function CheckPipeline({ checks }: { checks: ArgumentCheck[] }) {
  const stages = stagesOf(checks);

  return (
    <span role="list" aria-label="Check pipeline" className="mt-0.5 flex flex-shrink-0 items-center gap-1">
      {stages.map((stage) => (
        <span
          key={stage.name}
          role="listitem"
          title={`${stage.name}: ${STAGE_LABEL[stage.status]}`}
          aria-label={`${stage.name}: ${STAGE_LABEL[stage.status]}`}
        >
          <StageIcon status={stage.status} />
        </span>
      ))}
    </span>
  );
}

/** The named breakdown, shown when the card is open. */
function CheckBreakdown({ checks }: { checks: ArgumentCheck[] }) {
  const stages = stagesOf(checks);

  return (
    <dl className="mt-3 space-y-1">
      {stages.map((stage) => (
        <div key={stage.name} className="flex items-baseline gap-2 text-[11px]">
          <dt className="flex items-center gap-1.5">
            <StageIcon status={stage.status} />
            <span
              className={`font-mono ${
                stage.status === 'not_run' ? 'text-muted-foreground/50' : 'text-muted-foreground'
              }`}
            >
              {stage.name}
            </span>
          </dt>
          {stage.status === 'failed' && <dd className="text-red-700">{stage.detail}</dd>}
        </div>
      ))}
    </dl>
  );
}

function ArgumentCard({ argument }: { argument: ArgumentRecord }) {
  const [open, setOpen] = useState(false);

  return (
    <article className="rounded-md border bg-card">
      <div className="flex w-full items-start gap-2 p-3 hover:bg-muted/40">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="flex flex-1 items-start gap-2 text-left"
        >
          <ChevronDown
            className={`mt-0.5 h-4 w-4 flex-shrink-0 text-muted-foreground transition-transform ${open ? '' : '-rotate-90'}`}
          />
          <span className="text-sm font-medium leading-snug">{argument.claim}</span>
        </button>
        <CheckPipeline checks={argument.checks} />
      </div>

      {open && (
        <div className="border-t px-3 pb-3 pt-2 pl-9">
          <p className="text-sm text-muted-foreground leading-snug">{argument.evidence}</p>
          <CheckBreakdown checks={argument.checks} />
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
  { value: 'pending', label: 'Pending', icon: Loader2, empty: 'Nothing being checked.' },
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
