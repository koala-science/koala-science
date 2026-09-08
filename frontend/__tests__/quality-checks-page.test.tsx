import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import React from 'react';

jest.mock('react-markdown', () => ({
  __esModule: true,
  default: ({ children }: { children: string }) => <div>{children}</div>,
}));

import QualityChecksPage from '../src/app/quality-checks/page';

describe('Quality checks page', () => {
  it('carries every check in the order they run', () => {
    render(<QualityChecksPage />);
    const article = screen.getByLabelText(/the quality checks/i);
    for (const check of [
      '1. Moderation',
      '2. Validity',
      '3. Relevance',
      '4. Uniqueness',
      '5. Verification',
    ]) {
      expect(article).toHaveTextContent(check);
    }
  });
});
