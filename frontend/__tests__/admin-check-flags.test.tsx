import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import React from 'react';

import AdminCheckFlagsPage from '../src/app/admin/check-flags/page';
import { apiCall } from '../src/lib/api';
import { useAuthStore } from '../src/lib/store';

jest.mock('../src/lib/api', () => ({ apiCall: jest.fn() }));

const mockedApiCall = apiCall as jest.MockedFunction<typeof apiCall>;

const common = {
  flagger_id: 'h1',
  flagger_name: 'A reader',
  argument_claim: 'A claim.',
  paper_id: 'p1',
  paper_title: 'A Paper',
  created_at: '2026-09-25T12:00:00Z',
};

describe('AdminCheckFlagsPage', () => {
  beforeEach(() => {
    useAuthStore.setState({
      isAuthenticated: true,
      hydrated: true,
      accessToken: 'tok',
      user: { actor_id: 'u1', actor_type: 'human', name: 'Admin', is_superuser: true },
    } as never);
    mockedApiCall.mockResolvedValue({
      items: [
        {
          ...common,
          id: 'f1',
          reason: 'Validity misread it.',
          argument_id: 'a1',
          check_id: 'c1',
          check_name: 'validity',
          check_version: 'v2',
          check_status: 'failed',
          strength: null,
        },
        {
          ...common,
          id: 'f2',
          reason: 'Overrated.',
          argument_id: 'a2',
          check_id: null,
          check_name: null,
          check_version: null,
          check_status: null,
          strength: 'critical',
        },
      ],
      total: 2,
      page: 1,
      limit: 50,
    } as never);
  });

  it('lists a check flag by its check and a strength flag by the level disputed', async () => {
    render(<AdminCheckFlagsPage />);

    expect(await screen.findByText('Validity misread it.')).toBeInTheDocument();
    expect(screen.getByText('validity')).toBeInTheDocument();
    expect(screen.getByText('Overrated.')).toBeInTheDocument();
    expect(screen.getByText('strength (critical)')).toBeInTheDocument();
  });
});
