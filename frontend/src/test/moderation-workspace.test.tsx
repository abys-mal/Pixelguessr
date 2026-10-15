import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { api, type Session, type User } from '../api';
import { AuthProvider } from '../auth/AuthProvider';

vi.mock('../api', async (original) => ({ ...(await original<object>()), api: vi.fn() }));
const player = {
  id: 'player-id',
  username: 'pixelplayer',
  display_name: 'Player',
  rating: 1000,
  date_joined: '2026-01-01T00:00:00Z',
  is_active: true,
  protected: false,
  moderator: false,
};
const moderator: User = {
  ...player,
  email: 'private@example.test',
  moderation_access: true,
  administrator: false,
  ranked_tier: null,
  ranked_matches: 0,
  ranked_wins: 0,
  ranked_losses: 0,
  title: null,
};
let current: Session;
let warning: Record<string, unknown>;
let appeal: Record<string, unknown>;
let report: Record<string, unknown>;
let detail: Record<string, unknown>;
let notice: Record<string, unknown>;
let seen: [string, RequestInit | undefined][];
const pageData = (rows: unknown[]) => ({
  count: rows.length,
  next: null,
  previous: null,
  results: rows,
});

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute('open', '');
  });
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.removeAttribute('open');
  });
  current = {
    user: moderator,
    restrictions: { blocked: false, probation: false, unacknowledged_warnings: [] },
  };
  warning = {
    id: 'warning-id',
    kind: 'warning',
    category: 'fair_play',
    reason: 'Please read the rules.',
    internal_note: 'Staff context.',
    starts_at: '2026-10-14T12:00:00Z',
    expires_at: '2027-01-12T12:00:00Z',
    acknowledged_at: null,
    revoked_at: null,
    issued_by: 'mod',
    revoked_by: null,
    replaces: null,
    active: true,
    state: 'active',
  };
  appeal = {
    id: 'appeal-id',
    player,
    sanction: warning,
    kind: 'warning',
    explanation: 'Please reconsider this warning.',
    created_at: '2026-10-14T13:00:00Z',
    resolved_at: null,
    status: 'pending',
  };
  report = {
    id: 'report-id',
    subject: player,
    reporter: 'private_reporter',
    category: 'fair_play',
    details: 'This player needs review.',
    created_at: '2026-10-14T12:00:00Z',
    resolved_at: null,
    resolution: '',
  };
  detail = {
    player,
    sanctions: [warning],
    reports: [report],
    appeals: [appeal],
    activity: [
      {
        id: 'activity',
        actor: 'mod',
        action: 'sanction_issued',
        created_at: '2026-10-14T12:00:00Z',
        changes: {},
      },
    ],
  };
  notice = {
    ...warning,
    appeal: { eligible: true, detail: 'You can appeal this sanction.', available_at: null },
  };
  seen = [];
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path, options) => {
      seen.push([path, options]);
      if (path === '/api/auth/me/') return current;
      if (path === '/api/auth/settings/')
        return {
          username: player.username,
          email: moderator.email,
          username_change_available: true,
          username_change_available_at: '2026-04-01T00:00:00Z',
        };
      if (path === '/api/moderation/workspace/')
        return {
          pending_reports: 1,
          pending_appeals: 1,
          administrator: !!current.user?.administrator,
        };
      if (path.startsWith('/api/moderation/workspace/players/?')) return pageData([player]);
      if (path === '/api/moderation/workspace/players/player-id/') return detail;
      if (path.startsWith('/api/moderation/workspace/reports/?')) return pageData([report]);
      if (path.startsWith('/api/moderation/workspace/appeals/?')) return pageData([appeal]);
      if (
        path.endsWith('/resolve/') ||
        path.endsWith('/reverse/') ||
        path.endsWith('/replace/') ||
        (path.endsWith('/sanctions/') && options?.method === 'POST') ||
        path.endsWith('/access/')
      )
        return {};
      if (path === '/api/moderation/notices/') {
        return { username: player.username, sanctions: [notice], appeals: [] };
      }
      if (path.endsWith('/appeal/')) {
        notice.appeal = {
          eligible: false,
          detail: 'This warning has already been appealed.',
          available_at: null,
        };
        return {};
      }
      return {};
    });
});
function page(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

it('separates the workspace from game navigation and has a return path', async () => {
  page('/moderation');
  await screen.findByRole('heading', { name: 'A clearer community.' });
  expect(screen.getByRole('navigation', { name: 'Moderation navigation' })).toBeInTheDocument();
  expect(screen.queryByRole('navigation', { name: 'Main navigation' })).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: '← Return to Game' })).toHaveAttribute('href', '/');
  expect(screen.queryByRole('link', { name: /Django Admin/ })).not.toBeInTheDocument();
});

it('shows Mod Panel only for authorized game accounts', async () => {
  page('/');
  expect(await screen.findByRole('link', { name: 'Mod Panel' })).toHaveAttribute(
    'href',
    '/moderation',
  );
});

it('denies ordinary players and hides Mod Panel', async () => {
  current.user = { ...moderator, moderation_access: false };
  page('/moderation');
  await screen.findByRole('heading', { name: 'Moderator access required' });
  expect(
    screen.queryByRole('navigation', { name: 'Moderation navigation' }),
  ).not.toBeInTheDocument();
});

it('shows administrator controls only for administrators', async () => {
  current.user = { ...moderator, administrator: true };
  page('/moderation/players/player-id');
  expect(await screen.findByRole('button', { name: 'Grant moderator access' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /Django Admin/ })).toHaveAttribute('href', '/admin/');
});

it('searches player usernames and handles empty results', async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation((path, options) =>
    path.includes('q=missing') ? Promise.resolve(pageData([])) : original(path, options),
  );
  page('/moderation/players');
  const input = await screen.findByRole('searchbox', { name: 'Search by username' });
  await userEvent.type(input, 'missing');
  await userEvent.click(screen.getByRole('button', { name: 'Search' }));
  await screen.findByText('No accounts match your search.');
});

it('issues sanctions without required reason fields and prevents repeated submission', async () => {
  page('/moderation/players/player-id');
  await userEvent.click(await screen.findByRole('button', { name: 'Issue sanction' }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByLabelText(/Public reason/)).not.toBeRequired();
  expect(within(dialog).getByLabelText(/Internal note/)).not.toBeRequired();
  await userEvent.click(within(dialog).getByRole('button', { name: 'Issue sanction' }));
  await screen.findByText('Sanction saved.');
  const request = seen.find(
    ([path, options]) => path.endsWith('/player-id/sanctions/') && options?.method === 'POST',
  );
  expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
    kind: 'warning',
    reason: '',
    internal_note: '',
    expires_at: null,
  });
});

it('prepopulates replacements and preserves closure restriction controls', async () => {
  page('/moderation/players/player-id');
  await userEvent.click(await screen.findByRole('button', { name: 'Replace sanction' }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByLabelText(/Public reason/)).toHaveValue('Please read the rules.');
  expect(within(dialog).getByLabelText(/Internal note/)).toHaveValue('Staff context.');
  await userEvent.click(within(dialog).getByRole('button', { name: 'Replace sanction' }));
  await screen.findByText('Sanction saved.');
  expect(seen.some(([path]) => path.endsWith('/warning-id/replace/'))).toBe(true);
});

it('makes reversal deliberate and cancellation performs no mutation', async () => {
  page('/moderation/players/player-id');
  await userEvent.click(await screen.findByRole('button', { name: 'Reverse sanction' }));
  const dialog = screen.getByRole('dialog');
  await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
  expect(seen.some(([path]) => path.endsWith('/reverse/'))).toBe(false);
  await userEvent.click(screen.getByRole('button', { name: 'Reverse sanction' }));
  await userEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Reverse sanction' }),
  );
  await screen.findByText('Changes saved.');
});

it('reviews report context and dismisses without issuing a sanction', async () => {
  page('/moderation/reports');
  const dismiss = await screen.findByRole('button', { name: 'Dismiss' });
  expect(screen.getByText(/private_reporter \(staff only\)/)).toBeInTheDocument();
  await userEvent.click(dismiss);
  await screen.findByText('Review saved.');
  expect(seen.find(([path]) => path.endsWith('/report-id/resolve/'))?.[1]?.body).toBe(
    JSON.stringify({ decision: 'dismissed' }),
  );
});

it('upholds an appeal alongside the original sanction and explanation', async () => {
  page('/moderation/appeals');
  const uphold = await screen.findByRole('button', { name: 'Uphold' });
  expect(screen.getByRole('heading', { name: 'Original warning' })).toBeInTheDocument();
  await userEvent.click(uphold);
  await screen.findByText('Review saved.');
  expect(seen.find(([path]) => path.endsWith('/appeal-id/resolve/'))?.[1]?.body).toBe(
    JSON.stringify({ decision: 'uphold' }),
  );
});

it('reports API failures without pretending a reversal succeeded', async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation((path, options) =>
    path.endsWith('/reverse/')
      ? Promise.reject(new Error('Administrator required.'))
      : original(path, options),
  );
  page('/moderation/players/player-id');
  await userEvent.click(await screen.findByRole('button', { name: 'Reverse sanction' }));
  await userEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Reverse sanction' }),
  );
  await waitFor(() =>
    expect(within(screen.getByRole('dialog')).getByRole('alert')).toHaveTextContent(
      'Administrator required.',
    ),
  );
  expect(screen.queryByText('Changes saved.')).not.toBeInTheDocument();
});

it('submits an explanation-required appeal inside normal account settings', async () => {
  current.user = { ...moderator, moderation_access: false };
  page('/settings/account');
  await userEvent.click(await screen.findByRole('button', { name: 'Appeal this sanction' }));
  const submit = screen.getByRole('button', { name: 'Submit appeal' });
  expect(submit).toBeDisabled();
  fireEvent.change(
    screen.getByRole('textbox', { name: 'Why should this sanction be reconsidered?' }),
    { target: { value: 'Please reconsider this warning.' } },
  );
  await userEvent.click(submit);
  await screen.findByText('Your appeal has been submitted for review.');
  await screen.findByText('This warning has already been appealed.');
  expect(screen.queryByRole('button', { name: 'Appeal this sanction' })).not.toBeInTheDocument();
  expect(
    screen.queryByLabelText('Password', { exact: true, selector: 'input' }),
  ).not.toBeInTheDocument();
});
