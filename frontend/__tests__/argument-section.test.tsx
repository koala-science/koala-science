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

const negative = { ...base, id: 'neg', claim: 'A criticism.' };
const positive = { ...base, id: 'pos', position: 'positive' as const, claim: 'A piece of praise.' };
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

  it('a pending argument stays in its position bucket', () => {
    render(<ArgumentSection arguments={[pending]} />);
    expect(screen.getByText(pending.claim)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: new RegExp(pending.claim, 'i') }));
    expect(screen.getByText(/checking/i)).toBeInTheDocument();
  });

  it('counts each bucket in its tab', () => {
    render(<ArgumentSection arguments={[negative, positive, rejected, pending]} />);

    expect(screen.getByRole('tab', { name: /negative/i })).toHaveTextContent('2');
    expect(screen.getByRole('tab', { name: /positive/i })).toHaveTextContent('1');
    expect(screen.getByRole('tab', { name: /rejected/i })).toHaveTextContent('1');
  });

  it('shows why a rejected argument failed, once opened', () => {
    render(<ArgumentSection arguments={[rejected]} />);
    fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));

    expect(screen.queryByText(/low_effort/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: new RegExp(rejected.claim, 'i') }));
    expect(screen.getByText(/failed the moderation check/i)).toBeInTheDocument();
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
});
