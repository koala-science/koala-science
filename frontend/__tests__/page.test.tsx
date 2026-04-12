import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import PaperDiscoveryFeed from '../src/app/page';
import React from 'react';

// Mock fetch
global.fetch = jest.fn();

describe('PaperDiscoveryFeed', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders correctly with required data-agent-action tags and ARIA labels', async () => {
    const mockPapers = [
      {
        id: '1',
        domains: ['d/LLM-Alignment'],
        submitter_id: 'user-1',
        submitter_type: 'Human',
        title: 'Test Paper',
        abstract: 'Test Abstract',
        pdf_url: 'http://example.com/pdf',
        github_repo_url: 'http://example.com/repo',
        net_score: 0,
      }
    ];

    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockPapers
    });

    const jsx = await PaperDiscoveryFeed({ searchParams: {} });
    render(jsx);

    // ARIA roles and labels
    expect(screen.getByRole('main')).toHaveAttribute('aria-label', 'Paper Discovery Feed');
    expect(screen.getByRole('region', { name: 'Paper Feed' })).toBeInTheDocument();

    const newSortLink = screen.getByText('New');
    expect(newSortLink).toHaveAttribute('data-agent-action', 'sort-feed');
    expect(newSortLink).toHaveAttribute('data-sort', 'new');

    // Paper specific actions
    const paperLink = screen.getByText('Test Paper');
    expect(paperLink).toHaveAttribute('data-agent-action', 'view-paper');
    expect(paperLink).toHaveAttribute('data-paper-id', '1');

    const upvoteBtn = screen.getAllByLabelText('Upvote')[0];
    expect(upvoteBtn).toHaveAttribute('data-agent-action', 'upvote-paper');
    expect(upvoteBtn).toHaveAttribute('data-paper-id', '1');
  });
});
