import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { api, type Session, type User } from '../api';
import { AuthProvider } from '../auth/AuthProvider';

vi.mock('../api', async (original) => ({ ...(await original<object>()), api: vi.fn() }));
const user: User = {
  id: 'user-id',
  username: 'pixelplayer',
  email: 'private@example.test',
  display_name: 'Player',
  rating: 1000,
  ranked_tier: null,
  ranked_matches: 4,
  ranked_wins: 2,
  ranked_losses: 2,
  title: null,
  date_joined: '2026-01-01T00:00:00Z',
};
let current: Session;
let acknowledged: boolean;
const rows = ['win', 'loss', 'no_contest'].map((outcome, index) => ({
  id: String(index),
  date: '2026-10-13T12:00:00Z',
  opponent: 'other',
  outcome,
  forfeit: outcome === 'loss',
  score: 4 - index,
  opponent_score: index,
  rating_before: 1000,
  rating_after: 1000,
  rating_delta: 0,
}));
beforeEach(() => {
  acknowledged = false;
  current = {
    user,
    restrictions: { blocked: false, probation: false, unacknowledged_warnings: [] },
  };
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path) => {
      if (path === '/api/auth/me/') return current;
      if (path.startsWith('/api/library/contributions/?'))
        return {
          count: 0,
          next: null,
          previous: null,
          results: [],
          stats: { total: 0, pending: 0, approved: 0 },
        };
      if (path === '/api/library/categories/') return [];
      if (path.startsWith('/api/auth/profiles/'))
        return path.includes('/other/') ? { ...user, id: 'other-id', username: 'other' } : user;
      if (path.startsWith('/api/ranked/history/'))
        return { count: 3, next: null, previous: null, results: rows };
      if (path === '/api/auth/logout/') {
        current = { user: null, restrictions: null };
        return undefined;
      }
      if (path === '/api/auth/settings/')
        return {
          username: user.username,
          email: user.email,
          username_change_available: true,
          username_change_available_at: '2026-04-01T00:00:00Z',
        };
      if (path === '/api/moderation/notices/')
        return {
          appeals: [],
          sanctions: [
            {
              id: 'warning-id',
              active: true,
              kind: 'warning',
              reason: 'Review the fair-play notice.',
              expires_at: '2027-01-11T12:00:00Z',
              acknowledged_at: acknowledged ? '2026-10-13T12:00:00Z' : null,
              starts_at: '2026-10-13T12:00:00Z',
              revoked_at: null,
              appeal: {
                eligible: true,
                detail: 'You can appeal this sanction.',
                available_at: null,
              },
            },
          ],
        };
      if (path.endsWith('/acknowledge/')) {
        acknowledged = true;
        current = {
          ...current,
          restrictions: { blocked: false, probation: false, unacknowledged_warnings: [] },
        };
        return {
          id: 'warning-id',
          active: true,
          kind: 'warning',
          reason: 'Review the fair-play notice.',
          expires_at: '2027-01-11T12:00:00Z',
          acknowledged_at: '2026-10-13T12:00:00Z',
        };
      }
      return {};
    });
});
const page = (route = '/profile') =>
  render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );

it('places sign out next to the username on the own profile and retains settings navigation', async () => {
  page();
  const button = await screen.findByRole('button', { name: 'Sign out' });
  expect(button.closest('header')).toContainElement(screen.getByText('@pixelplayer'));
  expect(screen.getByRole('link', { name: /Account settings/ })).toHaveAttribute(
    'href',
    '/settings/account',
  );
  fireEvent.click(button);
  await screen.findByRole('heading', { name: /A little less pixel/ });
  expect(screen.getByRole('link', { name: 'Sign in' })).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls).toContainEqual(['/api/auth/logout/', { method: 'POST' }]);
});

it('removes the redundant settings logout control', async () => {
  page('/settings/account');
  await screen.findByRole('link', { name: 'View account notices →' });
  expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument();
});

it('never shows logout on another player profile', async () => {
  page('/players/other');
  await screen.findByRole('heading', { name: '1000 Elo' });
  expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument();
});

it('shows WIN and LOSS classes and keeps No Contest and forfeits distinct', async () => {
  page();
  expect(await screen.findByText('WIN')).toHaveClass('history-outcome-win');
  expect(screen.getByText('LOSS')).toHaveClass('history-outcome-loss');
  expect(screen.getByText('NO CONTEST')).toHaveClass('history-outcome-no_contest');
  expect(screen.getByText(/Forfeit/)).toBeInTheDocument();
  expect(screen.queryByText('DRAW')).not.toBeInTheDocument();
  expect(screen.getByText('4–0')).toBeInTheDocument();
  expect(screen.getAllByText('1000 → 1000 (0)')).toHaveLength(3);
});

it('disables duplicate logout while preserving history until the request completes', async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  let finish!: () => void;
  vi.mocked(api).mockImplementation((path, options) =>
    path === '/api/auth/logout/'
      ? new Promise<void>((resolve) => {
          finish = resolve;
        })
      : original(path, options),
  );
  page();
  const button = await screen.findByRole('button', { name: 'Sign out' });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(screen.getByRole('button', { name: 'Signing out…' })).toBeDisabled();
  expect(vi.mocked(api).mock.calls.filter(([path]) => path === '/api/auth/logout/')).toHaveLength(
    1,
  );
  expect(screen.getByText('WIN')).toBeInTheDocument();
  finish();
  await screen.findByRole('heading', { name: /A little less pixel/ });
});

it('reports failed logout without pretending the account is signed out', async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation((path, options) =>
    path === '/api/auth/logout/'
      ? Promise.reject(new Error('Unable to end this session.'))
      : original(path, options),
  );
  page();
  fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to end this session.');
  expect(screen.getByRole('button', { name: 'Sign out' })).toBeEnabled();
  expect(screen.getByText('WIN')).toBeInTheDocument();
});

it('acknowledges a warning through the existing API and refreshes the restriction banner', async () => {
  current.restrictions!.unacknowledged_warnings = ['warning-id'];
  page('/account-notices');
  await screen.findByRole('heading', { name: 'Account notices' });
  fireEvent.click(await screen.findByRole('button', { name: 'Acknowledge warning' }));
  await screen.findByText('Warning acknowledged.');
  expect(await screen.findByText('Acknowledged')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Acknowledge warning' })).not.toBeInTheDocument();
  await waitFor(() =>
    expect(screen.queryByRole('link', { name: 'Review account notices' })).not.toBeInTheDocument(),
  );
});

it.each(['/ranked', '/submit'])('keeps probation restrictions visible on %s', async (route) => {
  current.restrictions!.probation = true;
  page(route);
  await screen.findByRole('alert');
  expect(screen.queryByRole('button', { name: 'Find an opponent' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Submit image/ })).not.toBeInTheDocument();
});
