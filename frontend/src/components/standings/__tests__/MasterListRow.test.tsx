import '@testing-library/jest-dom';
import { render, screen, within } from '@testing-library/react';
import { MasterListRow } from '../master-list/MasterListRow';
import type { StandingsEntry } from '../lib/types';

// MasterListRow is a <tr>, so rendering requires a table wrapper.
function renderRow(entry: StandingsEntry) {
  return render(
    <table>
      <tbody>
        <MasterListRow entry={entry} />
      </tbody>
    </table>,
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
    });
    const row = screen.getByTestId('master-list-row');
    expect(row).toHaveAttribute('data-gate-kind', 'pass');
    expect(row.className).toMatch(/border-l-emerald-500/);
    expect(within(row).getByText('#1')).toBeInTheDocument();
    expect(within(row).getByText('past gate')).toBeInTheDocument();
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

  it('all numeric cells carry whitespace-nowrap', () => {
    renderRow({
      ...baseEntry,
      n_verdicts: 12345,
      n_gt_matched: 678,
      gt_corr_composite: 0.25,
      peer_distance: 1.23,
      trust_pct: 0.55,
    });
    const row = screen.getByTestId('master-list-row');
    const numericCells = row.querySelectorAll('td.tabular-nums');
    expect(numericCells.length).toBeGreaterThanOrEqual(5);
    numericCells.forEach(td => {
      expect(td.className).toMatch(/whitespace-nowrap/);
    });
  });

  it('splits verdicts and GT-matched into separate columns', () => {
    renderRow({
      ...baseEntry,
      n_verdicts: 104,
      n_gt_matched: 0,
    });
    const row = screen.getByTestId('master-list-row');
    // We should find "104" and "0" as distinct cells, not the legacy "104 (0 GT)".
    expect(within(row).queryByText(/104\s*\(0\s*GT\)/)).toBeNull();
    expect(within(row).getByText('104')).toBeInTheDocument();
    expect(within(row).getByText('0')).toBeInTheDocument();
  });
});
