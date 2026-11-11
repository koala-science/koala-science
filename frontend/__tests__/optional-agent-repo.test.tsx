import '@testing-library/jest-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { RegisterAgentModal } from '../src/components/agent/register-agent-modal';
import AdminAgentsPage from '../src/app/admin/agents/page';
import { useAuthStore } from '../src/lib/store';

function registerBody(): Record<string, unknown> {
  const call = (global.fetch as jest.Mock).mock.calls.find(([url]) =>
    String(url).includes('/auth/agents'),
  );
  expect(call).toBeDefined();
  return JSON.parse(call![1].body);
}

async function submitRegistration(repo: string) {
  render(<RegisterAgentModal />);
  fireEvent.click(screen.getByText('+ Register agent'));
  fireEvent.change(await screen.findByLabelText('Agent name'), { target: { value: 'my-agent' } });
  const repoInput = screen.getByLabelText(/Transparency repository/);
  expect(repoInput).not.toBeRequired();
  fireEvent.change(repoInput, { target: { value: repo } });
  fireEvent.submit(repoInput.closest('form')!);
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
}

describe('Registering an agent', () => {
  beforeEach(() => {
    global.fetch = jest.fn(() =>
      Promise.resolve({ ok: true, json: async () => ({ id: 'a1', api_key: 'cs_x' }) }) as any,
    ) as unknown as jest.Mock;
  });

  it('leaves the repository out when none is given', async () => {
    await submitRegistration('');

    expect(registerBody()).toEqual({ name: 'my-agent' });
  });

  it('sends the repository when one is given', async () => {
    await submitRegistration('https://github.com/org/my-agent');

    expect(registerBody()).toEqual({
      name: 'my-agent',
      github_repo: 'https://github.com/org/my-agent',
    });
  });
});

describe('Admin agents table', () => {
  it('shows a dash for an agent with no repository', async () => {
    useAuthStore.setState({
      isAuthenticated: true,
      hydrated: true,
      accessToken: 'tok',
      user: { actor_id: 'u1', actor_type: 'human', name: 'Super', is_superuser: true },
    } as any);
    global.fetch = jest.fn(() =>
      Promise.resolve({
        ok: true,
        json: async () => ({
          items: [
            {
              id: 'a1', name: 'no-repo-agent', owner_id: 'u2', owner_email: 'o@example.com',
              is_active: true, github_repo: null, created_at: '2026-11-01T00:00:00',
            },
          ],
          total: 1, page: 1, limit: 50,
        }),
      }) as any,
    ) as unknown as jest.Mock;

    render(<AdminAgentsPage />);

    const name = await screen.findByText('no-repo-agent');
    const row = name.closest('tr')!;
    expect(row).toHaveTextContent('—');
  });
});
