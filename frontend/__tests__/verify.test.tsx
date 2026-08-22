import '@testing-library/jest-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React, { StrictMode } from 'react';

let searchParams = new URLSearchParams('token=good-token');
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
  useSearchParams: () => searchParams,
  usePathname: () => '/auth/verify',
}));

import VerifyPage from '../src/app/auth/verify/page';

describe('Email verification page', () => {
  beforeEach(() => {
    searchParams = new URLSearchParams('token=good-token');
  });

  it('does not spend the token without a deliberate submit', async () => {
    // Institutional mail scanners fetch and render links before anyone sees
    // them. Redeeming on mount would let a scanner burn the single-use link —
    // and would mean no human action was needed to finish an account.
    const fetchMock = jest.fn();
    global.fetch = fetchMock as unknown as jest.Mock;

    render(
      <StrictMode>
        <VerifyPage />
      </StrictMode>,
    );

    await waitFor(() => expect(screen.getByLabelText(/display name/i)).toBeInTheDocument());
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('sends the name and password chosen here, with the token', async () => {
    const fetchMock = jest.fn((_url: RequestInfo | URL, init?: RequestInit) =>
      Promise.resolve({ ok: true, json: async () => ({ ok: true, sent: init?.body }) }),
    );
    global.fetch = fetchMock as unknown as jest.Mock;

    render(<VerifyPage />);
    fireEvent.change(screen.getByLabelText(/display name/i), { target: { value: 'Dr Jane' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'a-good-password' } });
    fireEvent.click(screen.getByRole('button', { name: /create my account/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body).toEqual({ token: 'good-token', name: 'Dr Jane', password: 'a-good-password' });

    await waitFor(() => expect(screen.getByText(/account ready/i)).toBeInTheDocument());
  });

  it('reports a link that cannot be used', async () => {
    global.fetch = jest.fn(() =>
      Promise.resolve({
        ok: false,
        json: async () => ({ detail: { detail: 'Invalid or expired token' } }),
      }),
    ) as unknown as jest.Mock;

    render(<VerifyPage />);
    fireEvent.change(screen.getByLabelText(/display name/i), { target: { value: 'Dr Jane' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'a-good-password' } });
    fireEvent.click(screen.getByRole('button', { name: /create my account/i }));

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/invalid or expired/i),
    );
  });

  it('says so when the link carries no token', async () => {
    searchParams = new URLSearchParams('');
    const fetchMock = jest.fn();
    global.fetch = fetchMock as unknown as jest.Mock;

    render(<VerifyPage />);

    expect(screen.getByText(/missing its token/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
