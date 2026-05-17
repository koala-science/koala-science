import { ApiError } from '@/lib/api';
import { type Question } from '@/components/annotate/question-input';

interface FactRef {
  fact_id: string;
}
interface FeedItemRef {
  author_name: string;
  facts: FactRef[];
}

function asStringArray(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
}

export function formatSubmitError(
  e: unknown,
  paperQuestions: Question[],
  feed: FeedItemRef[],
): string {
  if (!(e instanceof ApiError) || typeof e.detail !== 'object' || e.detail === null) {
    return e instanceof Error ? e.message : 'Submit failed';
  }
  const detail = e.detail as Record<string, unknown>;
  const code = detail.error;

  if (code === 'paper_responses_incomplete') {
    const missing = asStringArray(detail.missing_question_ids);
    if (missing.length === 0) {
      return 'Paper-level questions are incomplete.';
    }
    const promptByQid = new Map(paperQuestions.map((q) => [q.id, q.prompt]));
    const labels = missing.map((qid) => promptByQid.get(qid) ?? qid);
    return `Paper-level questions still need answers: ${labels.join('; ')}`;
  }

  if (code === 'fact_responses_incomplete') {
    const missing = asStringArray(detail.missing_fact_ids);
    const factLoc = new Map<string, { author: string; argIndex: number }>();
    for (const item of feed) {
      item.facts.forEach((f, i) => {
        factLoc.set(f.fact_id, { author: item.author_name, argIndex: i + 1 });
      });
    }
    const byAuthor = new Map<string, number[]>();
    let unresolved = 0;
    for (const fid of missing) {
      const loc = factLoc.get(fid);
      if (loc === undefined) {
        unresolved += 1;
        continue;
      }
      const arr = byAuthor.get(loc.author) ?? [];
      arr.push(loc.argIndex);
      byAuthor.set(loc.author, arr);
    }
    if (byAuthor.size === 0) {
      const n = missing.length;
      return n === 0
        ? 'Argument-level questions are incomplete.'
        : `${n} argument question${n === 1 ? '' : 's'} still unanswered (refresh the page if you don't see them).`;
    }
    const parts = Array.from(byAuthor.entries()).map(
      ([author, idxs]) =>
        `${author} (argument${idxs.length === 1 ? '' : 's'} ${idxs.sort((a, b) => a - b).join(', ')})`,
    );
    let msg = `Unanswered argument questions for: ${parts.join('; ')}.`;
    if (unresolved > 0) {
      msg += ` +${unresolved} more on argument${unresolved === 1 ? '' : 's'} not shown on this page (refresh).`;
    }
    return msg;
  }

  return e.message;
}
