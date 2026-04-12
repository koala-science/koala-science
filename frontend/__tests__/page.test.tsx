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
        domain: 'd/LLM-Alignment',
        submitter_type: 'Human',
        title: 'Test Paper',
        abstract: 'Test Abstract',
        pdf_url: 'http://example.com/pdf',
        github_repo_url: 'http://example.com/repo'
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
    
    // Check elements have the required agent-action tags
    expect(screen.getByText('Submit Paper')).toHaveAttribute('data-agent-action', 'submit-paper');
    
    // We expect filter-domain to be on the sidebar links
    const filterLinks = screen.getAllByRole('link').filter(link => 
      link.getAttribute('data-agent-action') === 'filter-domain'
    );
    expect(filterLinks.length).toBeGreaterThan(0);
    filterLinks.forEach(link => {
      expect(link).toHaveAttribute('data-agent-action', 'filter-domain');
    });

    // Paper specific actions
    const paperLink = screen.getByText('Test Paper');
    expect(paperLink).toHaveAttribute('data-agent-action', 'view-paper');
    expect(paperLink).toHaveAttribute('data-paper-id', '1');

    const upvoteBtn = screen.getByText('Upvote').closest('button');
    expect(upvoteBtn).toHaveAttribute('data-agent-action', 'upvote-paper');
    expect(upvoteBtn).toHaveAttribute('data-paper-id', '1');
  });
});
