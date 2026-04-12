import '@testing-library/jest-dom';
import { fireEvent, render, screen } from '@testing-library/react';
import { GateScatter } from '../gate-strip/GateScatter';
import type { StandingsEntry, StandingsResponse } from '../lib/types';

function mkEntry(overrides: Partial<StandingsEntry>): StandingsEntry {
  return {
    rank: null,
    agent_id: 'a',
    agent_name: 'A',
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
    ...overrides,
  };
}

function mkResponse(entries: StandingsEntry[]): StandingsResponse {
  return {
    gate_min_verdicts: 50,
    gate_min_corr: 0,
    n_papers: 100,
    n_verdicts: entries.reduce((a, e) => a + e.n_verdicts, 0),
    n_gt_matched_papers: 0,
    n_passers: entries.filter(e => e.passed_gate).length,
    n_failers: entries.filter(e => !e.passed_gate).length,
    entries,
  };
}

describe('GateScatter', () => {
  const entries = [
    mkEntry({ agent_id: 'p1', n_verdicts: 100, gt_corr_composite: 0.4, passed_gate: true, gate_reason: null, distance_to_clear: 0 }),
    mkEntry({ agent_id: 'f1', n_verdicts: 60, gt_corr_composite: -0.2, gate_reason: 'corr=-0.20', distance_to_clear: 0.2 }),
    mkEntry({ agent_id: 'f2', n_verdicts: 5, gt_corr_composite: null }),
    mkEntry({ agent_id: 'f3', n_verdicts: 70, gt_corr_composite: null }),
  ];
  const data = mkResponse(entries);

  it('renders one circle per entry', () => {
    render(<GateScatter data={data} selectedAgentId={null} onSelect={() => {}} />);
    const dots = screen.getAllByTestId('scatter-dot');
    expect(dots).toHaveLength(entries.length);
  });

  it('renders the pass region polygon', () => {
    render(<GateScatter data={data} selectedAgentId={null} onSelect={() => {}} />);
    expect(screen.getByTestId('pass-region')).toBeInTheDocument();
  });

  it('flags null-corr entries with the "not measured" stripe fill', () => {
    render(<GateScatter data={data} selectedAgentId={null} onSelect={() => {}} />);
    const nullDots = screen
      .getAllByTestId('scatter-dot')
      .filter(d => d.getAttribute('data-corr-null') === 'true');
    expect(nullDots).toHaveLength(2);
    nullDots.forEach(d => {
      expect(d.getAttribute('fill')).toBe('url(#gate-scatter-null-stripe)');
    });
  });

  it('has an aria-label describing the view', () => {
    render(<GateScatter data={data} selectedAgentId={null} onSelect={() => {}} />);
    const svg = screen.getByRole('img');
    const label = svg.getAttribute('aria-label') ?? '';
    expect(label).toMatch(/Scatter of 4 agents/);
    expect(label).toMatch(/verdicts >= 50/);
  });

  it('calls onSelect with the agent id when a dot is clicked', () => {
    const onSelect = jest.fn();
    render(<GateScatter data={data} selectedAgentId={null} onSelect={onSelect} />);
    const dots = screen.getAllByTestId('scatter-dot');
    fireEvent.click(dots[0]);
    expect(onSelect).toHaveBeenCalledWith('p1');
  });

  it('visually emphasizes the selected dot', () => {
    render(<GateScatter data={data} selectedAgentId="f1" onSelect={() => {}} />);
    const selected = screen
      .getAllByTestId('scatter-dot')
      .find(d => d.getAttribute('data-agent-id') === 'f1');
    expect(selected).toBeDefined();
    expect(selected?.getAttribute('r')).toBe('6');
  });
});
