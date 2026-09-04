'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { ActorBadge } from '@/components/shared/actor-badge';
import { apiCall, apiFetch } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { timeAgo } from '@/lib/utils';
import { Check, ChevronDown, Circle, Flag, Loader2, MessageSquare, Minus, Plus, X, XCircle } from 'lucide-react';

export interface ArgumentCheck {
  id: string;
  name: string;
  version: string;
  status: 'pending' | 'passed' | 'failed';
  detail: string | null;
  flag_count: number;
}

export interface AuthorResponse {
  id: string;
  argument_id: string;
  author_id: string;
  author_name: string;
  body: string;
  created_at: string;
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
  author_response: AuthorResponse | null;
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
  id: string | null;
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
      ? { id: row.id, name, status: row.status, detail: row.detail }
      : { id: null, name, status: 'not_run' as const, detail: null };
  });
}


/**
 * A check's dispute state as this reader sees it.
 *
 * How many people flagged a check is public; what they wrote is not. So the
 * count arrives with the argument, and `mine` — the only reason text this
 * reader is entitled to — is fetched separately and only when they are logged
 * in as a human.
 */
interface FlagState {
  count: number;
  mine: string | null;
}

type FlagMap = Record<string, FlagState>;

interface MyFlag {
  check_id: string;
  reason: string;
}

function seedFlags(items: ArgumentRecord[]): FlagMap {
  const seeded: FlagMap = {};
  for (const argument of items) {
    for (const check of argument.checks) {
      seeded[check.id] = { count: check.flag_count, mine: null };
    }
  }
  return seeded;
}

/**
 * Flag counts for a paper's checks, and which of them this reader flagged.
 *
 * The page is rendered on the server, where the reader's token does not exist,
 * so "you already flagged this" cannot come down with the arguments. It is
 * asked for once on mount and matched on check id.
 */
function useCheckFlags(paperId: string, items: ArgumentRecord[]) {
  const user = useAuthStore((s) => s.user);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const canFlag = isAuthenticated && user?.actor_type === 'human';

  const [flags, setFlags] = useState<FlagMap>(() => seedFlags(items));

  useEffect(() => {
    if (!canFlag) return;
    let cancelled = false;

    apiCall<MyFlag[]>(`/check-flags/mine?paper_id=${paperId}`)
      .then((mine) => {
        if (cancelled) return;
        setFlags((prev) => {
          const next = { ...prev };
          for (const { check_id, reason } of mine) {
            // A flag can outlive the visibility of the argument it sits on,
            // and there is no row here to attach it to when that happens.
            if (next[check_id]) next[check_id] = { ...next[check_id], mine: reason };
          }
          return next;
        });
      })
      .catch(() => {
        // Losing this leaves the reader with the counts and without their own
        // reasons. The unique key, not this fetch, is what stops a second flag.
      });

    return () => {
      cancelled = true;
    };
  }, [canFlag, paperId]);

  const submit = useCallback(async (checkId: string, reason: string) => {
    const created = await apiCall<{ reason: string }>('/check-flags/', {
      method: 'POST',
      body: JSON.stringify({ check_id: checkId, reason }),
    });
    setFlags((prev) => ({
      ...prev,
      [checkId]: { count: prev[checkId].count + 1, mine: created.reason },
    }));
  }, []);

  const withdraw = useCallback(async (checkId: string) => {
    const res = await apiFetch(`/check-flags/${checkId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Could not withdraw this flag.');
    setFlags((prev) => ({
      ...prev,
      [checkId]: { count: prev[checkId].count - 1, mine: null },
    }));
  }, []);

  return { flags, canFlag, isAuthenticated, submit, withdraw };
}

type FlagControls = ReturnType<typeof useCheckFlags>;

const RESPONSE_MAX = 1_000;

/**
 * The authors' answers on this paper, and whether this reader may write one.
 *
 * Authorship is granted in the database and nowhere else, so the reader cannot
 * know it from the page: the server renders without their token, and the answer
 * is asked for once on mount, exactly as their own check flags are.
 */
function useAuthorResponses(paperId: string, items: ArgumentRecord[]) {
  const user = useAuthStore((s) => s.user);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isHuman = isAuthenticated && user?.actor_type === 'human';

  const [byArgument, setByArgument] = useState<Record<string, AuthorResponse | null>>(
    () => Object.fromEntries(items.map((a) => [a.id, a.author_response])),
  );
  const [isAuthor, setIsAuthor] = useState(false);

  useEffect(() => {
    if (!isHuman) return;
    let cancelled = false;

    apiCall<{ is_author: boolean }>(`/papers/${paperId}/authorship`)
      .then((answer) => {
        if (!cancelled) setIsAuthor(answer.is_author);
      })
      .catch(() => {
        // Without an answer the composer stays hidden, which is what a reader
        // who is not an author would see anyway. The endpoint decides.
      });

    return () => {
      cancelled = true;
    };
  }, [isHuman, paperId]);

  const post = useCallback(async (argumentId: string, body: string) => {
    const created = await apiCall<AuthorResponse>(`/arguments/${argumentId}/response`, {
      method: 'POST',
      body: JSON.stringify({ body }),
    });
    setByArgument((prev) => ({ ...prev, [argumentId]: created }));
  }, []);

  return { byArgument, isAuthor, post };
}

type ResponseControls = ReturnType<typeof useAuthorResponses>;

/** The authors' answer, as everyone reading the paper sees it. */
function AuthorResponseBlock({ response }: { response: AuthorResponse }) {
  return (
    <div className="mt-3 rounded-md border border-l-2 border-l-primary bg-muted/30 px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Response from the authors
      </p>
      <p className="mt-1 whitespace-pre-wrap text-sm leading-snug">{response.body}</p>
      <p className="mt-1.5 text-xs text-muted-foreground">
        {response.author_name} · {timeAgo(response.created_at)}
      </p>
    </div>
  );
}

/** Offered only to an author of the paper, on an accepted argument nobody has answered. */
function AuthorResponseComposer({
  argumentId,
  post,
}: {
  argumentId: string;
  post: (argumentId: string, body: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await post(argumentId, body);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not post this response.');
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-3 inline-flex items-center gap-1.5 rounded border px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <MessageSquare className="h-3.5 w-3.5" />
        Respond as an author
      </button>
    );
  }

  return (
    <div className="mt-3 rounded-md border bg-muted/30 p-2">
      <label htmlFor={`response-${argumentId}`} className="sr-only">
        Your response to this argument
      </label>
      <textarea
        id={`response-${argumentId}`}
        value={body}
        maxLength={RESPONSE_MAX}
        rows={4}
        autoFocus
        onChange={(e) => setBody(e.target.value)}
        placeholder="Answer this argument. Posted publicly under your name, and cannot be edited."
        className="w-full resize-y rounded border bg-background p-2 text-sm outline-none focus-visible:border-ring"
      />
      {error && <p className="mt-1 text-[11px] text-red-700">{error}</p>}
      <div className="mt-1.5 flex items-center justify-between gap-2 text-[11px]">
        <span className="tabular-nums text-muted-foreground">
          {RESPONSE_MAX - body.length} characters left
        </span>
        <span className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              setError(null);
            }}
            className="rounded px-2 py-1 text-muted-foreground hover:bg-muted"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={send}
            disabled={busy || body.trim().length === 0}
            className="rounded bg-primary px-2 py-1 font-medium text-primary-foreground disabled:opacity-40"
          >
            {busy ? 'Posting…' : 'Post response'}
          </button>
        </span>
      </div>
    </div>
  );
}

const REASON_MAX = 2_000;

/**
 * The flag affordance on one stage of one argument's pipeline.
 *
 * A check with no result carries none: there is no verdict yet to be wrong,
 * and the API refuses one for the same reason.
 */
function CheckFlagControl({
  stage,
  controls,
  open,
  onToggle,
}: {
  stage: Stage;
  controls: FlagControls;
  open: boolean;
  onToggle: () => void;
}) {
  if (stage.id === null || stage.status === 'pending') return null;

  const state = controls.flags[stage.id];
  const flagged = state.mine !== null;
  const countLabel = state.count === 1 ? '1 person flagged this check' : `${state.count} people flagged this check`;

  if (controls.isAuthenticated && !controls.canFlag) {
    return state.count > 0 ? (
      <span className="inline-flex items-center gap-1 text-amber-700" aria-label={countLabel}>
        <Flag className="h-3 w-3" />
        <span className="tabular-nums">{state.count}</span>
      </span>
    ) : null;
  }

  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      aria-label={
        flagged
          ? `You flagged ${stage.name}`
          : state.count > 0
            ? `${countLabel}: ${stage.name}`
            : `Flag ${stage.name} as wrong`
      }
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 transition-colors ${
        flagged || state.count > 0
          ? 'text-amber-700 hover:bg-amber-50'
          : 'text-muted-foreground/50 hover:bg-muted hover:text-foreground'
      }`}
    >
      <Flag className={`h-3 w-3 ${flagged ? 'fill-amber-400' : ''}`} />
      {state.count > 0 ? <span className="tabular-nums">{state.count}</span> : <span>Flag</span>}
    </button>
  );
}

/**
 * What sits under a stage once its flag is opened: the composer, the reason
 * this reader already filed, or the nudge to log in.
 */
function CheckFlagPanel({
  stage,
  controls,
  open,
  onClose,
}: {
  stage: Stage;
  controls: FlagControls;
  open: boolean;
  onClose: () => void;
}) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const checkId = stage.id;
  if (checkId === null || stage.status === 'pending') return null;

  const state = controls.flags[checkId];
  const flagged = state.mine !== null;

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await controls.submit(checkId, reason);
      setReason('');
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not flag this check.');
    } finally {
      setBusy(false);
    }
  };

  const drop = async () => {
    setBusy(true);
    setError(null);
    try {
      await controls.withdraw(checkId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not withdraw this flag.');
    } finally {
      setBusy(false);
    }
  };

  if (flagged) {
    return (
      <div className="mt-1 ml-5 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5">
        <p className="font-medium text-amber-900">You flagged this check as wrong</p>
        <p className="mt-0.5 whitespace-pre-wrap text-amber-900/80">{state.mine}</p>
        {error && <p className="mt-1 text-red-700">{error}</p>}
        <button
          type="button"
          onClick={drop}
          disabled={busy}
          className="mt-1 text-amber-800 underline hover:text-amber-900 disabled:opacity-40"
        >
          {busy ? 'Withdrawing…' : 'Withdraw'}
        </button>
      </div>
    );
  }

  if (!open) return null;

  if (!controls.isAuthenticated) {
    return (
      <p className="mt-1 ml-5 text-muted-foreground">
        <Link href="/auth/login" className="underline hover:text-foreground">
          Log in
        </Link>{' '}
        to say why this check is wrong.
      </p>
    );
  }

  if (!controls.canFlag) return null;

  return (
    <div className="mt-1 ml-5 rounded-md border bg-muted/30 p-2">
      <label htmlFor={`flag-${checkId}`} className="sr-only">
        Why is the {stage.name} check wrong?
      </label>
      <textarea
        id={`flag-${checkId}`}
        value={reason}
        maxLength={REASON_MAX}
        rows={3}
        autoFocus
        onChange={(e) => setReason(e.target.value)}
        placeholder={`Why is the ${stage.name} check wrong?`}
        className="w-full resize-y rounded border bg-background p-2 text-[12px] outline-none focus-visible:border-ring"
      />
      {error && <p className="mt-1 text-red-700">{error}</p>}
      <div className="mt-1.5 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={() => {
            setError(null);
            onClose();
          }}
          className="rounded px-2 py-1 text-muted-foreground hover:bg-muted"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={send}
          disabled={busy || reason.trim().length === 0}
          className="rounded bg-primary px-2 py-1 font-medium text-primary-foreground disabled:opacity-40"
        >
          {busy ? 'Flagging…' : 'Flag as wrong'}
        </button>
      </div>
    </div>
  );
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
function CheckPipeline({
  checks,
  flags,
  answered,
}: {
  checks: ArgumentCheck[];
  flags: FlagMap;
  answered: boolean;
}) {
  const stages = stagesOf(checks);
  const flagged = stages.reduce(
    (total, stage) => total + (stage.id === null ? 0 : flags[stage.id].count),
    0,
  );
  const flagLabel = `${flagged} ${flagged === 1 ? 'flag' : 'flags'} on this argument's checks`;

  return (
    <span role="list" aria-label="Check pipeline" className="mt-0.5 flex flex-shrink-0 items-center gap-1">
      {answered && (
        <span
          role="listitem"
          aria-label="Answered by the authors"
          title="Answered by the authors"
          className="mr-1 inline-flex items-center text-primary"
        >
          <MessageSquare className="h-3.5 w-3.5" />
        </span>
      )}
      {flagged > 0 && (
        <span
          role="listitem"
          aria-label={flagLabel}
          title={flagLabel}
          className="mr-1 inline-flex items-center gap-0.5 rounded bg-amber-50 px-1 py-0.5 text-[10px] font-medium text-amber-800"
        >
          <Flag className="h-3 w-3" />
          <span className="tabular-nums">{flagged}</span>
        </span>
      )}
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
function CheckBreakdown({ checks, controls }: { checks: ArgumentCheck[]; controls: FlagControls }) {
  const stages = stagesOf(checks);
  const [openFlag, setOpenFlag] = useState<string | null>(null);

  return (
    <dl className="mt-3 space-y-1.5">
      {stages.map((stage) => (
        <div key={stage.name} className="text-[11px]">
          {/* Capped so the flag reads as belonging to the check beside it,
              rather than floating at the far edge of a wide card. */}
          <div className="flex max-w-[16rem] items-center gap-2">
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
            <span className="ml-auto flex-shrink-0">
              <CheckFlagControl
                stage={stage}
                controls={controls}
                open={openFlag === stage.id}
                onToggle={() => setOpenFlag((current) => (current === stage.id ? null : stage.id))}
              />
            </span>
          </div>
          <dd className="max-w-lg">
            {stage.status === 'failed' && (
              <p className="mt-0.5 pl-5 text-red-700">{stage.detail}</p>
            )}
            <CheckFlagPanel
              stage={stage}
              controls={controls}
              open={openFlag === stage.id}
              onClose={() => setOpenFlag(null)}
            />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function ArgumentCard({
  argument,
  controls,
  responses,
}: {
  argument: ArgumentRecord;
  controls: FlagControls;
  responses: ResponseControls;
}) {
  const [open, setOpen] = useState(false);
  const response = responses.byArgument[argument.id];

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
        <CheckPipeline checks={argument.checks} flags={controls.flags} answered={response !== null} />
      </div>

      {open && (
        <div className="border-t px-3 pb-3 pt-2 pl-9">
          <p className="text-sm text-muted-foreground leading-snug">{argument.evidence}</p>
          {response ? (
            <AuthorResponseBlock response={response} />
          ) : (
            responses.isAuthor &&
            argument.state === 'accepted' && (
              <AuthorResponseComposer argumentId={argument.id} post={responses.post} />
            )
          )}
          <CheckBreakdown checks={argument.checks} controls={controls} />
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

export function ArgumentSection({
  arguments: items,
  paperId,
}: {
  arguments: ArgumentRecord[];
  paperId: string;
}) {
  const [active, setActive] = useState<Bucket>('negative');
  const controls = useCheckFlags(paperId, items);
  const responses = useAuthorResponses(paperId, items);

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
              <ArgumentCard key={a.id} argument={a} controls={controls} responses={responses} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
