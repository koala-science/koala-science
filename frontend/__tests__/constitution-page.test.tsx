import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import React from 'react';

jest.mock('react-markdown', () => ({
  __esModule: true,
  default: ({ children }: { children: string }) => <div>{children}</div>,
}));

import ConstitutionPage from '../src/app/constitution/page';

describe('Constitution page', () => {
  it('carries every check in the order they run', () => {
    render(<ConstitutionPage />);
    const article = screen.getByLabelText(/the constitution/i);
    for (const check of ['1. Moderation', '2. Validity', '3. Relevance', '4. Uniqueness']) {
      expect(article).toHaveTextContent(check);
    }
  });
});
