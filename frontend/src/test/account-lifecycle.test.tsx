import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { api, ApiError, type User } from '../api';
import { AuthProvider } from '../auth/AuthProvider';

vi.mock('../api', async (original) => ({ ...(await original<object>()), api: vi.fn() }));
const base: User = {
  id: 'admin-id',
  username: 'operator',
  email: 'operator@example.test',
  display_name: '',
  rating: 1000,
  ranked_tier: null,
  ranked_matches: 0,
  ranked_wins: 0,
  ranked_losses: 0,
  title: null,
  date_joined: '2026-01-01',
  administrator: true,
  moderation_access: true,
};
let current: User | null;
let eligible: boolean;
let protectedTarget: boolean;
let verifyFailure: boolean;
let deleteFailure: boolean;
let calls: [string, RequestInit | undefined][];
beforeEach(() => {
  current = { ...base };
  eligible = true;
  protectedTarget = false;
  verifyFailure = false;
  deleteFailure = false;
  calls = [];
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute('open', '');
  });
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.removeAttribute('open');
  });
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path, options) => {
      calls.push([path, options]);
      if (path === '/api/auth/me/')
        return {
          user: current,
          restrictions: current
            ? { blocked: false, probation: false, unacknowledged_warnings: [] }
            : null,
        };
      if (path === '/api/auth/settings/')
        return {
          username: 'operator',
          email: base.email,
          username_change_available: true,
          username_change_available_at: '2026-01-01',
        };
      if (path === '/api/auth/verify-closure-password/') {
        if (verifyFailure) throw new ApiError('Current password is incorrect.', 400);
        return undefined;
      }
      if (path === '/api/auth/close-account/') {
        current = null;
        return { detail: 'Account closed.' };
      }
      if (path === '/api/moderation/workspace/')
        return { administrator: current?.administrator, pending_reports: 0, pending_appeals: 0 };
      if (path === '/api/moderation/workspace/players/target-id/')
        return {
          player: {
            id: 'target-id',
            username: 'closed_player',
            display_name: '',
            rating: 1000,
            date_joined: '2026-01-01',
            protected: protectedTarget,
            moderator: protectedTarget,
            deletion_eligible: eligible,
          },
          sanctions: [
            {
              id: 'closure-id',
              kind: 'closed',
              origin: 'voluntary',
              active: true,
              state: 'active',
              category: 'other',
              reason: 'Account voluntarily closed.',
              starts_at: '2026-01-01',
              expires_at: null,
              issued_by: 'closed_player',
            },
          ],
          appeals: [],
          reports: [],
          activity: [],
        };
      if (path === '/api/moderation/workspace/administration/players/target-id/delete/') {
        if (deleteFailure) throw new ApiError('Current password is incorrect.', 400);
        return { reference: 'anonymous-reference' };
      }
      if (path.startsWith('/api/moderation/workspace/players/?'))
        return { count: 0, results: [], next: null, previous: null };
      if (path === '/api/moderation/notices/') return { sanctions: [], appeals: [] };
      return {};
    });
});
function show(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

it('places a subtle closure link after settings without a danger-zone card', async () => {
  show('/settings/account');
  const link = await screen.findByRole('link', { name: 'Close account' });
  expect(link).toHaveAttribute('href', '/settings/close-account');
  expect(screen.queryByText(/Danger Zone/)).not.toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: 'Save display name' }).compareDocumentPosition(link) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});
it('runs understand, verify and final confirmation, then signs out', async () => {
  show('/settings/close-account');
  await userEvent.click(await screen.findByRole('button', { name: 'Continue to verification' }));
  expect(screen.queryByRole('button', { name: 'Close My Account' })).not.toBeInTheDocument();
  await userEvent.type(screen.getByLabelText('Current password'), 'test-only-current-password');
  await userEvent.click(screen.getByRole('button', { name: 'Verify password' }));
  await userEvent.type(await screen.findByLabelText('Confirmation phrase'), 'CLOSE MY ACCOUNT');
  expect(screen.queryByLabelText('Current password')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Close My Account' }));
  await screen.findByRole('heading', { name: 'Account closed' });
  const write = calls.find(([path]) => path === '/api/auth/close-account/');
  expect(JSON.parse(String(write?.[1]?.body))).toEqual({
    current_password: 'test-only-current-password',
    confirmation: 'CLOSE MY ACCOUNT',
  });
  expect(screen.queryByRole('link', { name: 'operator' })).not.toBeInTheDocument();
});
it('keeps verification errors on step two without sending a closure request', async () => {
  verifyFailure = true;
  show('/settings/close-account');
  await userEvent.click(await screen.findByRole('button', { name: 'Continue to verification' }));
  await userEvent.type(screen.getByLabelText('Current password'), 'incorrect');
  await userEvent.click(screen.getByRole('button', { name: 'Verify password' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Current password is incorrect.');
  expect(screen.getByLabelText('Current password')).toHaveValue('');
  expect(calls.some(([path]) => path === '/api/auth/close-account/')).toBe(false);
});
it('clears verification when navigating back and permits cancellation', async () => {
  show('/settings/close-account');
  await userEvent.click(await screen.findByRole('button', { name: 'Continue to verification' }));
  await userEvent.type(screen.getByLabelText('Current password'), 'test-only-current-password');
  await userEvent.click(screen.getByRole('button', { name: 'Verify password' }));
  await screen.findByLabelText('Confirmation phrase');
  await userEvent.click(screen.getByRole('button', { name: 'Back' }));
  expect(screen.getByLabelText('Current password')).toHaveValue('');
  await userEvent.click(screen.getByRole('link', { name: 'Cancel and return to settings' }));
  await screen.findByRole('heading', { name: 'Account settings' });
  expect(calls.some(([path]) => path === '/api/auth/close-account/')).toBe(false);
});
it('requires all sensitive deletion fields and redirects only after success', async () => {
  show('/moderation/players/target-id');
  await userEvent.click(await screen.findByRole('button', { name: 'Permanently Delete Account' }));
  const dialog = within(screen.getByRole('dialog'));
  expect(dialog.getByLabelText('Deletion reason (required)')).toBeRequired();
  expect(dialog.getByLabelText('Your current administrator password')).toHaveAttribute(
    'type',
    'password',
  );
  await userEvent.type(
    dialog.getByLabelText('Your current administrator password'),
    'test-only-admin-password',
  );
  await userEvent.type(dialog.getByLabelText('Deletion reason (required)'), 'Requested erasure');
  await userEvent.type(
    dialog.getByLabelText('Type the exact username: closed_player'),
    'closed_player',
  );
  await userEvent.click(dialog.getByRole('button', { name: 'Delete Permanently' }));
  await screen.findByText(
    'Account permanently deleted. Approved images and shared history were preserved anonymously.',
  );
  const write = calls.find(([path]) => path.endsWith('/target-id/delete/'));
  expect(JSON.parse(String(write?.[1]?.body))).toEqual({
    current_password: 'test-only-admin-password',
    reason: 'Requested erasure',
    confirmation: 'closed_player',
  });
});
it('retains a clear deletion error and clears the password after rejection', async () => {
  deleteFailure = true;
  show('/moderation/players/target-id');
  await userEvent.click(await screen.findByRole('button', { name: 'Permanently Delete Account' }));
  const dialog = within(screen.getByRole('dialog'));
  await userEvent.type(dialog.getByLabelText('Your current administrator password'), 'incorrect');
  await userEvent.type(dialog.getByLabelText('Deletion reason (required)'), 'Requested erasure');
  await userEvent.type(
    dialog.getByLabelText('Type the exact username: closed_player'),
    'closed_player',
  );
  await userEvent.click(dialog.getByRole('button', { name: 'Delete Permanently' }));
  await dialog.findByRole('alert');
  await waitFor(() =>
    expect(dialog.getByLabelText('Your current administrator password')).toHaveValue(''),
  );
});
it.each(['moderator', 'protected', 'not_closed', 'self'])(
  'does not expose deletion for %s',
  async (scenario) => {
    if (scenario === 'moderator') current = { ...base, administrator: false };
    if (scenario === 'protected') protectedTarget = true;
    if (scenario === 'not_closed') eligible = false;
    if (scenario === 'self') current = { ...base, id: 'target-id' };
    show('/moderation/players/target-id');
    await screen.findByRole('heading', { name: 'Player review' });
    expect(
      screen.queryByRole('button', { name: 'Permanently Delete Account' }),
    ).not.toBeInTheDocument();
  },
);
it('cleans up homepage availability text while retaining all primary actions', async () => {
  show('/');
  expect(screen.queryByText('Playable', { exact: true })).not.toBeInTheDocument();
  expect(screen.queryByText('Ready to play', { exact: true })).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Play Ranked Duel' })).toHaveAttribute('href', '/ranked');
  expect(screen.getByRole('link', { name: 'Play singleplayer' })).toHaveAttribute(
    'href',
    '/singleplayer',
  );
  expect(screen.getByRole('link', { name: 'Create Party' })).toHaveAttribute('href', '/party/new');
});
