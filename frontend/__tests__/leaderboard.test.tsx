import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';

import LeaderboardPage from '../src/app/leaderboard/page';
import { useAuthStore } from '../src/lib/store';

const push = jest.fn();
const originalSessionStorage = Object.getOwnPropertyDescriptor(window, 'sessionStorage');
const originalLocalStorage = Object.getOwnPropertyDescriptor(window, 'localStorage');

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}));

describe('LeaderboardPage', () => {
  beforeEach(() => {
    push.mockReset();
    window.sessionStorage.clear();
    global.fetch = jest.fn((input: string | URL | Request) => {
      const url = String(input);
      const payload = url.includes('metric=acceptance')
        ? {
            metric: 'acceptance',
            total: 1,
            entries: [
              {
                rank: 1,
                agent_id: 'agent-protected',
                agent_name: 'ProtectedAgent',
                agent_type: 'delegated_agent',
                owner_name: 'Owner',
                score: 0.99,
                num_papers_evaluated: 6,
              },
            ],
          }
        : {
            metric: 'interactions',
            total: 1,
            entries: [
              {
                rank: 1,
                agent_id: 'agent-public',
                agent_name: 'PublicAgent',
                agent_type: 'delegated_agent',
                owner_name: 'Owner',
                score: 12,
                num_papers_evaluated: 3,
              },
            ],
          };

      return Promise.resolve({
        ok: true,
        json: async () => payload,
      });
    }) as jest.Mock;
  });

  afterEach(() => {
    if (originalSessionStorage) {
      Object.defineProperty(window, 'sessionStorage', originalSessionStorage);
    }
    if (originalLocalStorage) {
      Object.defineProperty(window, 'localStorage', originalLocalStorage);
    }
    useAuthStore.setState({
      isAuthenticated: false,
      hydrated: false,
      user: null,
      accessToken: null,
    });
  });

  it('keeps verdict-based rankings locked until a password is entered', async () => {
    render(<LeaderboardPage searchParams={{ metric: 'acceptance' }} />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/v1/leaderboard/agents?metric=interactions&limit=20&skip=0'
      );
      expect(screen.getByText('PublicAgent')).toBeInTheDocument();
    });

    expect(screen.queryByText('Acceptance')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Papers' })).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('Enter leaderboard password'), {
      target: { value: 'Mont-Saint-Hilaire' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Unlock' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Acceptance' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Papers' })).toBeInTheDocument();
      expect(global.fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/v1/leaderboard/agents?metric=acceptance&limit=20&skip=0&password=Mont-Saint-Hilaire'
      );
      expect(screen.getByText('ProtectedAgent')).toBeInTheDocument();
    });
  });

  it('renders without crashing when browser storage access is blocked', async () => {
    const blockedStorage = {
      getItem: () => { throw new Error('storage blocked'); },
      setItem: () => { throw new Error('storage blocked'); },
      removeItem: () => { throw new Error('storage blocked'); },
      clear: () => undefined,
      key: () => null,
      length: 0,
    };

    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      value: blockedStorage,
    });
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: blockedStorage,
    });

    await act(async () => {
      useAuthStore.getState().restore();
      render(<LeaderboardPage searchParams={{}} />);
    });

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/v1/leaderboard/agents?metric=interactions&limit=20&skip=0'
      );
      expect(screen.getByText('PublicAgent')).toBeInTheDocument();
    });
  });
});
