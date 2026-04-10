import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import Dashboard from '../src/app/dashboard/page';
import React from 'react';

global.fetch = jest.fn();

describe('Dashboard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders correctly with required data-agent-action tags and ARIA labels', async () => {
    const mockUser = {
      name: 'Dr. Jane Doe',
      auth_method: 'Email',
      reputation_score: 120,
      voting_weight: 1.5,
      delegated_agents: [
        {
          id: 'agent-123',
          name: 'ResearchBot 9000',
          status: 'Active',
          api_key_preview: 'sk-...abcd',
          reputation: 45
        }
      ]
    };

    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockUser
    });

    const jsx = await Dashboard();
    render(jsx);

    // ARIA roles and labels
    expect(screen.getByRole('main')).toHaveAttribute('aria-label', 'Identity and Reputation Dashboard');
    
    // Check elements have the required agent-action tags
    expect(screen.getByText('+ Register Agent')).toHaveAttribute('data-agent-action', 'register-agent');
    
    // Kill-switch action
    const killSwitch = screen.getByText('Kill Switch (Revoke)');
    expect(killSwitch).toHaveAttribute('data-agent-action', 'kill-switch');
    expect(killSwitch).toHaveAttribute('data-agent-id', 'agent-123');
  });
});
