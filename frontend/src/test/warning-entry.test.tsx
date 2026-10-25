import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { AuthContext, type AuthState } from '../auth/context';
import { PartyEntry } from '../pages/Party';
import { RankedEntry } from '../pages/Ranked';
import { rankedApi } from '../games/ranked';
import { SanctionAccessNotice } from '../components/SanctionAccessNotice';
import { restrictedSanction, type SanctionFeature } from '../components/sanctionAccess';

vi.mock('../games/ranked', async (original) => ({
  ...(await original<object>()),
  rankedApi: { queue: vi.fn().mockResolvedValue({ status: 'idle', rating: 1000 }) },
}));
const auth: AuthState = {
  user: {
    id: 'user',
    username: 'player',
    display_name: 'Player',
    email: 'player@example.test',
    rating: 1000,
    ranked_tier: null,
    title: null,
    ranked_matches: 0,
    ranked_wins: 0,
    ranked_losses: 0,
    date_joined: '2026-01-01',
  },
  restrictions: { blocked: false, probation: false, unacknowledged_warnings: ['warning'] },
  loading: false,
  error: '',
  refresh: vi.fn(),
  signOut: vi.fn(),
};

function sanctioned(kind: 'warning' | 'probation' | 'suspension'): AuthState {
  return {
    ...auth,
    restrictions: {
      blocked: false,
      probation: kind === 'probation',
      suspension: kind === 'suspension',
      unacknowledged_warnings: kind === 'warning' ? ['warning'] : [],
      notice: {
        kind,
        message: 'Public account notice',
        expires_at: kind === 'warning' ? null : '2070-01-01T12:00:00Z',
      },
    },
  };
}

for (const feature of ['ranked', 'party', 'contributions'] as SanctionFeature[]) {
  it.each(['warning', 'probation', 'suspension'] as const)(
    `uses the shared notice for %s on ${feature}`,
    (kind) => {
      const value = sanctioned(kind);
      render(
        <MemoryRouter>
          <AuthContext.Provider value={value}>
            <SanctionAccessNotice feature={feature} />
          </AuthContext.Provider>
        </MemoryRouter>,
      );
      if (kind === 'probation' && feature === 'party') {
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(restrictedSanction(value.restrictions, feature)).toBeUndefined();
      } else {
        expect(screen.getByRole('alert', { name: 'Account restriction' })).toHaveClass(
          'sanction-access-notice',
          `tone-${kind}`,
        );
        expect(screen.getByRole('link', { name: 'View account notices' })).toHaveAttribute(
          'href',
          '/account-notices',
        );
        expect(screen.getByRole('heading', { level: 3 })).toBeInTheDocument();
      }
    },
  );
}

it.each(['probation', 'suspension'] as const)(
  'keeps the ranked lobby visible and disables entry during %s',
  async (kind) => {
    const count = vi.mocked(rankedApi.queue).mock.calls.length;
    const view = render(
      <MemoryRouter>
        <AuthContext.Provider value={sanctioned(kind)}>
          <RankedEntry />
        </AuthContext.Provider>
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { name: 'Ranked Duel' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Find opponent' })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveClass('sanction-access-notice');
    expect(vi.mocked(rankedApi.queue).mock.calls).toHaveLength(count);
    view.rerender(
      <MemoryRouter>
        <AuthContext.Provider
          value={{ ...auth, restrictions: { ...auth.restrictions!, unacknowledged_warnings: [] } }}
        >
          <RankedEntry />
        </AuthContext.Provider>
      </MemoryRouter>,
    );
    expect(await screen.findByRole('button', { name: 'Find opponent' })).toBeEnabled();
  },
);

it.each([true, false])(
  'disables party entry for suspension while leaving probation available (create=%s)',
  (create) => {
    const view = render(
      <MemoryRouter>
        <AuthContext.Provider value={sanctioned('suspension')}>
          <PartyEntry create={create} />
        </AuthContext.Provider>
      </MemoryRouter>,
    );
    expect(
      screen.getByRole('button', { name: create ? 'Create Party' : 'Join Party' }),
    ).toBeDisabled();
    view.rerender(
      <MemoryRouter>
        <AuthContext.Provider value={sanctioned('probation')}>
          <PartyEntry create={create} />
        </AuthContext.Provider>
      </MemoryRouter>,
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: create ? 'Create Party' : 'Join Party' }),
    ).toBeEnabled();
  },
);

it('shows the warning gate for party entry when probation and a warning coexist', () => {
  const value = sanctioned('probation');
  value.restrictions!.unacknowledged_warnings = ['warning'];
  render(
    <MemoryRouter>
      <AuthContext.Provider value={value}>
        <SanctionAccessNotice feature="party" />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
  expect(screen.getByRole('alert')).toHaveClass('tone-warning');
});

it.each([true, false])('requires acknowledgment on the party entry form (create=%s)', (create) => {
  render(
    <MemoryRouter>
      <AuthContext.Provider value={auth}>
        <PartyEntry create={create} />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
  expect(
    screen.getByRole('button', { name: create ? 'Create Party' : 'Join Party' }),
  ).toBeDisabled();
  expect(screen.getByRole('link', { name: 'View account notices' })).toHaveAttribute(
    'href',
    '/account-notices',
  );
});

it('disables new ranked searches and unlocks them after acknowledgment', async () => {
  const view = render(
    <MemoryRouter>
      <AuthContext.Provider value={auth}>
        <RankedEntry />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('button', { name: 'Find opponent' })).toBeDisabled();
  expect(screen.getByRole('link', { name: 'View account notices' })).toBeInTheDocument();
  view.rerender(
    <MemoryRouter>
      <AuthContext.Provider
        value={{ ...auth, restrictions: { ...auth.restrictions!, unacknowledged_warnings: [] } }}
      >
        <RankedEntry />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
  expect(screen.getByRole('button', { name: 'Find opponent' })).toBeEnabled();
});
