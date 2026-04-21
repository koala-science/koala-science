import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import Dashboard from '../src/app/dashboard/page';
import { useAuthStore, useProfileStore, useNotificationStore } from '../src/lib/store';
import React from 'react';

// Dashboard's useEffect calls fetchProfile which replaces the seeded store
// state, so the fetch mock must return the same shape the test asserts on.
const MOCK_PROFILE = {
  name: 'Dr. Jane Doe',
  auth_method: 'Email',
  agents: [
    {
      id: 'agent-123',
      name: 'ResearchBot 9000',
      status: 'Active',
      karma: 45,
    },
  ],
};

global.fetch = jest.fn((url: RequestInfo | URL) => {
  const u = String(url);
  if (u.includes('/notifications')) {
    return Promise.resolve({
      ok: true,
      json: async () => ({ notifications: [], unread_count: 0, total: 0 }),
    }) as any;
  }
  return Promise.resolve({ ok: true, json: async () => MOCK_PROFILE }) as any;
}) as unknown as jest.Mock;

describe('Dashboard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAuthStore.setState({
      isAuthenticated: true,
      hydrated: true,
      user: { id: 'user-1', name: 'Dr. Jane Doe', email: 'jane@example.com' },
      token: 'test-token',
    });
    useNotificationStore.setState({
      notifications: [],
      unreadCount: 0,
      loading: false,
      fetchUnreadCount: async () => {},
      fetchNotifications: async () => {},
    } as any);
    useProfileStore.setState({
      loading: false,
      profile: {
        name: 'Dr. Jane Doe',
        auth_method: 'Email',
        agents: [
          {
            id: 'agent-123',
            name: 'ResearchBot 9000',
            status: 'Active',
            karma: 45,
          },
        ],
      } as any,
      // No-op so the mounted useEffect doesn't flip loading and clobber the seeded profile.
      fetchProfile: async () => {},
    });
  });

  it('renders agent list without a kill-switch button', () => {
    render(<Dashboard />);

    expect(screen.getByRole('main')).toHaveAttribute('aria-label', 'Identity and Reputation Dashboard');
    expect(screen.getByText('+ Register Agent')).toHaveAttribute('data-agent-action', 'register-agent');
    expect(screen.getByText('ResearchBot 9000')).toBeInTheDocument();
    expect(screen.queryByText('Kill Switch (Revoke)')).toBeNull();
    expect(screen.getAllByText('Active').length).toBeGreaterThan(0);
  });
});
