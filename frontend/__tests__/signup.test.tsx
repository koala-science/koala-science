import '@testing-library/jest-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';

// Separate mocks on purpose: aliasing them made every navigation assertion pass
// whichever method the page actually called.
const push = jest.fn();
const replace = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace }),
}));

import SignupPage from '../src/app/auth/signup/page';

const fillAndSubmit = () => {
  fireEvent.change(screen.getByLabelText(/email/i), {
    target: { value: 'tester@mila.quebec' },
  });
  fireEvent.change(screen.getByLabelText(/openreview id/i), {
    target: { value: '~Test_Er1' },
  });
  fireEvent.click(screen.getByRole('button', { name: /create account/i }));
};

const respondWith = (body: Record<string, unknown>) => {
  const fetchMock = jest.fn(() => Promise.resolve({ ok: true, json: async () => body }));
  global.fetch = fetchMock as unknown as jest.Mock;
  return fetchMock;
};

describe('Signup page', () => {
  beforeEach(() => {
    push.mockClear();
    replace.mockClear();
  });

  it('tells the person to check their email when no token comes back', async () => {
    respondWith({ verification_required: true, email: 'tester@mila.quebec' });
    render(<SignupPage />);
    fillAndSubmit();

    await waitFor(() => expect(screen.getByText(/check your email/i)).toBeInTheDocument());
    expect(replace).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it('goes straight to the verify page when a token comes back', async () => {
    // Self-serve onboarding: no sender is configured, so waiting on mail would
    // strand the person on a page telling them to check an inbox nothing reaches.
    respondWith({
      verification_required: true,
      email: 'tester@mila.quebec',
      verification_token: 'raw-token-123',
    });
    render(<SignupPage />);
    fillAndSubmit();

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith('/auth/verify?token=raw-token-123'),
    );
    expect(push).not.toHaveBeenCalled();
    expect(screen.queryByText(/check your email/i)).not.toBeInTheDocument();
  });

  it('escapes a token that would otherwise alter the URL', async () => {
    respondWith({
      verification_required: true,
      email: 'tester@mila.quebec',
      verification_token: 'a&b=c',
    });
    render(<SignupPage />);
    fillAndSubmit();

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith('/auth/verify?token=a%26b%3Dc'),
    );
  });
});
