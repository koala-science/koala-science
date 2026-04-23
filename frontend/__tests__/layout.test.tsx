import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import { Header } from '../src/components/layout/header';
import { useAuthStore } from '../src/lib/store';
import React from 'react';

// Header fires off notification fetches on mount when authenticated; stub it.
global.fetch = jest.fn(() =>
  Promise.resolve({ ok: true, json: async () => ({}) }),
) as unknown as jest.Mock;

describe('Header navigation', () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: false, user: null, hydrated: true, accessToken: null });
  });

  it('exposes required data-agent-action attributes on nav links', () => {
    render(<Header />);

    const homeLink = screen.getByText(/Koala Science/).closest('a');
    expect(homeLink).toHaveAttribute('data-agent-action', 'nav-home');
  });

  it('hides Submit Paper button for non-superuser', () => {
    useAuthStore.setState({
      isAuthenticated: true,
      user: { actor_id: 'u1', actor_type: 'human', name: 'Alice', is_superuser: false },
      hydrated: true,
      accessToken: 't',
    });
    render(<Header />);
    expect(screen.queryByText('Submit Paper')).toBeNull();
  });

  it('shows Submit Paper button for superuser', () => {
    useAuthStore.setState({
      isAuthenticated: true,
      user: { actor_id: 'u1', actor_type: 'human', name: 'Admin', is_superuser: true },
      hydrated: true,
      accessToken: 't',
    });
    render(<Header />);
    expect(screen.getByText('Submit Paper')).toBeInTheDocument();
  });
});
