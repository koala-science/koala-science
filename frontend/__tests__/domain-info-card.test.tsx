import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import { DomainInfoCard } from '../src/components/domain/domain-info-card';
import { useAuthStore } from '../src/lib/store';

describe('DomainInfoCard', () => {
  it('describes the domain without offering to join it, even when signed in', () => {
    useAuthStore.setState({ isAuthenticated: true, hydrated: true, accessToken: 'tok' } as any);
    global.fetch = jest.fn() as unknown as jest.Mock;

    render(<DomainInfoCard name="NLP" description="Language." paperCount={3} />);

    expect(screen.getByRole('heading', { name: 'd/NLP' })).toBeInTheDocument();
    expect(screen.getByText('3 papers')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /join|leave/i })).toBeNull();
    expect(screen.queryByText(/member/i)).toBeNull();
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
