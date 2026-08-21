import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import { Footer } from '../src/components/layout/footer';
import React from 'react';
import fs from 'fs';
import path from 'path';

describe('Footer', () => {
  it('is how a reader reaches the About page', () => {
    render(<Footer />);
    const about = screen.getByText('About').closest('a');
    expect(about).toHaveAttribute('href', '/about');
    expect(about).toHaveAttribute('data-agent-action', 'nav-about');
  });

  it('points agents at the skill guide', () => {
    render(<Footer />);
    const skill = screen.getByText('For agents').closest('a');
    expect(skill).toHaveAttribute('href', '/skill.md');
    expect(skill).toHaveAttribute('data-agent-action', 'view-skill');
  });

  it('is mounted in the root layout', () => {
    // Rendering Footer in isolation cannot catch the regression that made
    // /about unreachable: the component was fine, nothing rendered it.
    const layout = fs.readFileSync(
      path.join(process.cwd(), 'src', 'app', 'layout.tsx'),
      'utf-8',
    );
    expect(layout).toMatch(/<Footer\s*\/>/);
  });
});
