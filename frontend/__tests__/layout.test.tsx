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
    useAuthStore.setState({ isAuthenticated: false, user: null, hydrated: true, token: null });
  });

  it('exposes required data-agent-action attributes on nav links', () => {
    render(<Header />);

    const homeLink = screen.getByText(/Coalesc.*ence/).closest('a');
    expect(homeLink).toHaveAttribute('data-agent-action', 'nav-home');
  });
});
