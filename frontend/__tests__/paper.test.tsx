import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import React from 'react';

// react-markdown + remark-math + katex CSS are ESM-only and break jest's default
// transformer. We're not testing markdown rendering here, so stub them out.
jest.mock('../src/components/shared/markdown', () => ({
  Markdown: ({ children }: { children: string }) => <div>{children}</div>,
}));
jest.mock('../src/components/shared/latex', () => ({
  LaTeX: ({ children }: { children: string }) => <span>{children}</span>,
}));

import PaperDetailView from '../src/app/p/[id]/page';
import { AppProvider } from '../src/lib/app-context';

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
      net_score: 0,
    };

    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: async () => mockPaper })
      .mockResolvedValueOnce({ ok: true, json: async () => [] })
      .mockResolvedValueOnce({ ok: true, json: async () => [] });

    const jsx = await PaperDetailView({ params: { id: 'paper-123' } });
    render(<AppProvider>{jsx}</AppProvider>);

    expect(screen.getByRole('main')).toHaveAttribute('aria-label', 'Paper Detail');
    expect(screen.getByText('PDF')).toHaveAttribute('data-agent-action', 'download-pdf');
    expect(screen.getByText('Code')).toHaveAttribute('data-agent-action', 'view-code');
  });
});
