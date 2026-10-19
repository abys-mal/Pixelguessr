import { render, screen, within } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigationType } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { api, type User } from '../api';
import { AuthContext, type AuthState } from '../auth/context';

vi.mock('../api', async (original) => ({ ...(await original<object>()), api: vi.fn() }));
const player: User = {
  id: 'stable-account-id',
  username: 'renamed',
  email: 'private@example.test',
  display_name: 'Player',
  rating: 1000,
  ranked_tier: null,
  ranked_matches: 0,
  ranked_wins: 0,
  ranked_losses: 0,
  title: null,
  date_joined: '2026-01-01T00:00:00Z',
};
let session: AuthState;
let publicPlayer: User;
beforeEach(() => {
  session = {
    user: null,
    restrictions: null,
    loading: false,
    error: '',
    refresh: vi.fn(),
    signOut: vi.fn(),
  };
  publicPlayer = player;
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path) => {
      if (path.startsWith('/api/auth/profiles/')) return publicPlayer;
      if (path.startsWith('/api/ranked/history/'))
        return { count: 0, next: null, previous: null, results: [] };
      return {};
    });
});
function Location() {
  return (
    <output aria-label="Current location">
      {useLocation().pathname}:{useNavigationType()}
    </output>
  );
}
function page(route = '/') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthContext.Provider value={session}>
        <App />
        <Location />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}
it('welcomes guests with account creation and all existing guest-compatible modes', () => {
  page();
  expect(screen.getByRole('heading', { name: /A little less pixel/ })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Create an account' })).toHaveAttribute(
    'href',
    '/register',
  );
  expect(screen.getByRole('link', { name: 'Try singleplayer' })).toHaveAttribute(
    'href',
    '/singleplayer',
  );
  expect(screen.getByRole('heading', { name: 'Singleplayer' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Parties' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Ranked Duels' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Join a Party' })).toHaveAttribute('href', '/party/join');
  expect(screen.queryByText(/Singleplayer is here/)).not.toBeInTheDocument();
});
it('gives signed-in players practical mode cards first and a graceful empty ranked standing', () => {
  session.user = player;
  page();
  expect(screen.getByRole('heading', { name: 'Play Pixelguessr' })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: /A little less pixel/ })).not.toBeInTheDocument();
  const modes = within(screen.getByRole('region', { name: 'Game modes' }));
  expect(modes.getAllByRole('heading').map((h) => h.textContent)).toEqual([
    'Ranked Duels',
    'Singleplayer',
    'Parties',
  ]);
  expect(modes.getByRole('link', { name: /Play singleplayer/ })).toHaveAttribute(
    'href',
    '/singleplayer',
  );
  expect(modes.getByRole('link', { name: /Create Party/ })).toHaveAttribute('href', '/party/new');
  expect(modes.getByRole('link', { name: /Play Ranked Duel/ })).toHaveAttribute('href', '/ranked');
  expect(screen.getByText('1000 Elo')).toBeInTheDocument();
  expect(screen.getByText(/No rated duels yet/)).toBeInTheDocument();
});
it('keeps important suspension notices visible on the dashboard', () => {
  session.user = player;
  session.restrictions = {
    blocked: true,
    probation: false,
    unacknowledged_warnings: [],
    notice: { kind: 'suspension', message: 'Play is restricted.', expires_at: null },
  };
  page();
  expect(screen.getByRole('status', { name: 'Account notice' })).toHaveTextContent(
    'Play is restricted.',
  );
  expect(screen.getByRole('link', { name: /View details/ })).toHaveAttribute(
    'href',
    '/account-notices',
  );
});
it('never flashes the promotional homepage while authentication loads', () => {
  session.loading = true;
  page();
  expect(screen.getByText('Loading your game dashboard…')).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: /A little less pixel/ })).not.toBeInTheDocument();
});
it.each([
  ['/terms', 'Terms of Service'],
  ['/privacy', 'Privacy Policy'],
])('makes %s public with an explicit draft date and shared policy navigation', (route, title) => {
  page(route);
  expect(screen.getByRole('heading', { name: title })).toBeInTheDocument();
  expect(screen.getByText('Effective date')).toBeInTheDocument();
  expect(screen.getByText('Pending operator confirmation')).toBeInTheDocument();
  const footer = within(screen.getByRole('navigation', { name: 'Information and policies' }));
  expect(footer.getByRole('link', { name: 'Terms of Service' })).toHaveAttribute('href', '/terms');
  expect(footer.getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute('href', '/privacy');
});
it('keeps policy navigation for authenticated players and links policies in registration', () => {
  session.user = player;
  const view = page('/');
  expect(screen.getByRole('navigation', { name: 'Information and policies' })).toHaveTextContent(
    'Privacy Policy',
  );
  view.unmount();
  session.user = null;
  page('/register');
  const acknowledgment = screen.getByText(/By creating an account/);
  expect(within(acknowledgment).getByRole('link', { name: 'Terms of Service' })).toHaveAttribute(
    'href',
    '/terms',
  );
  expect(within(acknowledgment).getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute(
    'href',
    '/privacy',
  );
});
it('canonicalizes an own public profile by stable ID, even with a changed username, using replace', async () => {
  session.user = { ...player, username: 'oldname' };
  page('/players/renamed');
  expect(await screen.findByText('/profile:REPLACE')).toBeInTheDocument();
});
it('redirects once ownership is known even if match history is unavailable', async () => {
  session.user = player;
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.startsWith('/api/auth/profiles/')) return player;
    throw new Error('Match history unavailable.');
  });
  page('/players/renamed');
  expect(await screen.findByText('/profile:REPLACE')).toBeInTheDocument();
});
it.each([true, false])(
  'preserves public profiles for another account or guest (signed in: %s)',
  async (signedIn) => {
    session.user = signedIn ? player : null;
    publicPlayer = { ...player, id: 'another-id', username: 'another', display_name: 'Another' };
    page('/players/another');
    expect(await screen.findByRole('heading', { name: 'Another' })).toBeInTheDocument();
    expect(screen.getByLabelText('Current location')).toHaveTextContent('/players/another:POP');
  },
);
it('waits for authentication before loading or redirecting a public profile', () => {
  session.loading = true;
  page('/players/renamed');
  expect(screen.getByText('Loading profile…')).toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Current location')).toHaveTextContent('/players/renamed:POP');
});
