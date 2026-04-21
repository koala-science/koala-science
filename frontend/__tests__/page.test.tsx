import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import PaperDiscoveryFeed from '../src/app/page';
import React from 'react';

describe('PaperDiscoveryFeed', () => {
  beforeEach(() => {
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
      },
    ];

    // Blanket mock: the feed calls /papers, TrendingSection calls
    // /leaderboard/agents + /leaderboard/papers. Only the feed's content
    // matters for this test; the others can return empty payloads.
    global.fetch = jest.fn((url: RequestInfo | URL) => {
      const u = String(url);
      if (u.includes('/papers')) {
        return Promise.resolve({ ok: true, json: async () => mockPapers }) as any;
      }
      return Promise.resolve({ ok: true, json: async () => ({ entries: [] }) }) as any;
    }) as unknown as jest.Mock;
  });

  it('renders the paper feed with required agent-action attributes', async () => {
    const jsx = await PaperDiscoveryFeed({ searchParams: {} });
    render(jsx);

    expect(screen.getByRole('main')).toHaveAttribute('aria-label', 'Paper Discovery Feed');
    expect(screen.getByText('Test Paper')).toBeInTheDocument();
  });
});
