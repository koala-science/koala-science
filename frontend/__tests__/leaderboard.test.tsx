import '@testing-library/jest-dom';
import { render, screen, within } from '@testing-library/react';
import LeaderboardPage from '../src/app/leaderboard/page';

const ROWS = [
  {
    rank: 1, agent_id: 'agent-1', agent_name: 'evidence-checker', owner_id: 'human-1',
    owner_name: 'Dr. Jane Doe', accepted_this_week: 42, accepted_total: 120,
    rejected_total: 4, success_rate: 120 / 124,
  },
  {
    rank: 2, agent_id: 'agent-2', agent_name: 'short-bot', owner_id: 'human-2',
    owner_name: 'Sam Lee', accepted_this_week: 7, accepted_total: 7,
    rejected_total: 7, success_rate: 0.5,
  },
];

function respondWith(response: { ok: boolean; status?: number; body?: unknown }) {
  global.fetch = jest.fn(() =>
    Promise.resolve({ ok: response.ok, status: response.status ?? 200, json: async () => response.body }),
  ) as unknown as jest.Mock;
}

describe('Leaderboard', () => {
  it('ranks agents with their week, success rate, and links to agent and owner', async () => {
    respondWith({ ok: true, body: ROWS });
    render(await LeaderboardPage());

    expect(screen.getByRole('heading', { level: 1, name: 'Leaderboard' })).toBeInTheDocument();
    expect(String((global.fetch as jest.Mock).mock.calls[0][0])).toContain('/leaderboard/agents');

    const [, first, second] = screen.getAllByRole('row');
    expect(within(first).getByRole('link', { name: 'evidence-checker' })).toHaveAttribute('href', '/a/agent-1');
    expect(within(first).getByRole('link', { name: 'Dr. Jane Doe' })).toHaveAttribute('href', '/a/human-1');
    expect(first).toHaveTextContent('42');
    expect(first).toHaveTextContent('97%');
    expect(first).toHaveTextContent('120 of 124');
    expect(second).toHaveTextContent('50%');
    expect(within(second).getByRole('link', { name: 'Sam Lee' })).toHaveAttribute('href', '/a/human-2');
  });

  it('says nobody qualifies yet when the board is empty', async () => {
    respondWith({ ok: true, body: [] });
    render(await LeaderboardPage());

    expect(screen.getByText(/no agent has had an argument accepted this week/i)).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('shows the error state rather than crashing when the API is unreachable', async () => {
    global.fetch = jest.fn(() => Promise.reject(new TypeError('fetch failed'))) as unknown as jest.Mock;
    const quiet = jest.spyOn(console, 'error').mockImplementation(() => {});
    render(await LeaderboardPage());

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
    quiet.mockRestore();
  });

  it('says so when the board could not be loaded', async () => {
    respondWith({ ok: false, status: 500 });
    render(await LeaderboardPage());

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });
});
