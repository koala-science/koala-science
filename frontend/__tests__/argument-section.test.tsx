import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';

import { ArgumentSection } from '../src/components/paper/argument-section';
import { apiCall, apiFetch } from '../src/lib/api';
import { useAuthStore } from '../src/lib/store';

jest.mock('../src/lib/api', () => ({
  apiCall: jest.fn(),
  apiFetch: jest.fn(),
}));

const mockedApiCall = apiCall as jest.MockedFunction<typeof apiCall>;
const mockedApiFetch = apiFetch as jest.MockedFunction<typeof apiFetch>;

const base = {
  id: 'a1',
  paper_id: 'p1',
  author_id: 'agent-1',
  author_name: 'critic-05e1',
  claim: 'The evaluation omits a no-retrieval baseline.',
  position: 'negative' as const,
  evidence: 'Section 4.1 compares retrieval variants only.',
  state: 'pending' as const,
  created_at: '2026-08-19T12:00:00Z',
  checks: [],
};

function checksOf(
  argumentId: string,
  status: 'pending' | 'passed' | 'failed',
  names = ['moderation', 'validity', 'relevance', 'uniqueness'],
) {
  return names.map((name) => ({
    id: `${argumentId}-${name}`,
    name,
    version: 'v1',
    status,
    detail: status === 'failed' ? 'low_effort' : 'ok',
    flag_count: 0,
  }));
}

const negative = {
  ...base, id: 'neg', claim: 'A criticism.', state: 'accepted' as const, checks: checksOf('neg', 'passed'),
};
const positive = {
  ...base, id: 'pos', position: 'positive' as const, claim: 'A piece of praise.',
  state: 'accepted' as const, checks: checksOf('pos', 'passed'),
};
const rejected = {
  ...base,
  id: 'rej',
  state: 'rejected' as const,
  claim: 'A rejected claim.',
  checks: checksOf('rej', 'failed', ['moderation']),
};
const pending = {
  ...base,
  id: 'pend',
  claim: 'A pending claim.',
  checks: checksOf('pend', 'pending', ['moderation']),
};

describe('ArgumentSection', () => {
  it('opens on negative and shows only negative arguments that passed', () => {
    render(<ArgumentSection paperId="p1" arguments={[negative, positive, rejected]} />);

    expect(screen.getByText(negative.claim)).toBeInTheDocument();
    expect(screen.queryByText(positive.claim)).not.toBeInTheDocument();
    expect(screen.queryByText(rejected.claim)).not.toBeInTheDocument();
  });

  it('switches to positive', () => {
    render(<ArgumentSection paperId="p1" arguments={[negative, positive, rejected]} />);
    fireEvent.click(screen.getByRole('tab', { name: /positive/i }));

    expect(screen.getByText(positive.claim)).toBeInTheDocument();
    expect(screen.queryByText(negative.claim)).not.toBeInTheDocument();
  });

  it('switches to rejected', () => {
    render(<ArgumentSection paperId="p1" arguments={[negative, positive, rejected]} />);
    fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));

    expect(screen.getByText(rejected.claim)).toBeInTheDocument();
    expect(screen.queryByText(negative.claim)).not.toBeInTheDocument();
    expect(screen.queryByText(positive.claim)).not.toBeInTheDocument();
  });

  it('a rejected argument leaves its position bucket entirely', () => {
    const rejectedPositive = { ...rejected, id: 'rp', position: 'positive' as const, claim: 'Rejected praise.' };
    render(<ArgumentSection paperId="p1" arguments={[positive, rejectedPositive]} />);

    fireEvent.click(screen.getByRole('tab', { name: /positive/i }));
    expect(screen.getByText(positive.claim)).toBeInTheDocument();
    expect(screen.queryByText(rejectedPositive.claim)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));
    expect(screen.getByText(rejectedPositive.claim)).toBeInTheDocument();
  });

  it('an argument still being checked is not in a position tab', () => {
    render(<ArgumentSection paperId="p1" arguments={[pending]} />);

    expect(screen.queryByText(pending.claim)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /pending/i }));
    expect(screen.getByText(pending.claim)).toBeInTheDocument();
    expect(screen.getByLabelText('moderation: checking')).toBeInTheDocument();
  });

  it('a pending positive argument waits in Pending, not Positive', () => {
    const pendingPraise = {
      ...pending, id: 'pp', position: 'positive' as const, claim: 'Unchecked praise.',
    };
    render(<ArgumentSection paperId="p1" arguments={[positive, pendingPraise]} />);

    fireEvent.click(screen.getByRole('tab', { name: /positive/i }));
    expect(screen.getByText(positive.claim)).toBeInTheDocument();
    expect(screen.queryByText(pendingPraise.claim)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /pending/i }));
    expect(screen.getByText(pendingPraise.claim)).toBeInTheDocument();
  });

  it('only fully-checked arguments make the position tabs', () => {
    const halfway = {
      ...base, id: 'half', claim: 'Cleared two of four.',
      checks: checksOf('half', 'passed', ['moderation', 'validity']),
    };
    render(<ArgumentSection paperId="p1" arguments={[negative, halfway]} />);

    expect(screen.getByText(negative.claim)).toBeInTheDocument();
    expect(screen.queryByText(halfway.claim)).not.toBeInTheDocument();
  });

  it('counts each bucket in its tab', () => {
    render(<ArgumentSection paperId="p1" arguments={[negative, positive, rejected, pending]} />);

    expect(screen.getByRole('tab', { name: /negative/i })).toHaveTextContent('1');
    expect(screen.getByRole('tab', { name: /positive/i })).toHaveTextContent('1');
    expect(screen.getByRole('tab', { name: /pending/i })).toHaveTextContent('1');
    expect(screen.getByRole('tab', { name: /rejected/i })).toHaveTextContent('1');
  });

  it('shows why a rejected argument failed, once opened', () => {
    render(<ArgumentSection paperId="p1" arguments={[rejected]} />);
    fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));

    expect(screen.queryByText(/low_effort/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: new RegExp(rejected.claim, 'i') }));
    expect(screen.getByText(/low_effort/)).toBeInTheDocument();
  });

  it('shows only the claim until the argument is opened', () => {
    render(<ArgumentSection paperId="p1" arguments={[negative]} />);

    expect(screen.getByText(negative.claim)).toBeInTheDocument();
    expect(screen.queryByText(negative.evidence)).not.toBeInTheDocument();
    expect(screen.queryByText(negative.author_name)).not.toBeInTheDocument();
  });

  it('reveals the evidence when clicked, and hides it again', () => {
    render(<ArgumentSection paperId="p1" arguments={[negative]} />);
    const toggle = screen.getByRole('button', { name: new RegExp(negative.claim, 'i') });

    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(negative.evidence)).toBeInTheDocument();
    expect(screen.getByText(negative.author_name)).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText(negative.evidence)).not.toBeInTheDocument();
  });

  it('opens each argument independently', () => {
    const other = { ...negative, id: 'other', claim: 'Another criticism.', evidence: 'Other evidence.' };
    render(<ArgumentSection paperId="p1" arguments={[negative, other]} />);

    fireEvent.click(screen.getByRole('button', { name: new RegExp(negative.claim, 'i') }));
    expect(screen.getByText(negative.evidence)).toBeInTheDocument();
    expect(screen.queryByText(other.evidence)).not.toBeInTheDocument();
  });

  it('tells you an empty bucket is empty, not that the paper has nothing', () => {
    render(<ArgumentSection paperId="p1" arguments={[negative]} />);
    fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));
    expect(screen.getByText(/no rejected arguments/i)).toBeInTheDocument();
  });

  it('renders an empty state when a paper has no arguments at all', () => {
    render(<ArgumentSection paperId="p1" arguments={[]} />);
    expect(screen.getByText(/no arguments yet/i)).toBeInTheDocument();
  });

  describe('the check pipeline', () => {
    const PIPELINE = ['moderation', 'validity', 'relevance', 'uniqueness'];

    it('shows every stage even when only the first has a row', () => {
      render(<ArgumentSection paperId="p1" arguments={[pending]} />);
      fireEvent.click(screen.getByRole('tab', { name: /pending/i }));

      expect(screen.getByLabelText('moderation: checking')).toBeInTheDocument();
      for (const name of ['validity', 'relevance', 'uniqueness']) {
        expect(screen.getByLabelText(`${name}: not run`)).toBeInTheDocument();
      }
    });

    it('renders the whole pipeline on the collapsed row', () => {
      render(<ArgumentSection paperId="p1" arguments={[pending]} />);
      fireEvent.click(screen.getByRole('tab', { name: /pending/i }));

      const rail = screen.getByRole('list', { name: /check pipeline/i });
      expect(rail).toBeInTheDocument();
      expect(screen.getAllByRole('listitem')).toHaveLength(PIPELINE.length);
    });

    it('marks the stages an argument cleared, and the one it failed', () => {
      const failedLate = {
        ...base,
        id: 'late',
        state: 'rejected' as const,
        claim: 'Failed at relevance.',
        checks: [
          ...checksOf('late', 'passed', ['moderation', 'validity']),
          { id: 'late-relevance', name: 'relevance', version: 'v1', status: 'failed' as const, detail: 'cosmetic: a typo', flag_count: 0 },
        ],
      };
      render(<ArgumentSection paperId="p1" arguments={[failedLate]} />);
      fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));

      expect(screen.getByLabelText('moderation: passed')).toBeInTheDocument();
      expect(screen.getByLabelText('validity: passed')).toBeInTheDocument();
      expect(screen.getByLabelText('relevance: failed')).toBeInTheDocument();
      // never queued, because the sequence stops at the first failure
      expect(screen.getByLabelText('uniqueness: not run')).toBeInTheDocument();
    });

    it('an accepted argument shows a check for every stage', () => {
      const accepted = {
        ...base,
        id: 'acc',
        state: 'accepted' as const,
        claim: 'Cleared everything.',
        checks: checksOf('acc', 'passed', PIPELINE),
      };
      render(<ArgumentSection paperId="p1" arguments={[accepted]} />);

      for (const name of PIPELINE) {
        expect(screen.getByLabelText(`${name}: passed`)).toBeInTheDocument();
      }
    });

    it('keeps the failure reason out of the collapsed row', () => {
      render(<ArgumentSection paperId="p1" arguments={[rejected]} />);
      fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));

      expect(screen.getByLabelText('moderation: failed')).toBeInTheDocument();
      expect(screen.queryByText(/low_effort/)).not.toBeInTheDocument();
    });

    it('takes the newest version when a check was re-run', () => {
      const rechecked = {
        ...base,
        id: 're',
        state: 'accepted' as const,
        claim: 'Re-run at v2.',
        checks: [
          { id: 're-mod-v1', name: 'moderation', version: 'v1', status: 'failed' as const, detail: 'low_effort', flag_count: 0 },
          { id: 're-mod-v2', name: 'moderation', version: 'v2', status: 'passed' as const, detail: 'ok', flag_count: 0 },
        ],
      };
      render(<ArgumentSection paperId="p1" arguments={[rechecked]} />);

      expect(screen.getByLabelText('moderation: passed')).toBeInTheDocument();
      expect(screen.queryByLabelText('moderation: failed')).not.toBeInTheDocument();
    });
  });


  describe('flagging a check as wrong', () => {
    const HUMAN = { actor_id: 'h1', actor_type: 'human', name: 'A reader' };

    function loginAs(user: typeof HUMAN | null) {
      act(() => {
        useAuthStore.setState({
          isAuthenticated: user !== null,
          user,
          accessToken: user === null ? null : 'token',
          hydrated: true,
        });
      });
    }

    beforeEach(() => {
      mockedApiCall.mockReset();
      mockedApiFetch.mockReset();
      mockedApiCall.mockResolvedValue([] as never);
      loginAs(null);
    });

    afterEach(() => loginAs(null));

    // Failed at validity, not at moderation: an argument that fails moderation
    // is withheld from the paper page entirely, so its checks are never
    // reachable to flag.
    const flaggable = {
      ...base,
      id: 'flagme',
      state: 'rejected' as const,
      claim: 'A contested claim.',
      checks: [
        ...checksOf('flagme', 'passed', ['moderation']),
        ...checksOf('flagme', 'failed', ['validity']),
      ],
    };

    function withFlagsOnValidity(count: number) {
      return {
        ...flaggable,
        checks: flaggable.checks.map((c) =>
          c.name === 'validity' ? { ...c, flag_count: count } : c,
        ),
      };
    }

    /** Render, open the rejected tab, expand the card, and let the mount fetch settle. */
    async function openTheCard(argument = flaggable) {
      render(<ArgumentSection paperId="p1" arguments={[argument]} />);
      fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));
      fireEvent.click(screen.getByRole('button', { name: new RegExp(argument.claim, 'i') }));
      await act(async () => {});
    }

    it('offers a flag on a check that produced a result', async () => {
      await openTheCard();
      expect(screen.getByRole('button', { name: /flag validity as wrong/i })).toBeInTheDocument();
    });

    it('offers nothing on a check that has not run or is still running', () => {
      render(<ArgumentSection paperId="p1" arguments={[pending]} />);
      fireEvent.click(screen.getByRole('tab', { name: /pending/i }));
      fireEvent.click(screen.getByRole('button', { name: new RegExp(pending.claim, 'i') }));

      expect(screen.queryByRole('button', { name: /flag .* as wrong/i })).not.toBeInTheDocument();
    });

    it('sends a guest to log in rather than to a composer', async () => {
      await openTheCard();
      fireEvent.click(screen.getByRole('button', { name: /flag validity as wrong/i }));

      expect(screen.getByRole('link', { name: /log in/i })).toHaveAttribute('href', '/auth/login');
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    });

    it('will not submit an empty reason', async () => {
      loginAs(HUMAN);
      await openTheCard();
      fireEvent.click(screen.getByRole('button', { name: /flag validity as wrong/i }));

      expect(screen.getByRole('button', { name: /flag as wrong/i })).toBeDisabled();
      fireEvent.change(screen.getByRole('textbox'), { target: { value: '   ' } });
      expect(screen.getByRole('button', { name: /flag as wrong/i })).toBeDisabled();
    });

    it('posts the reason and shows the check as flagged by you', async () => {
      loginAs(HUMAN);
      mockedApiCall.mockImplementation(async (path: string) =>
        (path.startsWith('/check-flags/mine') ? [] : { reason: 'Moderation misread the tone.' }) as never,
      );
      await openTheCard();

      fireEvent.click(screen.getByRole('button', { name: /flag validity as wrong/i }));
      fireEvent.change(screen.getByRole('textbox'), {
        target: { value: 'Moderation misread the tone.' },
      });
      fireEvent.click(screen.getByRole('button', { name: /flag as wrong/i }));

      await waitFor(() =>
        expect(screen.getByText(/you flagged this check as wrong/i)).toBeInTheDocument(),
      );
      expect(mockedApiCall).toHaveBeenCalledWith('/check-flags/', {
        method: 'POST',
        body: JSON.stringify({ check_id: 'flagme-validity', reason: 'Moderation misread the tone.' }),
      });
      expect(screen.getByText('Moderation misread the tone.')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /you flagged validity/i })).toHaveTextContent('1');
    });

    it('shows a flag you already filed, fetched on mount', async () => {
      loginAs(HUMAN);
      mockedApiCall.mockImplementation(async (path: string) =>
        (path.startsWith('/check-flags/mine')
          ? [{ check_id: 'flagme-validity', reason: 'Filed earlier.' }]
          : {}) as never,
      );
      await openTheCard();

      await waitFor(() => expect(screen.getByText('Filed earlier.')).toBeInTheDocument());
      expect(mockedApiCall).toHaveBeenCalledWith('/check-flags/mine?paper_id=p1');
    });

    it('withdraws a flag and puts the count back', async () => {
      loginAs(HUMAN);
      const flagged = withFlagsOnValidity(2);
      mockedApiCall.mockImplementation(async (path: string) =>
        (path.startsWith('/check-flags/mine')
          ? [{ check_id: 'flagme-validity', reason: 'Filed earlier.' }]
          : {}) as never,
      );
      mockedApiFetch.mockResolvedValue({ ok: true } as Response);
      await openTheCard(flagged);

      await waitFor(() => expect(screen.getByText('Filed earlier.')).toBeInTheDocument());
      fireEvent.click(screen.getByRole('button', { name: /withdraw/i }));

      await waitFor(() =>
        expect(screen.queryByText(/you flagged this check as wrong/i)).not.toBeInTheDocument(),
      );
      expect(mockedApiFetch).toHaveBeenCalledWith('/check-flags/flagme-validity', { method: 'DELETE' });
      expect(screen.getByRole('button', { name: /1 person flagged this check/i })).toBeInTheDocument();
    });

    it('surfaces a rejected flag instead of pretending it landed', async () => {
      loginAs(HUMAN);
      mockedApiCall.mockImplementation(async (path: string) => {
        if (path.startsWith('/check-flags/mine')) return [] as never;
        throw new Error('You have already flagged this check');
      });
      await openTheCard();

      fireEvent.click(screen.getByRole('button', { name: /flag validity as wrong/i }));
      fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Again.' } });
      fireEvent.click(screen.getByRole('button', { name: /flag as wrong/i }));

      await waitFor(() =>
        expect(screen.getByText(/already flagged this check/i)).toBeInTheDocument(),
      );
      expect(screen.queryByText(/you flagged this check as wrong/i)).not.toBeInTheDocument();
    });

    it('counts flagged checks on the collapsed card', () => {
      const contested = withFlagsOnValidity(3);
      render(<ArgumentSection paperId="p1" arguments={[contested]} />);
      fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));

      expect(screen.getByLabelText("3 flags on this argument's checks")).toBeInTheDocument();
    });

    it('leaves the collapsed card unmarked when nothing is flagged', () => {
      render(<ArgumentSection paperId="p1" arguments={[flaggable]} />);
      fireEvent.click(screen.getByRole('tab', { name: /rejected/i }));

      expect(screen.queryByLabelText(/flags? on this argument/i)).not.toBeInTheDocument();
    });

    it('shows an agent the count without a way to flag', async () => {
      loginAs({ actor_id: 'a1', actor_type: 'agent', name: 'critic-05e1' });
      const contested = withFlagsOnValidity(2);
      await openTheCard(contested);

      expect(screen.getByLabelText(/2 people flagged this check/i)).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /flag validity as wrong/i })).not.toBeInTheDocument();
    });
  });

  it('keeps the rail out of the toggle\'s accessible name', () => {
    // A <button> has presentational children, so a rail inside it would both
    // lose its own labels and append "Check pipeline" to every toggle.
    render(<ArgumentSection paperId="p1" arguments={[negative]} />);

    const toggle = screen.getByRole('button', { name: negative.claim });
    expect(toggle).toBeInTheDocument();
    expect(toggle).not.toHaveTextContent('Check pipeline');
  });
});
