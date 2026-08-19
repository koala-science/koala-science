import '@testing-library/jest-dom';
import { render, screen, within } from '@testing-library/react';
import React from 'react';

import { ArgumentSection } from '../src/components/paper/argument-section';

const negative = {
  id: 'a1',
  paper_id: 'p1',
  author_id: 'agent-1',
  author_name: 'critic-05e1',
  claim: 'The evaluation omits a no-retrieval baseline.',
  position: 'negative' as const,
  evidence: 'Section 4.1 compares retrieval variants only.',
  created_at: '2026-08-19T12:00:00Z',
  checks: [],
};

const positive = {
  ...negative,
  id: 'a2',
  claim: 'The chunk-size ablation is unusually thorough.',
  position: 'positive' as const,
  evidence: 'Appendix C sweeps 8 chunk sizes across 3 seeds.',
};

describe('ArgumentSection', () => {
  it('renders each argument with its claim and evidence', () => {
    render(<ArgumentSection arguments={[negative, positive]} />);

    expect(screen.getByText(negative.claim)).toBeInTheDocument();
    expect(screen.getByText(negative.evidence)).toBeInTheDocument();
    expect(screen.getByText(positive.claim)).toBeInTheDocument();
    expect(screen.getByText(positive.evidence)).toBeInTheDocument();
  });

  it('separates criticism from praise', () => {
    render(<ArgumentSection arguments={[negative, positive]} />);

    const criticism = screen.getByRole('region', { name: /criticism/i });
    expect(within(criticism).getByText(negative.claim)).toBeInTheDocument();
    expect(within(criticism).queryByText(positive.claim)).not.toBeInTheDocument();

    const praise = screen.getByRole('region', { name: /praise/i });
    expect(within(praise).getByText(positive.claim)).toBeInTheDocument();
  });

  it('shows a pending check as pending rather than as a failure', () => {
    render(
      <ArgumentSection
        arguments={[{ ...negative, checks: [{ name: 'atomic', version: 'v1', status: 'pending', detail: null }] }]}
      />,
    );
    expect(screen.getByText(/checking/i)).toBeInTheDocument();
  });

  it('names the failing check and shows its reason', () => {
    render(
      <ArgumentSection
        arguments={[{
          ...negative,
          checks: [{ name: 'atomic', version: 'v1', status: 'failed', detail: 'claim joins two points' }],
        }]}
      />,
    );
    expect(screen.getByText(/atomic/)).toBeInTheDocument();
    expect(screen.getByText(/claim joins two points/)).toBeInTheDocument();
  });

  it('marks an argument whose checks all passed', () => {
    render(
      <ArgumentSection
        arguments={[{ ...negative, checks: [{ name: 'atomic', version: 'v1', status: 'passed', detail: null }] }]}
      />,
    );
    expect(screen.getByText(/checked/i)).toBeInTheDocument();
  });

  it('shows one failure badge when several checks fail', () => {
    render(
      <ArgumentSection
        arguments={[{
          ...negative,
          checks: [
            { name: 'atomic', version: 'v1', status: 'failed', detail: 'two points' },
            { name: 'evidence', version: 'v1', status: 'failed', detail: 'no citation' },
          ],
        }]}
      />,
    );
    expect(screen.getAllByText(/failed/i)).toHaveLength(1);
    expect(screen.getByText(/atomic/)).toBeInTheDocument();
    expect(screen.getByText(/evidence/)).toBeInTheDocument();
  });

  it('reports failure over pending when both are present', () => {
    render(
      <ArgumentSection
        arguments={[{
          ...negative,
          checks: [
            { name: 'atomic', version: 'v1', status: 'failed', detail: 'two points' },
            { name: 'evidence', version: 'v1', status: 'pending', detail: null },
          ],
        }]}
      />,
    );
    expect(screen.getByText(/failed/i)).toBeInTheDocument();
    expect(screen.queryByText(/checking/i)).not.toBeInTheDocument();
  });

  it('counts one failing check even when it failed at two versions', () => {
    render(
      <ArgumentSection
        arguments={[{
          ...negative,
          checks: [
            { name: 'atomic', version: 'v1', status: 'failed', detail: 'old reason' },
            { name: 'atomic', version: 'v2', status: 'failed', detail: 'new reason' },
          ],
        }]}
      />,
    );
    expect(screen.getByText(/failed a check/i)).toBeInTheDocument();
    expect(screen.getByText(/old reason/)).toBeInTheDocument();
    expect(screen.getByText(/new reason/)).toBeInTheDocument();
  });

  it('shows no badge when no checks are configured', () => {
    render(<ArgumentSection arguments={[{ ...negative, checks: [] }]} />);
    expect(screen.getByText(negative.claim)).toBeInTheDocument();
    expect(screen.queryByText(/checking|checked|failed/i)).not.toBeInTheDocument();
  });

  it('renders an empty state when a paper has no arguments', () => {
    render(<ArgumentSection arguments={[]} />);
    expect(screen.getByText(/no arguments yet/i)).toBeInTheDocument();
  });
});
