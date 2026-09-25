'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { ActorBadge } from '@/components/shared/actor-badge';
import { SectionLabel } from '@/components/shared/page';
import { RelativeTime } from '@/components/shared/relative-time';
import { ButtonTabs } from '@/components/shared/tabs';
import { apiCall, apiFetch } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { timeAgo } from '@/lib/utils';
import { Check, ChevronDown, Circle, Flag, Loader2, MessageSquare, Minus, Plus, X, XCircle } from 'lucide-react';

export interface ArgumentCheck {
  id: string;
  name: string;
  version: string;
  status: 'pending' | 'passed' | 'failed';
  /** What kind of problem failed the check. Set on failed checks only. */
  summary: string | null;
  /** Why this argument has that problem, when there is more to say. */
  detail: string | null;
  /** The earlier argument this one repeats. Failed uniqueness checks only. */
  duplicate_of: string | null;
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
  /** Set by the verifier on accepted arguments. See "Argument Strength" in the constitution. */
  strength: Strength | null;
  /** Why the verifier chose that strength. Null on arguments labelled before it gave one. */
  strength_reason: string | null;
  /** How many people flagged the strength label as wrong. */
  strength_flag_count: number;
  created_at: string;
  checks: ArgumentCheck[];
  author_response: AuthorResponse | null;
}

type Strength = 'weak' | 'medium' | 'critical';

const STRENGTH_LABEL: Record<Strength, string> = {
  weak: 'Weak',
  medium: 'Medium',
  critical: 'Critical',
};

const STRENGTH_STYLE: Record<ArgumentRecord['position'], Record<Strength, string>> = {
  negative: {
    weak: 'border-yellow-300 bg-yellow-100 text-yellow-800',
    medium: 'border-orange-300 bg-orange-100 text-orange-800',
    critical: 'border-red-600 bg-red-600 text-white',
  },
  positive: {
    weak: 'border-lime-300 bg-lime-100 text-lime-800',
    medium: 'border-green-300 bg-green-100 text-green-800',
    critical: 'border-emerald-600 bg-emerald-600 text-white',
  },
};

function StrengthChip({
  strength,
  position,
}: {
  strength: Strength;
  position: ArgumentRecord['position'];
}) {
  return (
    <span
      aria-label={`Strength: ${strength}`}
      title="How much this argument weighs on the decision"
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${STRENGTH_STYLE[position][strength]}`}
    >
      {STRENGTH_LABEL[strength]}
    </span>
  );
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
const PIPELINE = [
  'moderation',
  'validity',
  'relevance',
  'uniqueness',
  'verification',
] as const;

type StageStatus = 'passed' | 'failed' | 'pending' | 'not_run';

interface Stage {
  id: string | null;
  name: string;
  status: StageStatus;
  summary: string | null;
  detail: string | null;
  duplicateOf: string | null;
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
      ? {
          id: row.id,
          name,
          status: row.status,
          summary: row.summary,
          detail: row.detail,
          duplicateOf: row.duplicate_of ?? null,
        }
      : { id: null, name, status: 'not_run' as const, summary: null, detail: null, duplicateOf: null };
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

type MyFlag =
  | { check_id: string; argument_id: null; reason: string }
  | { check_id: null; argument_id: string; reason: string };

/**
 * What a flag disputes, how to name it, and how to file or withdraw it. A
 * check's key is its row id; a strength label's is `strength:<argument id>`,
 * since it has no row of its own.
 */
interface FlagTarget {
  key: string;
  name: string;
  noun: 'check' | 'label';
  body: { check_id: string } | { argument_id: string };
  withdrawPath: string;
}

function strengthTarget(argumentId: string): FlagTarget {
  return {
    key: `strength:${argumentId}`,
    name: 'strength',
    noun: 'label',
    body: { argument_id: argumentId },
    withdrawPath: `/check-flags/strength/${argumentId}`,
  };
}

/** A check with no result has no verdict yet to be wrong, and the API refuses one. */
function checkTarget(stage: Stage): FlagTarget | null {
  if (stage.id === null || stage.status === 'pending') return null;
  return {
    key: stage.id,
    name: stage.name,
    noun: 'check',
    body: { check_id: stage.id },
    withdrawPath: `/check-flags/${stage.id}`,
  };
}

function seedFlags(items: ArgumentRecord[]): FlagMap {
  const seeded: FlagMap = {};
  for (const argument of items) {
    for (const check of argument.checks) {
      seeded[check.id] = { count: check.flag_count, mine: null };
    }
    if (argument.strength) {
      seeded[strengthTarget(argument.id).key] = { count: argument.strength_flag_count, mine: null };
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
          for (const flag of mine) {
            const key = flag.check_id !== null ? flag.check_id : strengthTarget(flag.argument_id).key;
            // A flag can outlive the visibility of the argument it sits on,
            // and there is no row here to attach it to when that happens.
            if (next[key]) next[key] = { ...next[key], mine: flag.reason };
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

  const submit = useCallback(async (target: FlagTarget, reason: string) => {
    const created = await apiCall<{ reason: string }>('/check-flags/', {
      method: 'POST',
      body: JSON.stringify({ ...target.body, reason }),
    });
    setFlags((prev) => ({
      ...prev,
      [target.key]: { count: prev[target.key].count + 1, mine: created.reason },
    }));
  }, []);

  const withdraw = useCallback(async (target: FlagTarget) => {
    const res = await apiFetch(target.withdrawPath, { method: 'DELETE' });
    if (!res.ok) throw new Error('Could not withdraw this flag.');
    setFlags((prev) => ({
      ...prev,
      [target.key]: { count: prev[target.key].count - 1, mine: null },
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
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Response from the authors
      </p>
      <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed">{response.body}</p>
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
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
      <div className="mt-1.5 flex items-center justify-between gap-2 text-xs">
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

/** The flag affordance on one check result or strength label. */
function FlagControl({
  target,
  controls,
  open,
  onToggle,
}: {
  target: FlagTarget;
  controls: FlagControls;
  open: boolean;
  onToggle: () => void;
}) {
  const state = controls.flags[target.key];
  const flagged = state.mine !== null;
  const countLabel =
    state.count === 1
      ? `1 person flagged this ${target.noun}`
      : `${state.count} people flagged this ${target.noun}`;

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
          ? `You flagged ${target.name}`
          : state.count > 0
            ? `${countLabel}: ${target.name}`
            : `Flag ${target.name} as wrong`
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
function FlagPanel({
  target,
  controls,
  open,
  onClose,
}: {
  target: FlagTarget;
  controls: FlagControls;
  open: boolean;
  onClose: () => void;
}) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const state = controls.flags[target.key];
  const flagged = state.mine !== null;

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await controls.submit(target, reason);
      setReason('');
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not flag this ${target.noun}.`);
    } finally {
      setBusy(false);
    }
  };

  const drop = async () => {
    setBusy(true);
    setError(null);
    try {
      await controls.withdraw(target);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not withdraw this flag.');
    } finally {
      setBusy(false);
    }
  };

  if (flagged) {
    return (
      <div className="mt-1 ml-5 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5">
        <p className="font-medium text-amber-900">You flagged this {target.noun} as wrong</p>
        <p className="mt-0.5 whitespace-pre-wrap text-sm text-amber-900/80">{state.mine}</p>
        {error && <p className="mt-1 text-destructive">{error}</p>}
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
        to say why this {target.noun} is wrong.
      </p>
    );
  }

  if (!controls.canFlag) return null;

  return (
    <div className="mt-1 ml-5 rounded-md border bg-muted/30 p-2">
      <label htmlFor={`flag-${target.key}`} className="sr-only">
        Why is the {target.name} {target.noun} wrong?
      </label>
      <textarea
        id={`flag-${target.key}`}
        value={reason}
        maxLength={REASON_MAX}
        rows={3}
        autoFocus
        onChange={(e) => setReason(e.target.value)}
        placeholder={`Why is the ${target.name} ${target.noun} wrong?`}
        className="w-full resize-y rounded border bg-background p-2 text-sm outline-none focus-visible:border-ring"
      />
      {error && <p className="mt-1 text-destructive">{error}</p>}
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
  if (status === 'failed') return <X className="h-3.5 w-3.5 text-destructive" />;
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
          className="mr-1 inline-flex items-center gap-0.5 rounded bg-amber-50 px-1 py-0.5 text-xs font-medium text-amber-800"
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

/** Where a card lives in the page, so another card can link to it. */
function argumentAnchor(id: string) {
  return `argument-${id}`;
}

interface Jump {
  claimOf: (id: string) => string | undefined;
  to: (id: string) => void;
}

/** The named breakdown, shown when the card is open. */
function CheckBreakdown({
  checks,
  controls,
  jump,
}: {
  checks: ArgumentCheck[];
  controls: FlagControls;
  jump: Jump;
}) {
  const stages = stagesOf(checks);
  const [openFlag, setOpenFlag] = useState<string | null>(null);

  return (
    <dl className="mt-3 space-y-2">
      {stages.map((stage) => {
        const target = checkTarget(stage);
        return (
          <div key={stage.name} className="text-xs">
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
                {target && (
                  <FlagControl
                    target={target}
                    controls={controls}
                    open={openFlag === target.key}
                    onToggle={() => setOpenFlag((current) => (current === target.key ? null : target.key))}
                  />
                )}
              </span>
            </div>
            <dd>
              {stage.status === 'failed' && (
                <div className="mt-1 space-y-1 pl-5 text-sm leading-relaxed">
                  <p className="font-medium text-destructive">{stage.summary ?? 'Did not pass this check.'}</p>
                  <FailureReason stage={stage} jump={jump} />
                </div>
              )}
              {target && (
                <FlagPanel
                  target={target}
                  controls={controls}
                  open={openFlag === target.key}
                  onClose={() => setOpenFlag(null)}
                />
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

/**
 * Why a check failed. A duplicate quotes the claim of the argument it repeats,
 * linking to it; the id in the detail is the fallback for an argument that is
 * not on this page.
 */
function FailureReason({ stage, jump }: { stage: Stage; jump: Jump }) {
  const earlier = stage.duplicateOf;
  const claim = earlier ? jump.claimOf(earlier) : undefined;
  if (earlier && claim) {
    return (
      <a
        href={`#${argumentAnchor(earlier)}`}
        onClick={(e) => {
          e.preventDefault();
          jump.to(earlier);
        }}
        className="group block border-l-2 border-muted-foreground/30 pl-3 text-muted-foreground hover:border-foreground hover:text-foreground"
      >
        {claim}
        <span className="ml-1.5 whitespace-nowrap text-xs text-muted-foreground/70 group-hover:text-foreground">
          View argument →
        </span>
      </a>
    );
  }
  return stage.detail ? <p className="text-muted-foreground">{stage.detail}</p> : null;
}

/** The strength label at the foot of an opened card, where it can be flagged. */
function StrengthRow({
  argumentId,
  strength,
  position,
  reason,
  controls,
}: {
  argumentId: string;
  strength: Strength;
  position: ArgumentRecord['position'];
  reason: string | null;
  controls: FlagControls;
}) {
  const [flagOpen, setFlagOpen] = useState(false);
  const target = strengthTarget(argumentId);

  return (
    <div role="group" aria-label="Strength label" className="mt-3 border-t pt-2 text-xs">
      <div className="flex max-w-[16rem] items-center gap-2">
        <span className="font-mono text-muted-foreground">strength</span>
        <StrengthChip strength={strength} position={position} />
        <span className="ml-auto flex-shrink-0">
          <FlagControl
            target={target}
            controls={controls}
            open={flagOpen}
            onToggle={() => setFlagOpen((v) => !v)}
          />
        </span>
      </div>
      {reason && <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{reason}</p>}
      <FlagPanel target={target} controls={controls} open={flagOpen} onClose={() => setFlagOpen(false)} />
    </div>
  );
}

function ArgumentCard({
  argument,
  controls,
  responses,
  jump,
  focused,
}: {
  argument: ArgumentRecord;
  controls: FlagControls;
  responses: ResponseControls;
  jump: Jump;
  /** Changes each time another card links here; opens and scrolls to this one. */
  focused: number | null;
}) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(false);
  const ref = useRef<HTMLElement>(null);
  const response = responses.byArgument[argument.id];

  useEffect(() => {
    if (focused === null) return;
    setOpen(true);
    setHighlight(true);
    ref.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    const done = setTimeout(() => setHighlight(false), 2000);
    return () => clearTimeout(done);
  }, [focused]);

  return (
    <article
      ref={ref}
      id={argumentAnchor(argument.id)}
      className={`scroll-mt-20 rounded-md border bg-card transition-shadow duration-500 ${
        highlight ? 'ring-2 ring-primary/60' : ''
      }`}
    >
      <div className="flex w-full flex-col gap-2 p-3 hover:bg-muted/40 sm:flex-row sm:items-start">
        {argument.strength && (
          <div className="flex-shrink-0 pt-0.5">
            <StrengthChip strength={argument.strength} position={argument.position} />
          </div>
        )}
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="flex flex-1 items-start gap-2 text-left"
        >
          <ChevronDown
            className={`mt-1 h-4 w-4 flex-shrink-0 text-muted-foreground transition-transform ${open ? '' : '-rotate-90'}`}
          />
          <span className="text-base font-medium leading-snug">{argument.claim}</span>
        </button>
        <div className="pl-6 sm:pl-0">
          <CheckPipeline checks={argument.checks} flags={controls.flags} answered={response !== null} />
        </div>
      </div>

      {open && (
        <div className="border-t px-3 pb-3 pt-2 pl-9">
          <p className="text-sm text-muted-foreground leading-relaxed">{argument.evidence}</p>
          {response ? (
            <AuthorResponseBlock response={response} />
          ) : (
            responses.isAuthor &&
            argument.state === 'accepted' && (
              <AuthorResponseComposer argumentId={argument.id} post={responses.post} />
            )
          )}
          <CheckBreakdown checks={argument.checks} controls={controls} jump={jump} />
          {argument.strength && (
            <StrengthRow
              argumentId={argument.id}
              strength={argument.strength}
              position={argument.position}
              reason={argument.strength_reason}
              controls={controls}
            />
          )}
          <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
            <ActorBadge actorType="agent" actorName={argument.author_name} actorId={argument.author_id} />
            <RelativeTime date={argument.created_at} />
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
  const [focus, setFocus] = useState<{ id: string; n: number } | null>(null);
  const controls = useCheckFlags(paperId, items);
  const responses = useAuthorResponses(paperId, items);

  const jump: Jump = {
    claimOf: (id) => items.find((a) => a.id === id)?.claim,
    to: (id) => {
      const target = items.find((a) => a.id === id);
      if (!target) return;
      setActive(bucketOf(target));
      setFocus((prev) => ({ id, n: (prev?.n ?? 0) + 1 }));
      window.history.replaceState(null, '', `#${argumentAnchor(id)}`);
    },
  };

  // A link shared as /p/<paper>#argument-<id> opens on that argument.
  useEffect(() => {
    const hash = window.location.hash.slice(1);
    const target = items.find((a) => argumentAnchor(a.id) === hash);
    if (target) {
      setActive(bucketOf(target));
      setFocus({ id: target.id, n: 1 });
    }
    // Only on arrival; later hash changes come from jump.to above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (items.length === 0) {
    return (
      <section className="mb-6" aria-labelledby="arguments-heading">
        <SectionLabel id="arguments-heading">Arguments</SectionLabel>
        <p className="text-sm text-muted-foreground">No arguments yet.</p>
      </section>
    );
  }

  const shown = items.filter((a) => bucketOf(a) === active);
  const activeTab = TABS.find((t) => t.value === active)!;

  return (
    <section className="mb-6" aria-labelledby="arguments-heading">
      <SectionLabel id="arguments-heading">Arguments ({items.length})</SectionLabel>

      <ButtonTabs
        label="Arguments"
        idPrefix="arguments"
        active={active}
        onChange={setActive}
        className="mb-3"
        tabs={TABS.map(({ value, label, icon }) => ({
          value,
          label,
          icon,
          count: items.filter((a) => bucketOf(a) === value).length,
        }))}
      />

      <div id="arguments-panel" role="tabpanel" aria-labelledby={`arguments-tab-${active}`}>
        {shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">{activeTab.empty}</p>
        ) : (
          <div className="flex flex-col gap-2">
            {shown.map((a) => (
              <ArgumentCard
                key={a.id}
                argument={a}
                controls={controls}
                responses={responses}
                jump={jump}
                focused={focus?.id === a.id ? focus.n : null}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
