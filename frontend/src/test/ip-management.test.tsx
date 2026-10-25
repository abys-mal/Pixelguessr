import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { api, ApiError, type User } from '../api';
import { AuthContext, type AuthState } from '../auth/context';
import { App } from '../App';

vi.mock('../api', async (original) => ({ ...(await original<object>()), api: vi.fn() }));
const root = '/api/moderation/workspace/administration/ip-access/';
const administrator: User = {
  id: 'admin',
  username: 'admin',
  display_name: 'Administrator',
  email: 'admin@example.test',
  rating: 1000,
  ranked_tier: null,
  title: null,
  ranked_matches: 0,
  ranked_wins: 0,
  ranked_losses: 0,
  date_joined: '2026-01-01',
  moderation_access: true,
  administrator: true,
};
const sample = {
  id: 'entry',
  list_kind: 'blacklist',
  address: '198.51.100.27',
  reason: 'Shared office review',
  activities: ['parties'],
  expires_at: null as string | null,
  status: 'active',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  created_by: 'admin',
  updated_by: 'admin',
};
let entries: (typeof sample)[];
let auth: AuthState;
let failure: string;
let listFailure: boolean;
let calls: [string, RequestInit | undefined][];
beforeEach(() => {
  entries = [{ ...sample }];
  auth = {
    user: administrator,
    restrictions: null,
    loading: false,
    error: '',
    refresh: vi.fn().mockResolvedValue(undefined),
    signOut: vi.fn().mockResolvedValue(undefined),
  };
  failure = '';
  listFailure = false;
  calls = [];
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open');
  };
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path, options) => {
      calls.push([path, options]);
      if (path === '/api/moderation/workspace/')
        return { administrator: true, pending_reports: 0, pending_appeals: 0 };
      if (path.startsWith(root)) {
        const [route, query] = path.slice(root.length).split('?');
        const [kind, id] = route.split('/');
        if (options?.method) {
          if (failure) throw new ApiError(failure, 400);
          if (options.method === 'DELETE') {
            entries = entries.filter((row) => row.id !== id);
            return;
          }
          const data = JSON.parse(String(options.body));
          const saved = {
            ...sample,
            ...data,
            id: id || 'created-entry',
            list_kind: kind,
            activities: data.activities ?? [],
            expires_at: data.expires_at ?? null,
            status: 'active',
          };
          entries = id ? entries.map((row) => (row.id === id ? saved : row)) : [...entries, saved];
          return saved;
        }
        if (listFailure) throw new Error('IP lists unavailable.');
        const params = new URLSearchParams(query);
        const q = (params.get('q') ?? '').toLowerCase();
        const rows = entries.filter(
          (row) =>
            row.list_kind === kind &&
            (row.address.toLowerCase().includes(q) || row.reason.toLowerCase().includes(q)),
        );
        const total = Math.ceil(rows.length / 24);
        const page = Math.max(1, Math.min(Number(params.get('page')) || 1, total));
        return {
          count: rows.length,
          page,
          page_size: 24,
          total_pages: total,
          next: page < total ? '?page=' + (page + 1) : null,
          previous: page > 1 ? '?page=' + (page - 1) : null,
          results: rows.slice((page - 1) * 24, page * 24),
        };
      }
      if (path === '/api/auth/register/') return { login_required: true };
      return {};
    });
});
function RouteProbe() {
  const route = useLocation();
  return <output aria-label="Current IP route">{route.pathname + route.search}</output>;
}
function show(path = '/moderation/administration/ip-management') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthContext.Provider value={auth}>
        <App />
        <RouteProbe />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}
const writes = () => calls.filter(([path, options]) => path.startsWith(root) && options?.method);
const labels = [
  'Account registration',
  'Login',
  'Singleplayer',
  'Parties',
  'Image submissions',
  'Community interactions',
];

it('places IP Management only in Administration and shows exactly two tabs', async () => {
  show();
  await screen.findByText('198.51.100.27');
  expect(
    screen.getByText(/Moderators and administrators are exempt from IP restrictions/),
  ).toBeInTheDocument();
  expect(
    within(screen.getByRole('navigation', { name: 'Administration navigation' })).getByRole(
      'link',
      { name: 'IP Management' },
    ),
  ).toBeInTheDocument();
  expect(
    within(screen.getByRole('navigation', { name: 'Moderation navigation' })).queryByRole('link', {
      name: 'IP Management',
    }),
  ).not.toBeInTheDocument();
  expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
    'Blacklist',
    'Whitelist',
  ]);
  expect(screen.getByText('Page 1 of 1')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('tab', { name: 'Whitelist' }));
  await screen.findByText('No whitelist entries match this view.');
  expect(screen.queryByRole('navigation', { name: 'Pagination' })).not.toBeInTheDocument();
  fireEvent.keyDown(screen.getByRole('tab', { name: 'Whitelist' }), { key: 'ArrowLeft' });
  await screen.findByText('198.51.100.27');
  expect(screen.getByRole('tab', { name: 'Blacklist' })).toHaveFocus();
});

it.each(['moderator', 'player', 'anonymous'])(
  'denies %s the IP screen and list API',
  async (role) => {
    auth.user =
      role === 'anonymous'
        ? null
        : { ...administrator, administrator: false, moderation_access: role === 'moderator' };
    show();
    await screen.findByRole('heading', {
      name: role === 'moderator' ? 'Administrator access required' : 'Moderator access required',
    });
    expect(calls.some(([path]) => path.startsWith(root))).toBe(false);
  },
);

it('keeps all six checkboxes independent, validates empty selection and submits custom UTC expiration', async () => {
  show();
  await userEvent.click(await screen.findByRole('button', { name: 'Add IP' }));
  const dialog = within(screen.getByRole('dialog', { name: 'Add blacklist IP' }));
  fireEvent.change(dialog.getByLabelText('IP address'), { target: { value: '2001:db8::42' } });
  fireEvent.change(dialog.getByLabelText('Internal reason'), { target: { value: 'New review' } });
  expect(dialog.getAllByRole('checkbox')).toHaveLength(6);
  expect(dialog.queryByRole('checkbox', { name: 'Ranked Duels' })).not.toBeInTheDocument();
  for (const label of labels) {
    fireEvent.click(dialog.getByRole('checkbox', { name: label }));
    expect(
      dialog.getAllByRole('checkbox').filter((input) => (input as HTMLInputElement).checked),
    ).toHaveLength(1);
    fireEvent.click(dialog.getByRole('checkbox', { name: label }));
  }
  await userEvent.click(dialog.getByRole('button', { name: 'Select all' }));
  expect(
    dialog.getAllByRole('checkbox').every((input) => (input as HTMLInputElement).checked),
  ).toBe(true);
  await userEvent.click(dialog.getByRole('button', { name: 'Clear' }));
  await userEvent.click(dialog.getByRole('button', { name: 'Save IP' }));
  expect(dialog.getByRole('alert')).toHaveTextContent('Select at least one');
  expect(writes()).toHaveLength(0);
  await userEvent.click(dialog.getByRole('checkbox', { name: 'Parties' }));
  expect(dialog.getAllByRole('radio').map((input) => (input as HTMLInputElement).value)).toEqual([
    'temporary',
    'indefinite',
  ]);
  await userEvent.click(dialog.getByRole('radio', { name: 'Temporary' }));
  fireEvent.change(dialog.getByLabelText('Expiration date and time'), {
    target: { value: '2070-01-02T12:34:56' },
  });
  expect(dialog.getByText(/Time zone:/)).toBeInTheDocument();
  await userEvent.click(dialog.getByRole('button', { name: 'Save IP' }));
  await screen.findByText('IP entry saved.');
  expect(JSON.parse(String(writes()[0][1]?.body))).toEqual({
    address: '2001:db8::42',
    reason: 'New review',
    activities: ['parties'],
    duration: 'temporary',
    expires_at: new Date('2070-01-02T12:34:56').toISOString(),
  });
});

it('rejects an invalid temporary expiration without sending a write', async () => {
  show();
  await userEvent.click(await screen.findByRole('button', { name: 'Add IP' }));
  const dialog = within(screen.getByRole('dialog'));
  await userEvent.type(dialog.getByLabelText('IP address'), '192.0.2.3');
  await userEvent.type(dialog.getByLabelText('Internal reason'), 'Review');
  await userEvent.click(dialog.getByLabelText('Login', { exact: true }));
  await userEvent.click(dialog.getByLabelText('Temporary'));
  fireEvent.change(dialog.getByLabelText('Expiration date and time'), {
    target: { value: '2000-01-01T12:00' },
  });
  await userEvent.click(dialog.getByRole('button', { name: 'Save IP' }));
  expect(dialog.getByRole('alert')).toHaveTextContent('valid future expiration');
  expect(writes()).toHaveLength(0);
});

it('edits an expired entry to indefinite and preserves its existing activity selection', async () => {
  entries = [{ ...sample, expires_at: '2000-01-01T12:00:05Z', status: 'expired' }];
  show();
  await screen.findByText('Expired');
  await userEvent.click(screen.getByRole('button', { name: 'Edit 198.51.100.27' }));
  const dialog = within(screen.getByRole('dialog', { name: 'Edit blacklist IP' }));
  expect(dialog.getByLabelText('Parties')).toBeChecked();
  await userEvent.click(dialog.getByLabelText('Indefinite'));
  await userEvent.clear(dialog.getByLabelText('Internal reason'));
  await userEvent.type(dialog.getByLabelText('Internal reason'), 'Edited review');
  await userEvent.click(dialog.getByRole('button', { name: 'Save IP' }));
  await screen.findByText('IP entry saved.');
  expect(JSON.parse(String(writes()[0][1]?.body))).toMatchObject({
    activities: ['parties'],
    duration: 'indefinite',
    expires_at: null,
    reason: 'Edited review',
  });
});

it('adds a whitelist entry without activity or expiration controls and retains values on duplicate errors', async () => {
  show('/moderation/administration/ip-management?list=whitelist');
  await userEvent.click(await screen.findByRole('button', { name: 'Add IP' }));
  const dialog = within(screen.getByRole('dialog', { name: 'Add whitelist IP' }));
  expect(dialog.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(dialog.queryByRole('radio')).not.toBeInTheDocument();
  await userEvent.type(dialog.getByLabelText('IP address'), '192.0.2.4');
  await userEvent.type(dialog.getByLabelText('Internal reason'), 'Known shared network');
  failure = 'This IP is already in this list.';
  await userEvent.click(dialog.getByRole('button', { name: 'Save IP' }));
  await dialog.findByText(failure);
  expect(dialog.getByLabelText('IP address')).toHaveValue('192.0.2.4');
  failure = '';
  await userEvent.click(dialog.getByRole('button', { name: 'Save IP' }));
  await screen.findByText('IP entry saved.');
  expect(JSON.parse(String(writes()[1][1]?.body))).toEqual({
    address: '192.0.2.4',
    reason: 'Known shared network',
  });
});

it('searches internal reasons and recovers when deleting the final item on the last page', async () => {
  entries = Array.from({ length: 25 }, (_, index) => ({
    ...sample,
    id: 'entry-' + index,
    address: '192.0.2.' + (index + 1),
  }));
  show('/moderation/administration/ip-management?list=blacklist&q=Shared&page=2');
  await screen.findByText('Page 2 of 2');
  await userEvent.click(screen.getByRole('button', { name: 'Delete 192.0.2.25' }));
  expect(writes()).toHaveLength(0);
  await userEvent.click(
    within(screen.getByRole('dialog', { name: 'Delete IP entry?' })).getByRole('button', {
      name: 'Delete IP',
    }),
  );
  await screen.findByText('Page 1 of 1');
  await waitFor(() =>
    expect(screen.getByLabelText('Current IP route')).toHaveTextContent(
      'list=blacklist&q=Shared&page=1',
    ),
  );
  const gets = calls.filter(([path, options]) => path.startsWith(root) && !options?.method);
  expect(gets).toHaveLength(2);
  await userEvent.clear(screen.getByLabelText('Search IP addresses or reasons'));
  await userEvent.type(screen.getByLabelText('Search IP addresses or reasons'), 'not found');
  await userEvent.click(screen.getByRole('button', { name: 'Search' }));
  await screen.findByText('No blacklist entries match this view.');
});

it('shows real list failures and supports retry', async () => {
  listFailure = true;
  show();
  await screen.findByText('IP lists unavailable.');
  listFailure = false;
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
  await screen.findByText('198.51.100.27');
});

it('does not claim an authenticated session when registration succeeds under a login-only restriction', async () => {
  auth.user = null;
  show('/register');
  await userEvent.type(screen.getByLabelText('Username'), 'newplayer');
  await userEvent.type(screen.getByLabelText('Email'), 'newplayer@example.test');
  await userEvent.type(
    screen.getByLabelText('Password', { exact: true }),
    'strong-new-password-734!',
  );
  await userEvent.type(screen.getByLabelText('Confirm password'), 'strong-new-password-734!');
  await userEvent.click(screen.getByRole('button', { name: 'Create account' }));
  await screen.findByText('Your account was created. Sign-in is unavailable from this network.');
  expect(screen.getByLabelText('Current IP route')).toHaveTextContent('/register');
});
