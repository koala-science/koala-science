'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import { AnnotatorGate } from '@/components/annotate/annotator-gate';
import { Markdown } from '@/components/shared/markdown';
import {
  QuestionInput,
  type Question,
} from '@/components/annotate/question-input';
interface Fact {
  fact_id: string;
  fact_text: string;
  sample_index: number;
  extractor_model: string;
}
import { useDebouncedDraftSave } from '@/components/annotate/use-debounced-save';
import { apiCall } from '@/lib/api';
import { formatSubmitError } from './submit-error';

type PageState = 'unstarted' | 'draft' | 'submitted';

interface FeedItem {
  id: string;
  author_id: string;
  author_name: string;
  is_focal: boolean;
  content_markdown: string;
  parent_id: string | null;
  created_at: string;
  facts: Fact[];
}

interface FocalAgentRef {
  agent_id: string;
  name: string;
  page_state: PageState;
}

interface PaperPagePayload {
  paper: {
    id: string;
    title: string;
    abstract: string;
    full_text: string | null;
    pdf_url: string | null;
  };
  focal_agents: FocalAgentRef[];
  feed: FeedItem[];
  questions: Question[];
  existing_responses: {
    by_agent: Record<
      string,
      {
        comments: Record<string, Record<string, unknown>>;
        facts?: Record<string, Record<string, unknown>>;
      }
    >;
    paper?: Record<string, unknown>;
  };
  page_state: PageState;
}

type AgentSlot = {
  comments: Record<string, Record<string, unknown>>;
  facts: Record<string, Record<string, unknown>>;
};

type Step =
  | { kind: 'paper' }
  | { kind: 'argument'; commentId: string; agentId: string; factId: string }
  | { kind: 'comment'; commentId: string; agentId: string };

export default function PaperAnnotationPage() {
  return (
    <AnnotatorGate>
      <PaperAnnotationContent />
    </AnnotatorGate>
  );
}

const _emptySlot = (): AgentSlot => ({ comments: {}, facts: {} });

function isQuestionVisible(q: Question, answers: Record<string, unknown>): boolean {
  if (!q.parent_value_match) return true;
  const parentJson = JSON.stringify(answers[q.parent_question_id!]);
  return q.parent_value_match.some((v) => JSON.stringify(v) === parentJson);
}


function FactQuestions({
  questions,
  answers,
  onChange,
}: {
  questions: Question[];
  answers: Record<string, unknown>;
  onChange: (questionId: string, value: unknown) => void;
}) {
  return (
    <div className="space-y-3 pt-2 border-t">
      {questions.map((q) => {
        if (!isQuestionVisible(q, answers)) return null;
        return (
          <div key={q.id} className="space-y-1">
            <div className="text-xs font-medium">{q.prompt}</div>
            <QuestionInput
              question={q}
              value={answers[q.id]}
              onChange={(v) => onChange(q.id, v)}
            />
          </div>
        );
      })}
    </div>
  );
}

function PaperAnnotationContent() {
  const params = useParams();
  const batchId = params.batchId as string;
  const paperId = params.paperId as string;

  const [payload, setPayload] = useState<PaperPagePayload | null>(null);
  const [byAgent, setByAgent] = useState<Record<string, AgentSlot>>({});
  const [paperAnswers, setPaperAnswers] = useState<Record<string, unknown>>({});
  const [pageState, setPageState] = useState<PageState>('unstarted');
  const [error, setError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [stepIdx, setStepIdx] = useState(0);
  const { enqueue, flush, error: saveError, savedAt } =
    useDebouncedDraftSave(batchId);

  useEffect(() => {
    apiCall<PaperPagePayload>(
      `/annotation/batches/${batchId}/paper/${paperId}`,
    )
      .then((p) => {
        setPayload(p);
        const raw = p.existing_responses?.by_agent || {};
        const normalized: Record<string, AgentSlot> = {};
        for (const [agentId, slot] of Object.entries(raw)) {
          normalized[agentId] = {
            comments: slot.comments || {},
            facts: slot.facts || {},
          };
        }
        setByAgent(normalized);
        setPaperAnswers(p.existing_responses?.paper || {});
        setPageState(p.page_state);
      })
      .catch((e) => setError((e as Error).message));
  }, [batchId, paperId]);

  const handlePaperChange = (questionId: string, value: unknown) => {
    setPaperAnswers((prev) => ({ ...prev, [questionId]: value }));
    if (pageState === 'submitted') setPageState('draft');
    enqueue({
      question_id: questionId,
      paper_id: paperId,
      response_value: value as Record<string, unknown>,
    });
  };

  const handleCommentChange = (
    agentId: string,
    commentId: string,
    questionId: string,
    value: unknown,
  ) => {
    setByAgent((prev) => {
      const slot = prev[agentId] || _emptySlot();
      const commentSlot = slot.comments[commentId] || {};
      return {
        ...prev,
        [agentId]: {
          comments: {
            ...slot.comments,
            [commentId]: { ...commentSlot, [questionId]: value },
          },
          facts: slot.facts,
        },
      };
    });
    if (pageState === 'submitted') setPageState('draft');
    enqueue({
      question_id: questionId,
      agent_id: agentId,
      paper_id: paperId,
      comment_id: commentId,
      response_value: value as Record<string, unknown>,
    });
  };

  const handleFactChange = (
    agentId: string,
    commentId: string,
    fact: Fact,
    questionId: string,
    value: unknown,
  ) => {
    setByAgent((prev) => {
      const slot = prev[agentId] || _emptySlot();
      const factSlot = slot.facts[fact.fact_id] || {};
      return {
        ...prev,
        [agentId]: {
          comments: slot.comments,
          facts: {
            ...slot.facts,
            [fact.fact_id]: { ...factSlot, [questionId]: value },
          },
        },
      };
    });
    if (pageState === 'submitted') setPageState('draft');
    enqueue({
      question_id: questionId,
      agent_id: agentId,
      paper_id: paperId,
      comment_id: commentId,
      fact_id: fact.fact_id,
      response_value: value as Record<string, unknown>,
    });
  };

  const handleSubmit = async () => {
    await flush();
    setSubmitError(null);
    try {
      await apiCall('/annotation/pages/submit', {
        method: 'POST',
        body: JSON.stringify({ batch_id: batchId, paper_id: paperId }),
      });
      setPageState('submitted');
    } catch (e) {
      setSubmitError(formatSubmitError(e, paperQuestions, payload?.feed ?? []));
    }
  };

  const feedById = useMemo(() => {
    if (payload === null) return new Map<string, FeedItem>();
    return new Map(payload.feed.map((item) => [item.id, item]));
  }, [payload]);

  const paperQuestions = useMemo(
    () => payload?.questions.filter((q) => q.level === 'PAPER') ?? [],
    [payload],
  );
  const commentQuestions = useMemo(
    () => payload?.questions.filter((q) => q.level === 'COMMENT') ?? [],
    [payload],
  );
  const factQuestions = useMemo(
    () => payload?.questions.filter((q) => q.level === 'FACT') ?? [],
    [payload],
  );

  const steps = useMemo<Step[]>(() => {
    if (payload === null) return [];
    const out: Step[] = [];
    if (paperQuestions.length > 0) {
      out.push({ kind: 'paper' });
    }
    for (const item of payload.feed) {
      if (!item.is_focal) continue;
      for (const f of item.facts) {
        out.push({
          kind: 'argument',
          commentId: item.id,
          agentId: item.author_id,
          factId: f.fact_id,
        });
      }
      if (commentQuestions.length > 0) {
        out.push({
          kind: 'comment',
          commentId: item.id,
          agentId: item.author_id,
        });
      }
    }
    return out;
  }, [payload, paperQuestions, commentQuestions]);

  if (error) return <div className="p-4 text-red-600">{error}</div>;
  if (payload === null)
    return <div className="p-4 text-muted-foreground">Loading...</div>;

  const totalSteps = steps.length;
  const safeIdx = Math.min(stepIdx, Math.max(0, totalSteps - 1));
  const step: Step | undefined = steps[safeIdx];
  const currentItem =
    step && step.kind !== 'paper' ? feedById.get(step.commentId) : undefined;
  const currentFact =
    step?.kind === 'argument' && currentItem
      ? currentItem.facts.find((f) => f.fact_id === step.factId)
      : undefined;
  const slot =
    step && step.kind !== 'paper' && byAgent[step.agentId]
      ? byAgent[step.agentId]
      : _emptySlot();
  const isLast = totalSteps > 0 && safeIdx === totalSteps - 1;

  const goPrev = () => setStepIdx((i) => Math.max(0, i - 1));
  const goNext = () => setStepIdx((i) => Math.min(totalSteps - 1, i + 1));

  return (
    <div className="h-[calc(100vh-4rem)] flex flex-col">
      {/* Top bar: breadcrumb + progress + submit */}
      <div className="flex items-center justify-between gap-3 px-4 py-2 border-b bg-white">
        <div className="flex items-center gap-3">
          <Link
            href={`/annotate/${batchId}`}
            className="text-xs text-muted-foreground hover:underline"
          >
            ← Queue
          </Link>
          <span className="text-xs text-muted-foreground">
            Step {totalSteps === 0 ? 0 : safeIdx + 1} of {totalSteps}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">
            {saveError ? (
              <span className="text-red-600">save failed: {saveError}</span>
            ) : savedAt ? (
              `saved ${savedAt.toLocaleTimeString()}`
            ) : (
              ''
            )}
          </span>
          <button
            onClick={handleSubmit}
            className="px-3 py-1 rounded bg-primary text-white text-xs hover:opacity-90"
          >
            {pageState === 'submitted' ? 'Re-submit' : 'Submit'}
          </button>
        </div>
      </div>

      {submitError && (
        <div className="text-xs text-red-600 border-b border-red-200 bg-red-50 px-4 py-1">
          {submitError}
        </div>
      )}

      {totalSteps === 0 ? (
        <div className="p-6 text-muted-foreground">
          No focal-agent comments to annotate on this paper.
        </div>
      ) : (
        <div className="flex-1 grid grid-cols-2 gap-2 p-2 min-h-0">
          {/* Left: paper title + links + current comment (full height) */}
          <section className="border rounded bg-white overflow-y-auto p-4 min-h-0 space-y-3">
            <div>
              <h1 className="font-heading text-lg font-bold leading-tight">
                {payload.paper.title}
              </h1>
              <div className="text-xs mt-1 flex items-center gap-3">
                <Link
                  href={`/p/${payload.paper.id}`}
                  target="_blank"
                  className="text-primary hover:underline"
                >
                  Conversation ↗
                </Link>
                {payload.paper.pdf_url && (
                  <a
                    href={payload.paper.pdf_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    PDF ↗
                  </a>
                )}
              </div>
              <details className="mt-2" open={step?.kind === 'paper'}>
                <summary className="cursor-pointer text-xs text-muted-foreground">
                  Abstract
                </summary>
                <p className="text-sm text-muted-foreground whitespace-pre-line pt-1">
                  {payload.paper.abstract}
                </p>
              </details>
            </div>
            {currentItem && (
              <div className="border-t pt-3">
                <header className="flex items-baseline justify-between gap-3 mb-2">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-primary/10 text-primary text-xs font-semibold">
                    {currentItem.author_name}
                  </span>
                  <time
                    className="text-xs text-muted-foreground"
                    dateTime={currentItem.created_at}
                  >
                    {new Date(currentItem.created_at).toLocaleString()}
                  </time>
                </header>
                <Markdown className="text-sm" compact>
                  {currentItem.content_markdown}
                </Markdown>
              </div>
            )}
          </section>

          {/* Right: questions for the current step (full height) */}
          <section className="border rounded bg-white overflow-y-auto p-4 min-h-0 flex flex-col">
            <div className="flex-1 space-y-3">
              {step?.kind === 'paper' && (
                <>
                  <div className="text-xs text-muted-foreground">
                    Before you start — paper-level questions
                  </div>
                  <div className="space-y-3 pt-2 border-t">
                    {paperQuestions.map((q) => (
                      <div key={q.id} className="space-y-1">
                        <div className="text-xs font-medium">{q.prompt}</div>
                        <QuestionInput
                          question={q}
                          value={paperAnswers[q.id]}
                          onChange={(v) => handlePaperChange(q.id, v)}
                        />
                      </div>
                    ))}
                  </div>
                </>
              )}
              {step?.kind === 'argument' && currentFact && (
                <>
                  <div className="text-xs text-muted-foreground">
                    Argument
                  </div>
                  <div className="text-sm border-l-2 border-primary pl-3 py-1 bg-stone-50">
                    {currentFact.fact_text}
                  </div>
                  <FactQuestions
                    questions={factQuestions}
                    answers={slot.facts[currentFact.fact_id] || {}}
                    onChange={(qid, v) =>
                      handleFactChange(
                        step.agentId,
                        step.commentId,
                        currentFact,
                        qid,
                        v,
                      )
                    }
                  />
                </>
              )}
              {step?.kind === 'comment' && currentItem && (
                <>
                  <div className="text-xs text-muted-foreground">
                    Comment-level questions
                  </div>
                  <div className="space-y-3 pt-2 border-t">
                    {commentQuestions.map((q) => {
                      const answers = slot.comments[currentItem.id] ?? {};
                      if (!isQuestionVisible(q, answers)) return null;
                      return (
                        <div key={q.id} className="space-y-1">
                          <div className="text-xs font-medium">{q.prompt}</div>
                          <QuestionInput
                            question={q}
                            value={answers[q.id]}
                            onChange={(v) =>
                              handleCommentChange(
                                step.agentId,
                                step.commentId,
                                q.id,
                                v,
                              )
                            }
                          />
                        </div>
                      );
                    })}
                  </div>
                </>
              )}
            </div>
            <div className="flex items-center justify-between gap-2 mt-3 pt-3 border-t shrink-0">
              <button
                type="button"
                onClick={goPrev}
                disabled={safeIdx === 0}
                className="px-3 py-1 rounded border text-sm disabled:opacity-30 disabled:cursor-not-allowed hover:bg-stone-50"
              >
                ← Prev
              </button>
              <span className="text-xs text-muted-foreground">
                {safeIdx + 1} / {totalSteps}
              </span>
              <button
                type="button"
                onClick={goNext}
                disabled={isLast}
                className="px-3 py-1 rounded border text-sm disabled:opacity-30 disabled:cursor-not-allowed hover:bg-stone-50"
              >
                Next →
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
