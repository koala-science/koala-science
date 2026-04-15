import '@testing-library/jest-dom';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';

import LeaderboardPage from '../src/app/leaderboard/page';

const push = jest.fn();

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}));

describe('LeaderboardPage', () => {
  beforeEach(() => {
    push.mockReset();
    global.fetch = jest.fn(() =>
      Promise.resolve({
        ok: true,
        json: async () => ({
          metric: 'acceptance',
          total: 1,
          entries: [
            {
              rank: 1,
              agent_id: 'agent-1',
              agent_name: 'TestAgent',
              agent_type: 'delegated_agent',
              owner_name: 'Owner',
              score: 0.42,
              num_papers_evaluated: 10,
            },
          ],
        }),
      }),
    ) as jest.Mock;
  });

  it('renders all metric tabs without requiring a password', async () => {
    render(<LeaderboardPage searchParams={{}} />);

    await waitFor(() => {
      expect(screen.getByText('TestAgent')).toBeInTheDocument();
    });

    expect(screen.getByRole('button', { name: 'Acceptance' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Citation' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Interactions' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Papers' })).toBeInTheDocument();
  });

  it('fetches acceptance metric by default', async () => {
    render(<LeaderboardPage searchParams={{}} />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/v1/leaderboard/agents?metric=acceptance&limit=20&skip=0'
      );
    });
  });
});
