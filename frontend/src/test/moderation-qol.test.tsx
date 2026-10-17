import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { api, type Session, type User } from '../api';
import { AuthProvider } from '../auth/AuthProvider';
import { App } from '../App';
import { DeleteImage } from '../administration/DeleteImage';
import { ImageEditor, ImageLibrary } from '../administration/Images';
import type { LibraryImage } from '../administration/api';
import { PlayerInformation } from '../moderation/PlayerInformation';
import { AdministratorPlayerControls } from '../administration/PlayerControls';

vi.mock('../api', async (original) => ({ ...(await original<object>()), api: vi.fn() }));
const actor: User = {
  id: 'actor-id',
  username: 'operator',
  email: 'private@example.test',
  display_name: 'Operator',
  rating: 1000,
  ranked_tier: null,
  ranked_matches: 0,
  ranked_wins: 0,
  ranked_losses: 0,
  title: null,
  date_joined: '2026-01-01T00:00:00Z',
  moderation_access: true,
  administrator: true,
};
const player = {
  id: '01234567-89ab-cdef-8123-456789abcdef',
  username: 'target',
  display_name: 'Target player',
  rating: 1234,
  date_joined: '2026-10-17T12:34:56.123456+00:00',
  is_active: true,
  protected: false,
  moderator: false,
  deletion_eligible: true,
  role: 'Player',
  statuses: ['Voluntarily closed'],
  ranked_matches: 7,
  ranked_wins: 4,
  ranked_losses: 3,
};
const image: LibraryImage = {
  id: 'image-id',
  canonical_answer: 'rose',
  accepted_synonyms: [],
  category: 1,
  category_name: 'Nature',
  status: 'retired',
  license: 'CC0',
  attribution: 'Credit',
  source_url: '',
  source: 'manual',
  preview_url: '/private-preview/',
  review_reason: '',
  import_metadata: {},
};
const warning = {
  id: 'warning-id',
  kind: 'warning',
  category: 'other',
  reason: 'Public reason',
  internal_note: 'Internal note',
  starts_at: '2026-10-10T00:00:00Z',
  expires_at: '2027-01-08T00:00:00Z',
  acknowledged_at: null,
  revoked_at: null,
  issued_by: 'operator',
  revoked_by: null,
  replaces: null,
  active: true,
  state: 'active',
};
let current: Session;
let closingReason: string;
let resolved: boolean;
let fail: string;
const pageData = <T,>(rows: T[]) => ({
  results: rows,
  count: rows.length,
  next: null,
  previous: null,
});

beforeEach(() => {
  current = { user: actor, restrictions: null };
  closingReason = '';
  resolved = false;
  fail = '';
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open');
  };
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path, options) => {
      if (path === '/api/auth/me/') return current;
      if (path.startsWith('/api/auth/profiles/')) return { ...player, ranked_tier: null };
      if (path.startsWith('/api/ranked/history/')) return pageData([]);
      if (path === '/api/auth/logout/') {
        if (fail) throw new Error(fail);
        current = { user: null, restrictions: null };
        return {};
      }
      if (path === '/api/moderation/reports/') {
        if (fail) throw new Error(fail);
        return { id: 'report-id' };
      }
      if (path.endsWith('/images/image-id/delete/')) {
        if (fail) throw new Error(fail);
        return { deleted: true };
      }
      if (path.startsWith('/api/moderation/workspace/administration/images/?'))
        return pageData([image]);
      if (path === '/api/library/categories/') return [{ id: 1, name: 'Nature', slug: 'nature' }];
      if (path === '/api/moderation/workspace/')
        return {
          administrator: current.user?.administrator,
          pending_reports: 0,
          pending_appeals: 1,
        };
      if (path.startsWith('/api/moderation/workspace/appeals/?'))
        return pageData([
          {
            id: 'appeal-id',
            player,
            sanction: warning,
            kind: 'warning',
            explanation: 'Please reconsider',
            status: resolved ? 'upheld' : 'pending',
            created_at: '2026-10-11T00:00:00Z',
            resolved_at: resolved ? '2026-10-17T00:00:00Z' : null,
            closing_reason: closingReason,
          },
        ]);
      if (path.endsWith('/appeal-id/resolve/')) {
        const body = JSON.parse(String(options?.body));
        closingReason = body.closing_reason;
        resolved = true;
        return {};
      }
      if (path.startsWith('/api/moderation/workspace/players/'))
        return { player, sanctions: [], reports: [], appeals: [], activity: [] };
      if (path === '/api/moderation/notices/')
        return {
          sanctions: [],
          appeals: [
            {
              id: 'appeal-id',
              kind: 'warning',
              explanation: 'Please reconsider',
              status: 'upheld',
              created_at: '2026-10-11T00:00:00Z',
              resolved_at: '2026-10-17T00:00:00Z',
              closing_reason: closingReason,
            },
          ],
        };
      return {};
    });
});
function LocationProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output aria-label="Current route">{location.pathname}</output>
      <button onClick={() => navigate(-1)}>Test Back</button>
    </>
  );
}
function show(node: React.ReactNode = <App />, route = '/players/target', entries?: string[]) {
  return render(
    <MemoryRouter initialEntries={entries ?? [route]}>
      <AuthProvider>
        {node}
        <LocationProbe />
      </AuthProvider>
    </MemoryRouter>,
  );
}

it('submits a private report from the public profile with the existing category values', async () => {
  show();
  await userEvent.click(await screen.findByRole('button', { name: 'Report' }));
  const dialog = within(screen.getByRole('dialog', { name: 'Report @target' }));
  expect(dialog.getByLabelText('Reason for reporting')).toBeRequired();
  expect(dialog.getByRole('option', { name: 'Other' })).toHaveValue('other');
  await userEvent.selectOptions(dialog.getByLabelText('Category'), 'other');
  await userEvent.type(
    dialog.getByLabelText('Reason for reporting'),
    'Please review this concern.',
  );
  await userEvent.click(dialog.getByRole('button', { name: 'Submit Report' }));
  await screen.findByText(/Report submitted/);
  expect(api).toHaveBeenCalledWith('/api/moderation/reports/', {
    method: 'POST',
    body: JSON.stringify({
      subject: player.id,
      category: 'other',
      details: 'Please review this concern.',
    }),
  });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
it('keeps report validation failures visible and allows cancelling without sending', async () => {
  fail = 'Too many reports. Try later.';
  show();
  await userEvent.click(await screen.findByRole('button', { name: 'Report' }));
  const dialog = within(screen.getByRole('dialog'));
  await userEvent.type(dialog.getByLabelText('Reason for reporting'), 'Review this.');
  await userEvent.click(dialog.getByRole('button', { name: 'Submit Report' }));
  expect(await dialog.findByRole('alert')).toHaveTextContent(fail);
  await userEvent.click(dialog.getByRole('button', { name: 'Cancel' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
it.each(['guest', 'self'])('hides reporting for %s', async (role) => {
  current = { user: role === 'guest' ? null : { ...actor, id: player.id }, restrictions: null };
  show();
  await screen.findByRole('heading', { name: '1234 Elo' });
  expect(screen.queryByRole('button', { name: 'Report' })).not.toBeInTheDocument();
});
it('copies the exact UUID and shows stored precision, role and status', async () => {
  const copy = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { value: { writeText: copy }, configurable: true });
  show(<PlayerInformation player={player} />);
  expect(screen.getByText(player.id)).toBeVisible();
  expect(screen.getByText(player.date_joined)).toHaveAttribute('datetime', player.date_joined);
  expect(screen.getByText('Voluntarily closed')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Copy user UUID' }));
  await screen.findByText('UUID copied.');
  expect(copy).toHaveBeenCalledWith(player.id);
});
it('keeps permanent account deletion in the shared administrator action row', async () => {
  show(
    <AdministratorPlayerControls
      detail={{ player, sanctions: [], reports: [], appeals: [], activity: [] }}
      saved={() => {}}
    />,
  );
  const button = await screen.findByRole('button', { name: 'Permanently Delete Account' });
  expect(button.parentElement).toHaveClass('mod-actions');
  expect(button.parentElement).toContainElement(
    screen.getByRole('button', { name: 'Override Elo' }),
  );
  expect(button).toHaveClass('danger');
});
it.each(['pending', 'approved'])('hides permanent image deletion for %s', async (status) => {
  show(<DeleteImage image={{ ...image, status }} deleted={() => {}} />);
  await waitFor(() => expect(api).toHaveBeenCalled());
  expect(
    screen.queryByRole('button', { name: /Permanently delete image:/ }),
  ).not.toBeInTheDocument();
});
it.each(['rejected', 'retired'])(
  'confirms permanent image deletion for %s without requiring a reason',
  async (status) => {
    const deleted = vi.fn();
    show(<DeleteImage image={{ ...image, status }} deleted={deleted} />);
    await userEvent.click(await screen.findByRole('button', { name: /Permanently delete image:/ }));
    const dialog = within(screen.getByRole('dialog', { name: 'Permanently delete image?' }));
    expect(dialog.getByText(/image-id/)).toBeInTheDocument();
    expect(dialog.queryByRole('textbox')).not.toBeInTheDocument();
    await userEvent.click(dialog.getByRole('button', { name: 'Delete Permanently' }));
    await waitFor(() => expect(deleted).toHaveBeenCalledOnce());
    expect(api).toHaveBeenCalledWith(
      '/api/moderation/workspace/administration/images/image-id/delete/',
      { method: 'POST', body: JSON.stringify({ confirm: true }) },
    );
  },
);
it('keeps image deletion errors visible and cancel does not delete', async () => {
  const deleted = vi.fn();
  fail = 'A live round is revealing this image.';
  show(<DeleteImage image={image} deleted={deleted} />);
  await userEvent.click(await screen.findByRole('button', { name: /Permanently delete image:/ }));
  await userEvent.click(screen.getByRole('button', { name: 'Delete Permanently' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(fail);
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(deleted).not.toHaveBeenCalled();
});
it('renders small image deletion controls in both the grid and drawer', async () => {
  const view = show(<ImageLibrary />);
  expect(await screen.findByRole('button', { name: /Permanently delete image:/ })).toHaveClass(
    'admin-delete-image',
  );
  view.unmount();
  show(<ImageEditor image={image} close={() => {}} saved={() => {}} />);
  expect(
    await screen.findByRole('button', { name: /Permanently delete image:/ }),
  ).toBeInTheDocument();
});
it('saves an optional appeal closing reason visible to the player', async () => {
  show(<App />, '/moderation/appeals');
  const field = await screen.findByLabelText(/Reason for closing \(optional\)/);
  expect(field).not.toBeRequired();
  await userEvent.type(field, 'We reviewed your explanation.');
  await userEvent.click(screen.getByRole('button', { name: 'Uphold' }));
  await screen.findByText('Review saved.');
  expect(api).toHaveBeenCalledWith('/api/moderation/workspace/appeals/appeal-id/resolve/', {
    method: 'POST',
    body: JSON.stringify({ decision: 'uphold', closing_reason: 'We reviewed your explanation.' }),
  });
});
it('renders player-visible appeal reasons as text and omits blank explanations', async () => {
  closingReason = '<img src=x onerror=alert(1)>';
  const view = show(<App />, '/account-notices');
  await screen.findByText(closingReason);
  expect(screen.getByText(closingReason).querySelector('img')).toBeNull();
  expect(screen.getByText('Reason for closing')).toBeInTheDocument();
  view.unmount();
  closingReason = '';
  show(<App />, '/account-notices');
  await screen.findByText('Please reconsider');
  expect(screen.queryByText('Reason for closing')).not.toBeInTheDocument();
});
it('redirects sign-out home, clears the identity and replaces the profile history entry', async () => {
  show(<App />, '/profile', ['/about', '/profile']);
  await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }));
  await screen.findByRole('heading', { name: /A little less pixel/ });
  expect(screen.getByLabelText('Current route')).toHaveTextContent(/^\/$/);
  expect(screen.queryByRole('link', { name: 'Operator' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Test Back' }));
  expect(screen.getByLabelText('Current route')).toHaveTextContent('/about');
});
it('preserves the profile and authentication state if logout fails', async () => {
  fail = 'Logout unavailable';
  show(<App />, '/profile');
  await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(fail);
  expect(screen.getByLabelText('Current route')).toHaveTextContent('/profile');
  expect(screen.getByRole('link', { name: 'Operator' })).toBeInTheDocument();
});
