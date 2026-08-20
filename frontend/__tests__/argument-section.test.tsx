import '@testing-library/jest-dom';
import { fireEvent, render, screen } from '@testing-library/react';
import React from 'react';

import { ArgumentSection } from '../src/components/paper/argument-section';

const base = {
  id: 'a1',
  paper_id: 'p1',
  author_id: 'agent-1',
  author_name: 'critic-05e1',
  claim: 'The evaluation omits a no-retrieval baseline.',
  position: 'negative' as const,
  evidence: 'Section 4.1 compares retrieval variants only.',
  state: 'pending' as const,
  created_at: '2026-08-19T12:00:00Z',
  checks: [],
};

const PASSED_ALL = ['moderation', 'validity', 'relevance', 'uniqueness'].map((name) => ({
  name, version: 'v1', status: 'passed' as const, detail: 'ok',
}));

const negative = {
  ...base, id: 'neg', claim: 'A criticism.', state: 'accepted' as const, checks: PASSED_ALL,
};
const positive = {
  ...base, id: 'pos', position: 'positive' as const, claim: 'A piece of praise.',
  state: 'accepted' as const, checks: PASSED_ALL,
};
const rejected = {
  ...base,
  id: 'rej',
  state: 'rejected' as const,
  claim: 'A rejected claim.',
  checks: [{ name: 'moderation', version: 'v1', status: 'failed' as const, detail: 'low_effort' }],
};
const pending = {
  ...base,
  id: 'pend',
  claim: 'A pending claim.',
  checks: [{ name: 'moderation', version: 'v1', status: 'pending' as const, detail: null }],
};

describe('ArgumentSection', () => {
  it('opens on negative and shows only negative arguments that passed', () => {
    render(<ArgumentSection arguments={[negative, positive, rejected]} />);

    expect(screen.getByText(negative.claim)).toBeInTheDocument();
    expect(screen.queryByText(positive.claim)).not.toBeInTheDocument();
    expect(screen.queryByText(rejected.claim)).not.toBeInTheDocument();
  });

  it('switches to positive', () => {
    render(<ArgumentSection arguments={[negative, positive, rejected]} />);
    fireEvent.click(screen.getByRole('tab', { name: /positive/i }));

    expect(screen.getByText(positive.claim)).toBeInTheDocument();
    expect(screen.queryByText(negative.claim)).not.toBeInTheDocument();
  });

  it('switches to rejected', () => {
    render(<ArgumentSection arguments={[negative, positive, rejected]} />);
    fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));

    expect(screen.getByText(rejected.claim)).toBeInTheDocument();
    expect(screen.queryByText(negative.claim)).not.toBeInTheDocument();
    expect(screen.queryByText(positive.claim)).not.toBeInTheDocument();
  });

  it('a rejected argument leaves its position bucket entirely', () => {
    const rejectedPositive = { ...rejected, id: 'rp', position: 'positive' as const, claim: 'Rejected praise.' };
    render(<ArgumentSection arguments={[positive, rejectedPositive]} />);

    fireEvent.click(screen.getByRole('tab', { name: /positive/i }));
    expect(screen.getByText(positive.claim)).toBeInTheDocument();
    expect(screen.queryByText(rejectedPositive.claim)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));
    expect(screen.getByText(rejectedPositive.claim)).toBeInTheDocument();
  });

  it('an argument still being checked is not in a position tab', () => {
    render(<ArgumentSection arguments={[pending]} />);

    expect(screen.queryByText(pending.claim)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /pending/i }));
    expect(screen.getByText(pending.claim)).toBeInTheDocument();
    expect(screen.getByLabelText('moderation: checking')).toBeInTheDocument();
  });

  it('a pending positive argument waits in Pending, not Positive', () => {
    const pendingPraise = {
      ...pending, id: 'pp', position: 'positive' as const, claim: 'Unchecked praise.',
    };
    render(<ArgumentSection arguments={[positive, pendingPraise]} />);

    fireEvent.click(screen.getByRole('tab', { name: /positive/i }));
    expect(screen.getByText(positive.claim)).toBeInTheDocument();
    expect(screen.queryByText(pendingPraise.claim)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /pending/i }));
    expect(screen.getByText(pendingPraise.claim)).toBeInTheDocument();
  });

  it('only fully-checked arguments make the position tabs', () => {
    const halfway = {
      ...base, id: 'half', claim: 'Cleared two of four.',
      checks: [
        { name: 'moderation', version: 'v1', status: 'passed' as const, detail: 'ok' },
        { name: 'validity', version: 'v1', status: 'passed' as const, detail: 'ok' },
      ],
    };
    render(<ArgumentSection arguments={[negative, halfway]} />);

    expect(screen.getByText(negative.claim)).toBeInTheDocument();
    expect(screen.queryByText(halfway.claim)).not.toBeInTheDocument();
  });

  it('counts each bucket in its tab', () => {
    render(<ArgumentSection arguments={[negative, positive, rejected, pending]} />);

    expect(screen.getByRole('tab', { name: /negative/i })).toHaveTextContent('1');
    expect(screen.getByRole('tab', { name: /positive/i })).toHaveTextContent('1');
    expect(screen.getByRole('tab', { name: /pending/i })).toHaveTextContent('1');
    expect(screen.getByRole('tab', { name: /rejected/i })).toHaveTextContent('1');
  });

  it('shows why a rejected argument failed, once opened', () => {
    render(<ArgumentSection arguments={[rejected]} />);
    fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));

    expect(screen.queryByText(/low_effort/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: new RegExp(rejected.claim, 'i') }));
    expect(screen.getByText(/low_effort/)).toBeInTheDocument();
  });

  it('shows only the claim until the argument is opened', () => {
    render(<ArgumentSection arguments={[negative]} />);

    expect(screen.getByText(negative.claim)).toBeInTheDocument();
    expect(screen.queryByText(negative.evidence)).not.toBeInTheDocument();
    expect(screen.queryByText(negative.author_name)).not.toBeInTheDocument();
  });

  it('reveals the evidence when clicked, and hides it again', () => {
    render(<ArgumentSection arguments={[negative]} />);
    const toggle = screen.getByRole('button', { name: new RegExp(negative.claim, 'i') });

    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(negative.evidence)).toBeInTheDocument();
    expect(screen.getByText(negative.author_name)).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText(negative.evidence)).not.toBeInTheDocument();
  });

  it('opens each argument independently', () => {
    const other = { ...negative, id: 'other', claim: 'Another criticism.', evidence: 'Other evidence.' };
    render(<ArgumentSection arguments={[negative, other]} />);

    fireEvent.click(screen.getByRole('button', { name: new RegExp(negative.claim, 'i') }));
    expect(screen.getByText(negative.evidence)).toBeInTheDocument();
    expect(screen.queryByText(other.evidence)).not.toBeInTheDocument();
  });

  it('tells you an empty bucket is empty, not that the paper has nothing', () => {
    render(<ArgumentSection arguments={[negative]} />);
    fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));
    expect(screen.getByText(/no rejected arguments/i)).toBeInTheDocument();
  });

  it('renders an empty state when a paper has no arguments at all', () => {
    render(<ArgumentSection arguments={[]} />);
    expect(screen.getByText(/no arguments yet/i)).toBeInTheDocument();
  });

  describe('the check pipeline', () => {
    const PIPELINE = ['moderation', 'validity', 'relevance', 'uniqueness'];

    it('shows every stage even when only the first has a row', () => {
      render(<ArgumentSection arguments={[pending]} />);
      fireEvent.click(screen.getByRole('tab', { name: /pending/i }));

      expect(screen.getByLabelText('moderation: checking')).toBeInTheDocument();
      for (const name of ['validity', 'relevance', 'uniqueness']) {
        expect(screen.getByLabelText(`${name}: not run`)).toBeInTheDocument();
      }
    });

    it('renders the whole pipeline on the collapsed row', () => {
      render(<ArgumentSection arguments={[pending]} />);
      fireEvent.click(screen.getByRole('tab', { name: /pending/i }));

      const rail = screen.getByRole('list', { name: /check pipeline/i });
      expect(rail).toBeInTheDocument();
      expect(screen.getAllByRole('listitem')).toHaveLength(PIPELINE.length);
    });

    it('marks the stages an argument cleared, and the one it failed', () => {
      const failedLate = {
        ...base,
        id: 'late',
        state: 'rejected' as const,
        claim: 'Failed at relevance.',
        checks: [
          { name: 'moderation', version: 'v1', status: 'passed' as const, detail: 'ok' },
          { name: 'validity', version: 'v1', status: 'passed' as const, detail: 'ok' },
          { name: 'relevance', version: 'v1', status: 'failed' as const, detail: 'cosmetic: a typo' },
        ],
      };
      render(<ArgumentSection arguments={[failedLate]} />);
      fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));

      expect(screen.getByLabelText('moderation: passed')).toBeInTheDocument();
      expect(screen.getByLabelText('validity: passed')).toBeInTheDocument();
      expect(screen.getByLabelText('relevance: failed')).toBeInTheDocument();
      // never queued, because the sequence stops at the first failure
      expect(screen.getByLabelText('uniqueness: not run')).toBeInTheDocument();
    });

    it('an accepted argument shows a check for every stage', () => {
      const accepted = {
        ...base,
        id: 'acc',
        state: 'accepted' as const,
        claim: 'Cleared everything.',
        checks: PIPELINE.map((name) => ({
          name, version: 'v1', status: 'passed' as const, detail: 'ok',
        })),
      };
      render(<ArgumentSection arguments={[accepted]} />);

      for (const name of PIPELINE) {
        expect(screen.getByLabelText(`${name}: passed`)).toBeInTheDocument();
      }
    });

    it('keeps the failure reason out of the collapsed row', () => {
      render(<ArgumentSection arguments={[rejected]} />);
      fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));

      expect(screen.getByLabelText('moderation: failed')).toBeInTheDocument();
      expect(screen.queryByText(/low_effort/)).not.toBeInTheDocument();
    });

    it('takes the newest version when a check was re-run', () => {
      const rechecked = {
        ...base,
        id: 're',
        state: 'accepted' as const,
        claim: 'Re-run at v2.',
        checks: [
          { name: 'moderation', version: 'v1', status: 'failed' as const, detail: 'low_effort' },
          { name: 'moderation', version: 'v2', status: 'passed' as const, detail: 'ok' },
        ],
      };
      render(<ArgumentSection arguments={[rechecked]} />);

      expect(screen.getByLabelText('moderation: passed')).toBeInTheDocument();
      expect(screen.queryByLabelText('moderation: failed')).not.toBeInTheDocument();
    });
  });

  it('keeps the rail out of the toggle\'s accessible name', () => {
    // A <button> has presentational children, so a rail inside it would both
    // lose its own labels and append "Check pipeline" to every toggle.
    render(<ArgumentSection arguments={[negative]} />);

    const toggle = screen.getByRole('button', { name: negative.claim });
    expect(toggle).toBeInTheDocument();
    expect(toggle).not.toHaveTextContent('Check pipeline');
  });
});
