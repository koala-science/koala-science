import '@testing-library/jest-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';

// katex CSS is ESM-only and breaks jest's default transformer. We're not testing
// rendering here, so stub it out.
jest.mock('../src/components/shared/latex', () => ({
  LaTeX: ({ children }: { children: string }) => <span>{children}</span>,
}));

import PaperDetailView from '../src/app/p/[id]/page';
import { PaperDetailClient } from '../src/components/paper/paper-detail-client';
import { AppProvider } from '../src/lib/app-context';
import { useAuthStore } from '../src/lib/store';

jest.mock('next/navigation', () => ({
  ...jest.requireActual('next/navigation'),
  notFound: jest.fn(() => {
    throw new Error('NEXT_NOT_FOUND');
  }),
}));

global.fetch = jest.fn();

const { notFound } = jest.requireMock('next/navigation');

const privatePaper = {
  id: 'paper-9',
  domains: ['d/NLP'],
  submitter_id: 'owner-1',
  submitter_type: 'human',
  title: 'Hidden Paper',
  abstract: 'Not for everyone.',
  is_private: true,
};

function signedInAs(actorId: string) {
  useAuthStore.setState({
    isAuthenticated: true,
    hydrated: true,
    user: { actor_id: actorId, actor_type: 'human', name: 'Reader' },
  } as any);
}

/** Stands in for Next's not-found boundary, which catches what `notFound()` throws. */
class NotFoundBoundary extends React.Component<{ children: React.ReactNode }, { caught: boolean }> {
  state = { caught: false };
  static getDerivedStateFromError() {
    return { caught: true };
  }
  render() {
    return this.state.caught ? <p>not found page</p> : this.props.children;
  }
}

function renderPaper(paper: typeof privatePaper) {
  render(<AppProvider><PaperDetailClient paper={paper} arguments={[]} /></AppProvider>);
}

describe('PaperDetailView', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (global.fetch as jest.Mock).mockReset();
    localStorage.clear();
    useAuthStore.setState({ isAuthenticated: false, hydrated: true, user: null } as any);
  });

  it('renders with PDF and Code action links', async () => {
    const mockPaper = {
      id: 'paper-123',
      domains: ['d/LLM-Alignment'],
      submitter_id: 'user-1',
      submitter_type: 'human',
      title: 'Detailed Paper',
      abstract: 'Detailed abstract',
      pdf_url: 'http://example.com/pdf',
      github_repo_url: 'http://example.com/repo',
      is_private: false,
    };

    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: async () => mockPaper })
      .mockResolvedValueOnce({ ok: true, json: async () => [] });

    const jsx = await PaperDetailView({ params: { id: 'paper-123' } });
    render(<AppProvider>{jsx}</AppProvider>);

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(mockPaper.title);
    expect(document.querySelector('[data-agent-action="download-pdf"]')).toHaveAttribute(
      'href',
      mockPaper.pdf_url,
    );
    expect(document.querySelector('[data-agent-action="view-code"]')).toHaveAttribute(
      'href',
      mockPaper.github_repo_url,
    );
  });

  it('a malformed id is a 404 straight away', async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: false, status: 422 })
      .mockResolvedValueOnce({ ok: false, status: 422 });

    await expect(PaperDetailView({ params: { id: 'nope' } })).rejects.toThrow('NEXT_NOT_FOUND');
  });

  it('a paper the server cannot show is fetched again with the reader token', async () => {
    localStorage.setItem('access_token', 'reader-token');
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: false, status: 404 })
      .mockResolvedValueOnce({ ok: false, status: 404 })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => privatePaper })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => [] });

    const jsx = await PaperDetailView({ params: { id: 'paper-9' } });
    render(<AppProvider>{jsx}</AppProvider>);

    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('Hidden Paper');
    const [path, init] = (global.fetch as jest.Mock).mock.calls[2];
    expect(String(path)).toContain('/papers/paper-9');
    expect(init.headers.Authorization).toBe('Bearer reader-token');
  });

  it('a paper the reader cannot see either is a 404', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 404 });
    jest.spyOn(console, 'error').mockImplementation(() => {});

    const jsx = await PaperDetailView({ params: { id: 'nope' } });
    render(<NotFoundBoundary><AppProvider>{jsx}</AppProvider></NotFoundBoundary>);

    expect(await screen.findByText('not found page')).toBeInTheDocument();
    expect(notFound).toHaveBeenCalled();
  });

  it('marks a private paper as private', async () => {
    signedInAs('someone-else');
    renderPaper(privatePaper);

    expect(screen.getByText('Private')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /make public/i })).not.toBeInTheDocument();
  });

  it('lets the submitter switch it between private and public', async () => {
    signedInAs('owner-1');
    (global.fetch as jest.Mock).mockImplementation(async (_path: string, init: RequestInit) =>
      init?.method === 'PATCH'
        ? { ok: true, status: 200, json: async () => ({ ...privatePaper, is_private: false }) }
        : { ok: true, status: 200, json: async () => [] },
    );
    renderPaper(privatePaper);

    fireEvent.click(screen.getByRole('button', { name: /make public/i }));

    expect(await screen.findByRole('button', { name: /make private/i })).toBeInTheDocument();
    expect(screen.queryByText('Private')).not.toBeInTheDocument();
    const patches = (global.fetch as jest.Mock).mock.calls.filter(([, init]) => init?.method === 'PATCH');
    expect(patches).toHaveLength(1);
    const [path, init] = patches[0];
    expect(String(path)).toMatch(/\/papers\/paper-9$/);
    expect(JSON.parse(init.body)).toEqual({ is_private: false });
  });

  it('an API failure says so, rather than that the paper is missing', async () => {
    (global.fetch as jest.Mock).mockRejectedValue(new Error('down'));
    jest.spyOn(console, 'error').mockImplementation(() => {});

    const jsx = await PaperDetailView({ params: { id: 'paper-123' } });
    render(<AppProvider>{jsx}</AppProvider>);

    expect(screen.getByRole('alert')).toHaveTextContent('This paper could not be loaded');
  });
});
