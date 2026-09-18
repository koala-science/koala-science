import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import React from 'react';

// katex CSS is ESM-only and breaks jest's default transformer. We're not testing
// rendering here, so stub it out.
jest.mock('../src/components/shared/latex', () => ({
  LaTeX: ({ children }: { children: string }) => <span>{children}</span>,
}));

import PaperDetailView from '../src/app/p/[id]/page';
import { AppProvider } from '../src/lib/app-context';

jest.mock('next/navigation', () => ({
  ...jest.requireActual('next/navigation'),
  notFound: jest.fn(() => {
    throw new Error('NEXT_NOT_FOUND');
  }),
}));

global.fetch = jest.fn();

describe('PaperDetailView', () => {
  beforeEach(() => {
    jest.clearAllMocks();
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

  it('a paper that does not exist is a 404, not an error', async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: false, status: 404 })
      .mockResolvedValueOnce({ ok: false, status: 404 });

    await expect(PaperDetailView({ params: { id: 'nope' } })).rejects.toThrow('NEXT_NOT_FOUND');
  });

  it('an API failure says so, rather than that the paper is missing', async () => {
    (global.fetch as jest.Mock).mockRejectedValue(new Error('down'));
    jest.spyOn(console, 'error').mockImplementation(() => {});

    const jsx = await PaperDetailView({ params: { id: 'paper-123' } });
    render(<AppProvider>{jsx}</AppProvider>);

    expect(screen.getByRole('alert')).toHaveTextContent('This paper could not be loaded');
  });
});
