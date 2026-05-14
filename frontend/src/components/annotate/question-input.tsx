'use client';

type ChoiceDescriptor = string | { value: string; label: string };

interface Question {
  id: string;
  level: string;
  prompt: string;
  response_type: string;
  choices_json: ChoiceDescriptor[] | null;
  order_index: number;
  parent_question_id?: string | null;
  parent_value_match?: Record<string, unknown>[] | null;
}

interface QuestionInputProps {
  question: Question;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
}

const FACT_CHOICE_LABELS: Record<string, { label: string; tooltip: string }> = {
  // verifiability
  verified: {
    label: 'Verified',
    tooltip: 'The fact is supported by the paper or prior conversation.',
  },
  false_claim: {
    label: 'False',
    tooltip: 'The fact is contradicted by the paper or prior conversation.',
  },
  verify_not_sure: {
    label: 'Not sure',
    tooltip: 'Cannot determine whether the fact is true.',
  },
  // relevance to a review
  very_relevant: { label: 'Very relevant', tooltip: 'Clearly relevant to a review of this paper.' },
  somewhat_relevant: { label: 'Somewhat relevant', tooltip: 'Partially relevant; a reviewer might raise it.' },
  not_relevant: { label: 'Not relevant', tooltip: 'Would not surface in a review.' },
  not_sure: { label: 'Not sure', tooltip: 'Unclear whether a reviewer would raise this.' },
  // confidence
  fully_confident: { label: 'Fully confident', tooltip: 'Confident in this assessment.' },
  partially_confident: { label: 'Partially confident', tooltip: 'Somewhat confident.' },
  not_confident: { label: 'Not confident', tooltip: 'Low confidence in this assessment.' },
  // polarity
  positive: { label: 'Positive', tooltip: 'The fact argues in favor of the paper.' },
  negative: { label: 'Negative', tooltip: 'The fact argues against the paper.' },
  // paper-level: understanding
  fully: { label: 'Fully', tooltip: 'I understand the paper.' },
  partially: { label: 'Partially', tooltip: 'I have a partial understanding.' },
  not_at_all: { label: 'Not at all', tooltip: 'I do not feel I understand the paper.' },
};

function _normalizeChoice(c: ChoiceDescriptor): { value: string; label: string; tooltip?: string } {
  if (typeof c === 'string') {
    const known = FACT_CHOICE_LABELS[c];
    if (known) return { value: c, label: known.label, tooltip: known.tooltip };
    return { value: c, label: c };
  }
  return c;
}

export function QuestionInput({
  question,
  value,
  onChange,
  disabled,
}: QuestionInputProps) {
  const v = value as { value?: unknown } | null;

  if (question.response_type === 'BOOLEAN') {
    const current = v?.value;
    return (
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={() => onChange({ value: true })}
          className={`px-3 py-1 rounded border text-sm ${
            current === true
              ? 'bg-emerald-100 border-emerald-400'
              : 'bg-white border-gray-300 hover:bg-gray-50'
          }`}
        >
          Yes
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() => onChange({ value: false })}
          className={`px-3 py-1 rounded border text-sm ${
            current === false
              ? 'bg-rose-100 border-rose-400'
              : 'bg-white border-gray-300 hover:bg-gray-50'
          }`}
        >
          No
        </button>
      </div>
    );
  }

  if (question.response_type === 'SINGLE_CHOICE') {
    const current = v?.value as string | undefined;
    const choices = (question.choices_json ?? []).map(_normalizeChoice);
    return (
      <div className="flex flex-wrap items-center gap-2">
        {choices.map((c) => {
          const selected = current === c.value;
          return (
            <button
              key={c.value}
              type="button"
              disabled={disabled}
              title={c.tooltip}
              onClick={() => onChange({ value: c.value })}
              className={`px-2.5 py-1 rounded border text-xs ${
                selected
                  ? 'bg-indigo-100 border-indigo-400'
                  : 'bg-white border-gray-300 hover:bg-gray-50'
              }`}
            >
              {c.label}
            </button>
          );
        })}
      </div>
    );
  }

  if (question.response_type === 'FREE_TEXT') {
    return (
      <textarea
        className="w-full border rounded p-2 text-sm"
        rows={3}
        disabled={disabled}
        value={(v?.value as string) ?? ''}
        onChange={(e) => onChange({ value: e.target.value })}
      />
    );
  }

  if (
    question.response_type === 'LIKERT_5' ||
    question.response_type === 'LIKERT_7'
  ) {
    const max = question.response_type === 'LIKERT_5' ? 5 : 7;
    const current = v?.value as number | undefined;
    return (
      <div className="flex items-center gap-1">
        {Array.from({ length: max }).map((_, i) => {
          const n = i + 1;
          const selected = current === n;
          return (
            <button
              key={n}
              type="button"
              disabled={disabled}
              onClick={() => onChange({ value: n })}
              className={`w-8 h-8 rounded border text-xs ${
                selected
                  ? 'bg-indigo-100 border-indigo-400'
                  : 'bg-white border-gray-300 hover:bg-gray-50'
              }`}
            >
              {n}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="text-xs text-muted-foreground">
      Unsupported response type: {question.response_type}
    </div>
  );
}

export type { Question };
