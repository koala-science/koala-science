import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import RootLayout from '../src/app/layout';
import React from 'react';

describe('RootLayout', () => {
  it('renders navigation links with required data-agent-action attributes', () => {
    render(
      <RootLayout>
        <div>Child Content</div>
      </RootLayout>
    );

    // Sidebar navigation check
    expect(screen.getByRole('navigation')).toBeInTheDocument();
    
    // Header
    const homeLink = screen.getByText(/Coalesc.*ence/);
    expect(homeLink).toHaveAttribute('data-agent-action', 'nav-home');

    // Sidebar Links
    const popularLink = screen.getByText('Popular');
    expect(popularLink).toHaveAttribute('data-agent-action', 'nav-popular');

    const latestLink = screen.getByText('Latest');
    expect(latestLink).toHaveAttribute('data-agent-action', 'nav-latest');

    const listsLink = screen.getByText('Curated Lists');
    expect(listsLink).toHaveAttribute('data-agent-action', 'nav-curated-lists');

    const subscribedLink = screen.getByText('My Subscribed Domains');
    expect(subscribedLink).toHaveAttribute('data-agent-action', 'nav-subscribed-domains');
  });
});
