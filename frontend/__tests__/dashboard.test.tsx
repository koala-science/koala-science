import '@testing-library/jest-dom';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
      user: { actor_id: 'user-1', actor_type: 'user', name: 'Dr. Jane Doe' },
      accessToken: 'test-token',
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
        budget: 47,
        model_credit_usd: 7.4216,
        accepted_arguments: 23,
        papers_available: 2,
        arguments_to_next_paper: 7,
        agents: [
          {
            id: 'agent-123',
            name: 'ResearchBot 9000',
            status: 'Active',
            stats: { arguments: 8, accepted: 5 },
          },
        ],
      } as any,
      // No-op so the mounted useEffect doesn't flip loading and clobber the seeded profile.
      fetchProfile: async () => {},
    });
  });

  it('renders agent list without a kill-switch button', () => {
    render(<Dashboard />);

    expect(screen.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.queryByRole('main')).toBeNull();
    expect(screen.getByText('+ Register agent')).toHaveAttribute('data-agent-action', 'register-agent');
    expect(screen.getByText('ResearchBot 9000')).toBeInTheDocument();
    expect(screen.queryByText('Kill Switch (Revoke)')).toBeNull();
    expect(screen.getAllByText('Active').length).toBeGreaterThan(0);
  });

  it('shows the budget, accepted arguments and papers earned', () => {
    render(<Dashboard />);
    const profile = screen.getByRole('region', { name: 'Profile' });

    const value = (label: string) =>
      within(profile).getByText(label).closest('div')!.querySelector('dd')!.textContent;
    expect(value('Budget')).toBe('47');
    expect(value('Model credit')).toBe('$7.42');
    expect(value('Accepted arguments')).toBe('23');
    expect(value('Papers you can submit')).toBe('2');

    expect(within(profile).getByText(/7 more accepted arguments to your next paper/i)).toBeInTheDocument();
    const bar = within(profile).getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '3');
    expect(bar).toHaveAttribute('aria-valuemax', '10');
  });

  it('leaves the bar empty while papers are owed', () => {
    useProfileStore.setState({
      profile: { ...useProfileStore.getState().profile!, arguments_to_next_paper: 17 } as any,
    });
    render(<Dashboard />);
    const profile = screen.getByRole('region', { name: 'Profile' });

    expect(within(profile).getByText(/17 more accepted arguments to your next paper/i)).toBeInTheDocument();
    expect(within(profile).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0');
  });

  it('says one argument, not one arguments', () => {
    useProfileStore.setState({
      profile: { ...useProfileStore.getState().profile!, arguments_to_next_paper: 1 } as any,
    });
    render(<Dashboard />);
    expect(screen.getByText('1 more accepted argument to your next paper')).toBeInTheDocument();
  });

  it('shows an agent its owner\'s budget but no paper progress', () => {
    useProfileStore.setState({
      profile: {
        name: 'ResearchBot 9000',
        auth_method: 'API Key',
        budget: 47,
        model_credit_usd: 10,
        accepted_arguments: null,
        papers_available: null,
        arguments_to_next_paper: null,
        agents: [],
      } as any,
    });
    render(<Dashboard />);
    const profile = screen.getByRole('region', { name: 'Profile' });

    expect(within(profile).getByText('Budget')).toBeInTheDocument();
    expect(within(profile).getByText('$10.00')).toBeInTheDocument();
    expect(within(profile).queryByText('Accepted arguments')).toBeNull();
    expect(within(profile).queryByText('Papers you can submit')).toBeNull();
    expect(within(profile).queryByRole('progressbar')).toBeNull();
    expect(profile.textContent).not.toMatch(/null/);
  });

  it('shows each agent\'s accepted arguments against what it submitted', () => {
    render(<Dashboard />);
    const agent = screen.getByLabelText('Agent: ResearchBot 9000');
    expect(within(agent).getByText('5 accepted / 8 submitted')).toBeInTheDocument();
  });

  it('says the dashboard failed to load instead of loading forever', async () => {
    useProfileStore.setState({ loading: false, profile: null, fetchProfile: async () => {} });
    render(<Dashboard />);

    expect(await screen.findByText('Could not load your dashboard')).toBeInTheDocument();
    expect(screen.queryByText(/Loading dashboard/)).toBeNull();
  });
  it('keeps Google Scholar in the profile card, with no separate identity card', () => {
    render(<Dashboard />);

    expect(screen.queryByRole('region', { name: 'Academic identity' })).toBeNull();
    const profile = screen.getByRole('region', { name: 'Profile' });
    expect(within(profile).getByRole('button', { name: 'Add Google Scholar' })).toBeInTheDocument();
    expect(within(profile).queryByRole('textbox', { name: 'Google Scholar ID' })).toBeNull();
    expect(screen.queryByText(/orcid/i)).toBeNull();
  });

  it('links Google Scholar from the profile card by posting the entered ID', async () => {
    render(<Dashboard />);

    const profile = screen.getByRole('region', { name: 'Profile' });
    fireEvent.click(within(profile).getByRole('button', { name: 'Add Google Scholar' }));
    fireEvent.change(within(profile).getByRole('textbox', { name: 'Google Scholar ID' }), {
      target: { value: 'dkAFaXoAAAAJ' },
    });
    fireEvent.click(within(profile).getByRole('button', { name: 'Link' }));

    await waitFor(() => {
      const calls = (global.fetch as jest.Mock).mock.calls.map(([url, init]) => [String(url), init?.method]);
      expect(calls).toContainEqual([
        expect.stringContaining('/auth/scholar/link?scholar_id=dkAFaXoAAAAJ'),
        'POST',
      ]);
    });
  });

  it('shows a linked Google Scholar profile as a link', () => {
    const seeded = useProfileStore.getState().profile!;
    useProfileStore.setState({ profile: { ...seeded, google_scholar_id: 'dkAFaXoAAAAJ' } });
    render(<Dashboard />);

    const profile = screen.getByRole('region', { name: 'Profile' });
    expect(within(profile).getByRole('link', { name: 'dkAFaXoAAAAJ' })).toHaveAttribute(
      'href',
      'https://scholar.google.com/citations?user=dkAFaXoAAAAJ',
    );
    expect(within(profile).queryByRole('button', { name: 'Add Google Scholar' })).toBeNull();
  });

  it('cancelling an unfinished link clears it and returns focus to Add', async () => {
    render(<Dashboard />);

    const profile = screen.getByRole('region', { name: 'Profile' });
    fireEvent.click(within(profile).getByRole('button', { name: 'Add Google Scholar' }));
    fireEvent.change(within(profile).getByRole('textbox', { name: 'Google Scholar ID' }), {
      target: { value: 'half-typed' },
    });
    fireEvent.click(within(profile).getByRole('button', { name: 'Cancel' }));

    expect(within(profile).queryByRole('textbox', { name: 'Google Scholar ID' })).toBeNull();
    const add = within(profile).getByRole('button', { name: 'Add Google Scholar' });
    await waitFor(() => expect(add).toHaveFocus());

    fireEvent.click(add);
    expect(within(profile).getByRole('textbox', { name: 'Google Scholar ID' })).toHaveValue('');
  });
});
