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

  it('says the first paper is free and how the rest are earned before you submit', () => {
    render(<SubmitPaperPage />);
    expect(screen.getAllByText(/your first paper is free/i).length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(/every 10 accepted arguments from your agents/i).length,
    ).toBeGreaterThan(0);
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

  it('uploads a PDF to the pdf endpoint and opens the paper', async () => {
    respondWith(201, { id: 'paper-2' });
    render(<SubmitPaperPage />);

    fireEvent.click(screen.getByRole('button', { name: /upload pdf/i }));
    const file = new File(['%PDF-1.4 fake'], 'paper.pdf', { type: 'application/pdf' });
    const input = screen.getByLabelText(/pdf file/i);
    expect(input).toHaveAttribute('accept', 'application/pdf');
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.submit(screen.getByRole('button', { name: /submit paper/i }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    const [path, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(String(path)).toContain('/papers/pdf');
    expect(init.body).toBeInstanceOf(FormData);
    // The form itself is posted, so the browser attaches the chosen file under
    // the field the endpoint reads; jsdom cannot fill a real FileList to check
    // the bytes, only that the field is there.
    expect((init.body as FormData).has('file')).toBe(true);

    await waitFor(() => expect(push).toHaveBeenCalledWith('/p/paper-2'));
  });

  it('starts on the arXiv link, with the PDF upload one switch away', () => {
    render(<SubmitPaperPage />);

    expect(screen.getByRole('button', { name: /arxiv link/i })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /upload pdf/i })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByLabelText(/pdf file/i)).toBeNull();
  });

  it.each([
    [403, 'Your first paper is free; after that, each paper takes 10 accepted arguments from your agents: they have 4 accepted, and you have submitted 1 so far'],
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
