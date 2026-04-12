import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import PaperDetailView from '../src/app/paper/[id]/page';
import React from 'react';
import { AppProvider } from '../src/lib/app-context';

global.fetch = jest.fn();

describe('PaperDetailView', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders correctly with required data-agent-action tags and ARIA labels', async () => {
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

    const mockComments = [
      {
        id: 'com-1',
        author_id: 'user-2',
        author_type: 'human',
        content_markdown: 'I agree.'
      }
    ];

    const mockRevisions = [
      {
        id: 'rev-1',
        paper_id: 'paper-123',
        version: 1,
        title: 'Detailed Paper',
        abstract: 'Detailed abstract',
        pdf_url: 'http://example.com/pdf',
        github_repo_url: 'http://example.com/repo',
        changelog: null,
        created_by_id: 'user-1',
        created_by_type: 'human',
        created_at: '2026-04-10T00:00:00Z',
        updated_at: '2026-04-10T00:00:00Z',
      }
    ];

    // fetch is called three times
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: async () => mockPaper })
      .mockResolvedValueOnce({ ok: true, json: async () => mockComments })
      .mockResolvedValueOnce({ ok: true, json: async () => mockRevisions });

    const jsx = await PaperDetailView({ params: { id: 'paper-123' } });
    render(
      <AppProvider>
        {jsx}
      </AppProvider>
    );

    // ARIA roles and labels
    expect(screen.getByRole('main')).toHaveAttribute('aria-label', 'Paper Detail');
    
    // Check download actions
    const pdfLink = screen.getByText('PDF');
    expect(pdfLink).toHaveAttribute('data-agent-action', 'download-pdf');
    expect(screen.getByText('Code')).toHaveAttribute('data-agent-action', 'view-code');
    expect(screen.getByText('1 comments')).toBeInTheDocument();
    expect(screen.getByText('Revisions')).toBeInTheDocument();
  });
});
