import { ApiError } from '../../src/lib/api';
import { formatSubmitError } from '../../src/app/annotate/[batchId]/paper/[paperId]/submit-error';

const Q = (id: string, prompt: string) =>
  ({ id, prompt, level: 'PAPER', response_type: 'BOOLEAN', choices_json: null, order_index: 0 } as never);

const feed = [
  {
    author_name: 'reviewer-2',
    facts: [{ fact_id: 'f1' }, { fact_id: 'f2' }, { fact_id: 'f3' }],
  },
  {
    author_name: 'claude_shannon',
    facts: [{ fact_id: 'f4' }, { fact_id: 'f5' }],
  },
];

describe('formatSubmitError', () => {
  it('falls back to message for non-ApiError input', () => {
    expect(formatSubmitError(new Error('boom'), [], [])).toBe('boom');
    expect(formatSubmitError('nope', [], [])).toBe('Submit failed');
  });

  it('uses ApiError.message when detail is not structured', () => {
    const e = new ApiError('Forbidden', 403, 'forbidden');
    expect(formatSubmitError(e, [], [])).toBe('Forbidden');
  });

  it('lists prompts for missing paper-level questions', () => {
    const e = new ApiError('x', 422, {
      error: 'paper_responses_incomplete',
      missing_question_ids: ['qa', 'qb'],
    });
    const out = formatSubmitError(e, [Q('qa', 'Did you read it?'), Q('qb', 'Confidence?')], []);
    expect(out).toBe('Paper-level questions still need answers: Did you read it?; Confidence?');
  });

  it('falls back to qid when paper prompt is unknown', () => {
    const e = new ApiError('x', 422, {
      error: 'paper_responses_incomplete',
      missing_question_ids: ['qa'],
    });
    expect(formatSubmitError(e, [], [])).toContain('qa');
  });

  it('handles empty paper missing_question_ids', () => {
    const e = new ApiError('x', 422, {
      error: 'paper_responses_incomplete',
      missing_question_ids: [],
    });
    expect(formatSubmitError(e, [], [])).toBe('Paper-level questions are incomplete.');
  });

  it('groups missing facts by author and uses singular grammar for one arg', () => {
    const e = new ApiError('x', 422, {
      error: 'fact_responses_incomplete',
      missing_fact_ids: ['f4'],
    });
    expect(formatSubmitError(e, [], feed)).toBe(
      'Unanswered argument questions for: claude_shannon (argument 1).',
    );
  });

  it('groups missing facts by author and uses plural for many', () => {
    const e = new ApiError('x', 422, {
      error: 'fact_responses_incomplete',
      missing_fact_ids: ['f3', 'f1', 'f5'],
    });
    expect(formatSubmitError(e, [], feed)).toBe(
      'Unanswered argument questions for: reviewer-2 (arguments 1, 3); claude_shannon (argument 2).',
    );
  });

  it('reports unresolved fact-ids when the feed is stale', () => {
    const e = new ApiError('x', 422, {
      error: 'fact_responses_incomplete',
      missing_fact_ids: ['f1', 'unknown-1', 'unknown-2'],
    });
    const out = formatSubmitError(e, [], feed);
    expect(out).toContain('reviewer-2 (argument 1)');
    expect(out).toContain('+2 more on arguments not shown on this page (refresh)');
  });

  it('handles all-unresolved fact-ids (totally stale feed)', () => {
    const e = new ApiError('x', 422, {
      error: 'fact_responses_incomplete',
      missing_fact_ids: ['u1', 'u2'],
    });
    expect(formatSubmitError(e, [], feed)).toBe(
      "2 argument questions still unanswered (refresh the page if you don't see them).",
    );
  });

  it('rejects non-string array elements', () => {
    const e = new ApiError('x', 422, {
      error: 'paper_responses_incomplete',
      missing_question_ids: [123, null, 'qa'],
    });
    const out = formatSubmitError(e, [Q('qa', 'Q')], []);
    expect(out).toBe('Paper-level questions still need answers: Q');
  });

  it('falls back to e.message for unrecognized error codes', () => {
    const e = new ApiError('Boom', 422, { error: 'something_else' });
    expect(formatSubmitError(e, [], feed)).toBe('Boom');
  });
});
