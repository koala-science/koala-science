import '@testing-library/jest-dom';
import { render, screen, within, fireEvent } from '@testing-library/react';
import { MasterListRow } from '../master-list/MasterListRow';
import type { StandingsEntry } from '../lib/types';

function renderRow(
  entry: StandingsEntry,
  opts?: { onSelect?: (id: string) => void; isSelected?: boolean },
) {
  return render(
    <div role="listbox">
      <MasterListRow
        entry={entry}
        onSelect={opts?.onSelect}
        isSelected={opts?.isSelected}
        gateMinVerdicts={50}
        gateMinCorr={0}
      />
    </div>,
  );
}

const baseEntry: StandingsEntry = {
  rank: null,
  agent_id: 'agent_short',
  agent_name: 'Short Agent',
  actor_type: 'delegated_agent',
  n_verdicts: 10,
  n_gt_matched: 0,
  n_out_of_gt_verdicts: 10,
  gt_corr_composite: null,
  gt_corr_avg_score: null,
  gt_corr_accepted: null,
  gt_corr_citations: null,
  peer_distance: null,
  n_peer_papers: 0,
  trust: null,
  trust_pct: null,
  activity: null,
  passed_gate: false,
  gate_reason: 'coverage 10/50, no-GT-signal',
  distance_to_clear: 1.8,
};

describe('MasterListRow', () => {
  it('renders a passer with a rank badge and emerald stripe', () => {
    renderRow({
      ...baseEntry,
      rank: 1,
      n_verdicts: 120,
      n_gt_matched: 80,
      gt_corr_composite: 0.42,
      trust_pct: 0.9,
      passed_gate: true,
      gate_reason: null,
      distance_to_clear: 0,
    });
    const row = screen.getByTestId('master-list-row');
    expect(row).toHaveAttribute('role', 'option');
    expect(row).toHaveAttribute('data-gate-kind', 'pass');
    expect(row.className).toMatch(/border-l-emerald-500/);
    expect(within(row).getByText('#1')).toBeInTheDocument();
    expect(within(row).getByText('90%')).toBeInTheDocument();
  });

  it('renders a failer with a distance pill and reason-colored stripe', () => {
    renderRow({
      ...baseEntry,
      gate_reason: 'corr=-0.12',
      distance_to_clear: 0.12,
    });
    const row = screen.getByTestId('master-list-row');
    expect(row).toHaveAttribute('data-gate-kind', 'neg_corr');
    expect(row.className).toMatch(/border-l-red-500/);
    const pill = within(row).getByTestId('distance-pill');
    expect(pill).toHaveTextContent('+0.12');
    expect(within(row).getByText('negative corr')).toBeInTheDocument();
  });

  it('classifies no-GT-signal failers as no_gt (grey stripe)', () => {
    renderRow({ ...baseEntry, gate_reason: 'coverage 10/50, no-GT-signal' });
    const row = screen.getByTestId('master-list-row');
    expect(row).toHaveAttribute('data-gate-kind', 'no_gt');
    expect(row.className).toMatch(/border-l-slate-400/);
  });

  it('truncates long agent names and carries agent_id in the title attr', () => {
    const longId = 'very-very-very-long-agent-identifier-that-should-not-expand-the-row';
    renderRow({
      ...baseEntry,
      agent_id: longId,
      agent_name: 'a'.repeat(120),
    });
    const nameSpan = screen.getByTitle(longId);
    expect(nameSpan.className).toMatch(/truncate/);
  });

  it('marks the row as selected via aria-selected', () => {
    renderRow(
      {
        ...baseEntry,
        rank: 1,
        passed_gate: true,
        trust_pct: 0.5,
        gate_reason: null,
        distance_to_clear: 0,
      },
      { isSelected: true },
    );
    const row = screen.getByTestId('master-list-row');
    expect(row).toHaveAttribute('aria-selected', 'true');
    expect(row).toHaveAttribute('data-selected', 'true');
  });

  it('dispatches selection on click', () => {
    const onSelect = jest.fn();
    renderRow(baseEntry, { onSelect });
    fireEvent.click(screen.getByTestId('master-list-row'));
    expect(onSelect).toHaveBeenCalledWith('agent_short');
  });

  it('dispatches selection on Enter keydown', () => {
    const onSelect = jest.fn();
    renderRow(baseEntry, { onSelect });
    fireEvent.keyDown(screen.getByTestId('master-list-row'), { key: 'Enter' });
    expect(onSelect).toHaveBeenCalledWith('agent_short');
  });
});
