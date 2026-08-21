import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import React from 'react';
import fs from 'fs';
import path from 'path';
import Home from '../src/app/page';

describe('Landing page', () => {
  it('leads with the search box, not a feed', () => {
    render(<Home />);
    expect(screen.getByPlaceholderText(/search papers/i)).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /paper feed/i })).toBeNull();
  });

  it('sends a reader to the papers feed', () => {
    render(<Home />);
    const browse = screen.getByText(/browse papers/i).closest('a');
    expect(browse).toHaveAttribute('href', '/papers');
    expect(browse).toHaveAttribute('data-agent-action', 'nav-papers');
  });

  it('offers a scroll cue rather than showing what is below', () => {
    render(<Home />);
    const cue = document.querySelector('[data-agent-action="nav-about"]');
    expect(cue).toHaveAttribute('href', '#about');
    expect(cue).toHaveTextContent(/about/i);
  });

  it('gives the hero the whole first screen, so nothing below it shows on arrival', () => {
    render(<Home />);
    const hero = document.querySelector('section');
    expect(hero?.className).toMatch(/min-h-\[calc\(100svh/);
  });

  it('walks through the pipeline in the order the checks run', () => {
    render(<Home />);
    const steps = Array.from(
      document.querySelectorAll('[data-pipeline-step]'),
    ).map((el) => el.getAttribute('data-pipeline-step'));
    expect(steps).toEqual(['moderation', 'validity', 'relevance', 'uniqueness']);
  });

  it('describes each check in a sentence, without reproducing its constitution', () => {
    render(<Home />);
    const about = screen.getByLabelText(/about koala science/i);
    expect(about).toHaveTextContent(/serious contribution/i);

    // A phrase that only appears in the full constitution's worked examples.
    // Anchored to the document first: rewrite that example and this guard would
    // otherwise go on passing while asserting the absence of nothing.
    const constitution = fs.readFileSync(
      path.join(process.cwd(), 'public', 'CONSTITUTION.md'),
      'utf-8',
    );
    expect(constitution).toContain('Woof!');
    expect(about).not.toHaveTextContent(/Woof!/);
  });

  it('ends by pointing at real examples and at the full constitution', () => {
    render(<Home />);
    const examples = screen.getByText(/look at some examples/i).closest('a');
    expect(examples).toHaveAttribute('href', '/papers');

    const full = screen.getByText(/full constitution/i).closest('a');
    expect(full).toHaveAttribute('href', '/constitution');
  });

  it('opens by saying what the platform is, before explaining the pipeline', () => {
    render(<Home />);
    const about = screen.getByLabelText(/about koala science/i);
    expect(about).toHaveTextContent(/AI agent review platform for scientific papers/i);
    expect(about).toHaveTextContent(/strengths and weaknesses/i);
    expect(about).toHaveTextContent(/evidence/i);

    const intro = about.textContent ?? '';
    expect(intro.indexOf('AI agent review platform')).toBeLessThan(
      intro.indexOf('How an argument is judged'),
    );
  });

  it('closes by explaining what points are for', () => {
    render(<Home />);
    const about = screen.getByLabelText(/about koala science/i);
    expect(about).toHaveTextContent(/agents win points for their owner by reviewing/i);
    expect(about).toHaveTextContent(/humans spend points to submit papers/i);
  });
});
