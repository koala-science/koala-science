import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import AdminPage from '../src/app/admin/page';
import { useAuthStore } from '../src/lib/store';
import React from 'react';

describe('AdminPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = jest.fn(() =>
      Promise.resolve({ ok: true, json: async () => ({}) }) as any
    ) as unknown as jest.Mock;
  });

  it('shows "Not authorized" for non-superusers', () => {
    useAuthStore.setState({
      isAuthenticated: true,
      hydrated: true,
      accessToken: 'tok',
      user: { actor_id: 'u1', actor_type: 'human', name: 'Jane', is_superuser: false },
    } as any);

    render(<AdminPage />);

    expect(screen.getByText('Not authorized')).toBeInTheDocument();
    expect(screen.queryByText('Users')).toBeNull();
  });

  it('shows "Not authorized" for unauthenticated visitors', () => {
    useAuthStore.setState({
      isAuthenticated: false,
      hydrated: true,
      accessToken: null,
      user: null,
    } as any);

    render(<AdminPage />);

    expect(screen.getByText('Not authorized')).toBeInTheDocument();
  });

  it('renders dashboard links for superusers', () => {
    useAuthStore.setState({
      isAuthenticated: true,
      hydrated: true,
      accessToken: 'tok',
      user: { actor_id: 'u1', actor_type: 'human', name: 'Super', is_superuser: true },
    } as any);

    render(<AdminPage />);

    expect(screen.getByText('Users')).toBeInTheDocument();
    expect(screen.getByText('Agents')).toBeInTheDocument();
    expect(screen.getByText('Papers')).toBeInTheDocument();
    expect(screen.queryByText('Not authorized')).toBeNull();
  });
});
