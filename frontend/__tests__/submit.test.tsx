import '@testing-library/jest-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';

import SubmitPaperPage from '../src/app/submit/page';
import { useAuthStore } from '../src/lib/store';

const push = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

function signedIn() {
  useAuthStore.setState({
    isAuthenticated: true,
    hydrated: true,
    accessToken: 'tok',
    user: { actor_id: 'u1', actor_type: 'human', name: 'Jane', is_superuser: false },
  } as any);
}

function respondWith(status: number, body: unknown) {
  global.fetch = jest.fn(() =>
    Promise.resolve({ ok: status < 400, status, json: async () => body }) as any
  ) as unknown as jest.Mock;
}

describe('SubmitPaperPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    signedIn();
  });

  it('asks only for a URL', () => {
    render(<SubmitPaperPage />);

    expect(screen.getByLabelText(/arxiv url/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/abstract/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^domain$/i)).not.toBeInTheDocument();
  });

  it('says what it costs before you submit', () => {
    render(<SubmitPaperPage />);
    expect(screen.getAllByText(/20 points/i).length).toBeGreaterThan(0);
  });

  it('posts the url to the arxiv endpoint and opens the paper', async () => {
    respondWith(201, { id: 'paper-1' });
    render(<SubmitPaperPage />);

    fireEvent.change(screen.getByLabelText(/arxiv url/i), {
      target: { value: '  https://arxiv.org/abs/2401.12345  ' },
    });
    fireEvent.submit(screen.getByRole('button', { name: /submit paper/i }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    const [path, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(String(path)).toContain('/papers/arxiv');
    expect(JSON.parse(init.body)).toEqual({ url: 'https://arxiv.org/abs/2401.12345' });

    await waitFor(() => expect(push).toHaveBeenCalledWith('/p/paper-1'));
  });

  it.each([
    [402, 'Insufficient points: 20 required, 5 available'],
    [409, 'That paper is already on the platform'],
    [422, 'That does not look like an arXiv URL'],
    [503, 'arXiv is unavailable, please try again later'],
  ])('surfaces the %i the server sends', async (status, detail) => {
    respondWith(status, { detail });
    render(<SubmitPaperPage />);

    fireEvent.change(screen.getByLabelText(/arxiv url/i), {
      target: { value: 'https://arxiv.org/abs/2401.12345' },
    });
    fireEvent.submit(screen.getByRole('button', { name: /submit paper/i }));

    expect(await screen.findByText(detail)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('tells a signed-out visitor to log in rather than showing the form', () => {
    useAuthStore.setState({ isAuthenticated: false, hydrated: true } as any);
    render(<SubmitPaperPage />);

    expect(screen.queryByLabelText(/arxiv url/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /log in/i })).toBeInTheDocument();
  });
});
