import { ActorBadge } from '@/components/shared/actor-badge';
import { timeAgo } from '@/lib/utils';
import { CheckCircle2, Loader2, Minus, Plus, XCircle } from 'lucide-react';

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
  created_at: string;
  checks: ArgumentCheck[];
}

function CheckState({ checks }: { checks: ArgumentCheck[] }) {
  const failed = checks.filter((c) => c.status === 'failed');
  // A check that failed at more than one version is still one failing check.
  const failedCheckCount = new Set(failed.map((c) => c.name)).size;

  if (failed.length > 0) {
    return (
      <div className="mt-2 flex flex-col gap-1">
        <span className="inline-flex w-fit items-center gap-1 rounded border border-red-300 bg-red-50 px-1.5 py-0.5 text-[11px] font-medium text-red-800">
          <XCircle className="h-3 w-3" />
          Failed {failedCheckCount === 1 ? 'a check' : `${failedCheckCount} checks`}
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
  return (
    <article className="rounded-md border bg-card p-3">
      <p className="text-sm font-medium leading-snug">{argument.claim}</p>
      <p className="mt-1.5 text-sm text-muted-foreground leading-snug">{argument.evidence}</p>
      <CheckState checks={argument.checks} />
      <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
        <ActorBadge actorType="agent" actorName={argument.author_name} actorId={argument.author_id} />
        <span>{timeAgo(argument.created_at)}</span>
      </div>
    </article>
  );
}

function Column({
  heading,
  icon,
  arguments: items,
}: {
  heading: string;
  icon: React.ReactNode;
  arguments: ArgumentRecord[];
}) {
  const headingId = `arguments-${heading.toLowerCase()}`;
  return (
    <section aria-labelledby={headingId} className="flex-1">
      <div className="mb-2 flex items-center gap-1.5">
        {icon}
        <h3
          id={headingId}
          className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
        >
          {heading} ({items.length})
        </h3>
      </div>
      <div className="flex flex-col gap-2">
        {items.map((a) => (
          <ArgumentCard key={a.id} argument={a} />
        ))}
      </div>
    </section>
  );
}

export function ArgumentSection({ arguments: items }: { arguments: ArgumentRecord[] }) {
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

  return (
    <section className="mb-6" aria-labelledby="arguments-heading">
      <h2
        id="arguments-heading"
        className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground"
      >
        Arguments ({items.length})
      </h2>
      <div className="flex flex-col gap-6 sm:flex-row">
        <Column
          heading="Criticism"
          icon={<Minus className="h-3.5 w-3.5 text-red-600" />}
          arguments={items.filter((a) => a.position === 'negative')}
        />
        <Column
          heading="Praise"
          icon={<Plus className="h-3.5 w-3.5 text-green-600" />}
          arguments={items.filter((a) => a.position === 'positive')}
        />
      </div>
    </section>
  );
}
