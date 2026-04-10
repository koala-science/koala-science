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
      domain: 'd/LLM-Alignment',
      title: 'Detailed Paper',
      abstract: 'Detailed abstract',
      pdf_url: 'http://example.com/pdf',
      github_repo_url: 'http://example.com/repo'
    };

    const mockReviews = [
      {
        id: 'rev-1',
        reviewer_type: 'Agent',
        confidence_score: 9,
        content_markdown: 'Great paper.',
        proof_of_work: { hash: 'abc' }
      }
    ];

    const mockComments = [
      {
        id: 'com-1',
        author_type: 'HumanAccount',
        content_markdown: 'I agree.'
      }
    ];

    // fetch is called three times
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: async () => mockPaper })
      .mockResolvedValueOnce({ ok: true, json: async () => mockReviews })
      .mockResolvedValueOnce({ ok: true, json: async () => mockComments });

    const jsx = await PaperDetailView({ params: { id: 'paper-123' } });
    render(
      <AppProvider>
        {jsx}
      </AppProvider>
    );

    // ARIA roles and labels
    expect(screen.getByRole('main')).toHaveAttribute('aria-label', 'Paper Detail and Debate Thread');
    
    // Check download actions
    const pdfLink = screen.getByText('Open PDF in new tab');
    expect(pdfLink).toHaveAttribute('data-agent-action', 'download-pdf');

    // Wait, the acceptance criteria mention "download, comment, reply, view-proof" 
    // but the actual code has download-pdf, submit-comment (and input-comment), reply-comment, view-proof
    
    // Check view-proof
    const viewProofContainers = screen.getAllByText(/Attached Proof of Work/);
    expect(viewProofContainers.length).toBeGreaterThan(0);
    // The closest parent with data-agent-action
    expect(viewProofContainers[0].closest('div[data-agent-action="view-proof"]')).toBeInTheDocument();

    // Check comment textarea and submit
    const textarea = screen.getByPlaceholderText('Add a comment or rebuttal...');
    expect(textarea).toHaveAttribute('data-agent-action', 'input-comment');
    expect(screen.getByText('Post Comment')).toHaveAttribute('data-agent-action', 'submit-comment');

    // Check reply
    const replyButtons = screen.getAllByText('Reply');
    replyButtons.forEach(btn => {
      expect(btn).toHaveAttribute('data-agent-action', 'reply-comment');
    });
  });
});
