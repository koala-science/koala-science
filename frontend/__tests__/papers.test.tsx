import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import PapersPage from '../src/app/papers/page';

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
  },
];

describe('Papers feed', () => {
  beforeEach(() => {
    global.fetch = jest.fn((url: RequestInfo | URL) => {
      const u = String(url);
      if (u.includes('/papers')) {
        return Promise.resolve({ ok: true, json: async () => mockPapers }) as any;
      }
      return Promise.resolve({ ok: true, json: async () => ({ entries: [] }) }) as any;
    }) as unknown as jest.Mock;
  });

  it('renders the feed', async () => {
    render(await PapersPage({ searchParams: {} }));
    expect(screen.getByRole('heading', { level: 1, name: 'Papers' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Paper Feed' })).toBeInTheDocument();
    expect(screen.getByText('Test Paper')).toBeInTheDocument();
  });

  it('says so when the feed could not be loaded, rather than showing nothing', async () => {
    (global.fetch as jest.Mock).mockImplementation(() => Promise.resolve({ ok: false, status: 500 }));
    render(await PapersPage({ searchParams: {} }));
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong');
    expect(screen.queryByText('No papers yet')).not.toBeInTheDocument();
  });

  it('shows an empty state when there are no papers', async () => {
    (global.fetch as jest.Mock).mockImplementation(() => Promise.resolve({ ok: true, json: async () => [] }));
    render(await PapersPage({ searchParams: {} }));
    expect(screen.getByText('No papers yet')).toBeInTheDocument();
  });

  it('asks the API for activity order by default', async () => {
    await PapersPage({ searchParams: {} });
    const urls = (global.fetch as jest.Mock).mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes('sort=active'))).toBe(true);
  });

  it('offers both orderings, marking the active one', async () => {
    render(await PapersPage({ searchParams: {} }));
    expect(screen.getByText('Active').closest('a')).toHaveAttribute('href', '/papers');
    expect(screen.getByText('Newest').closest('a')).toHaveAttribute('href', '/papers?sort=new');
    expect(screen.getByText('Active').closest('a')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('navigation', { name: 'Feed order' })).toBeInTheDocument();
  });

  it('honours an explicit newest sort', async () => {
    await PapersPage({ searchParams: { sort: 'new' } });
    const urls = (global.fetch as jest.Mock).mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes('sort=new'))).toBe(true);
  });
});
