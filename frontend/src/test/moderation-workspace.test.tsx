import { readFileSync } from 'node:fs';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { api, ApiError, type Session, type User } from '../api';
import { AuthProvider } from '../auth/AuthProvider';

const moderationCss = readFileSync('src/moderation/moderation.css', 'utf8');

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
  id: 'moderator-id',
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
    reviewer_is_issuer: false,
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

it('keeps only the moderation brand free of hover underlines and retains focus styling', async () => {
  const sharedCss = readFileSync('src/styles.css', 'utf8');
  const style = document.createElement('style');
  // Map hover to an attribute to exercise the real cascade in jsdom.
  style.textContent = (sharedCss + moderationCss).replaceAll(':hover', '[data-hover]');
  document.head.append(style);
  try {
    page('/moderation');
    await screen.findByRole('heading', { name: 'A clearer community.' });
    const brand = document.querySelector<HTMLAnchorElement>('.mod-brand')!;
    brand.setAttribute('data-hover', '');
    expect(brand).toHaveAttribute('href', '/moderation');
    expect(getComputedStyle(brand).textDecoration).toBe('none');
    brand.focus();
    expect(brand).toHaveFocus();
    expect(moderationCss).toMatch(/\.mod-shell a:focus-visible/);
    const returnLink = screen.getByRole('link', { name: '← Return to Game' });
    returnLink.setAttribute('data-hover', '');
    expect(getComputedStyle(returnLink).textDecoration).toBe('underline');
  } finally {
    style.remove();
  }
});

it.each([
  [{ username: 'renamed' }, 'renamed', 'Player'],
  [{ display_name: '' }, 'pixelplayer', ''],
  [{ username: 'renamed', display_name: 'Fresh name' }, 'renamed', 'Fresh name'],
])(
  'edits only changed names and refreshes stable player details: %j',
  async (changes, username, displayName) => {
    const fallback = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, options) => {
      if (path.endsWith('/names/')) {
        seen.push([path, options]);
        detail = {
          ...detail,
          player: { ...player, ...changes },
          activity: [
            {
              id: 'names-audit',
              actor: 'mod',
              action: 'player_names_changed',
              created_at: '2026-10-15T12:00:00Z',
              changes: Object.fromEntries(
                Object.entries(changes).map(([key, value]) => [
                  key,
                  { old: player[key as keyof typeof player], new: value },
                ]),
              ),
            },
          ],
        };
        return detail.player;
      }
      return fallback(path, options);
    });
    page('/moderation/players/player-id');
    await userEvent.click(await screen.findByRole('button', { name: 'Edit player names' }));
    const dialog = within(screen.getByRole('dialog'));
    expect(dialog.getByRole('textbox', { name: 'Username' })).toHaveValue('pixelplayer');
    expect(dialog.getByRole('textbox', { name: 'Display name' })).toHaveValue('Player');
    expect(dialog.getByRole('button', { name: 'Save changes' })).toBeDisabled();
    fireEvent.submit(dialog.getByRole('button', { name: 'Save changes' }).closest('form')!);
    expect(seen.filter(([path]) => path.endsWith('/names/'))).toHaveLength(0);
    for (const [key, value] of Object.entries(changes)) {
      fireEvent.change(
        dialog.getByRole('textbox', { name: key === 'username' ? 'Username' : 'Display name' }),
        { target: { value } },
      );
    }
    await userEvent.click(dialog.getByRole('button', { name: 'Save changes' }));
    await screen.findByText('Player names saved.');
    expect(await screen.findByRole('heading', { name: `@${username}` })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Public profile ↗' })).toHaveAttribute(
      'href',
      `/players/${username}`,
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Edit player names' })).toHaveFocus();
    const writes = seen.filter(([path]) => path.endsWith('/names/'));
    expect(writes).toHaveLength(1);
    expect(JSON.parse(String(writes[0][1]?.body))).toEqual(changes);
    expect((detail.player as typeof player).display_name).toBe(displayName);
    expect(screen.getByText('player names changed')).toBeInTheDocument();
  },
);

it('keeps validation errors next to their fields and prevents duplicate submissions', async () => {
  const fallback = vi.mocked(api).getMockImplementation()!;
  let reject!: (error: Error) => void;
  const request = new Promise<never>((_, fail) => {
    reject = fail;
  });
  vi.mocked(api).mockImplementation((path, options) => {
    if (path.endsWith('/names/')) {
      seen.push([path, options]);
      return request;
    }
    return fallback(path, options);
  });
  page('/moderation/players/player-id');
  await userEvent.click(await screen.findByRole('button', { name: 'Edit player names' }));
  const dialog = within(screen.getByRole('dialog'));
  fireEvent.change(dialog.getByRole('textbox', { name: 'Username' }), {
    target: { value: 'taken' },
  });
  const form = dialog.getByRole('button', { name: 'Save changes' }).closest('form')!;
  fireEvent.submit(form);
  fireEvent.submit(form);
  expect(dialog.getByRole('button', { name: 'Saving…' })).toBeDisabled();
  expect(dialog.getByRole('button', { name: 'Cancel' })).toBeDisabled();
  expect(seen.filter(([path]) => path.endsWith('/names/'))).toHaveLength(1);
  reject(
    new ApiError('Username unavailable.', 400, undefined, {
      username: ['This username is unavailable.'],
    }),
  );
  expect(await dialog.findByRole('alert')).toHaveTextContent('This username is unavailable.');
  expect(dialog.getByRole('textbox', { name: 'Username' })).toHaveAttribute('aria-invalid', 'true');
  expect(dialog.getByRole('textbox', { name: 'Username' })).toHaveAccessibleDescription(
    'This username is unavailable.',
  );
  expect(dialog.getByRole('textbox', { name: 'Username' })).toHaveValue('taken');
  expect(dialog.getByRole('textbox', { name: 'Username' })).toHaveFocus();
  expect(dialog.getByRole('button', { name: 'Save changes' })).toBeEnabled();
  await userEvent.click(dialog.getByRole('button', { name: 'Cancel' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it.each([false, true])(
  'exposes protected-account name editing only to administrators: %s',
  async (admin) => {
    current = { ...current, user: { ...moderator, administrator: admin } };
    detail = { ...detail, player: { ...player, protected: true, moderator: true } };
    page('/moderation/players/player-id');
    await screen.findByRole('heading', { name: '@pixelplayer' });
    expect(!!screen.queryByRole('button', { name: 'Edit player names' })).toBe(admin);
  },
);

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

it.each(['warning', 'probation', 'suspension'])(
  'retains ordinary management actions for %s',
  async (kind) => {
    warning.kind = kind;
    page('/moderation/players/player-id');
    expect(await screen.findByRole('button', { name: 'Replace sanction' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reverse sanction' })).toBeInTheDocument();
  },
);

it.each(['', 'Reviewed the closure evidence.'])(
  'keeps closure records and the administrator reopen workflow with optional reason: %s',
  async (reason) => {
    current.user = { ...moderator, administrator: true };
    warning.kind = 'closed';
    warning.reason = 'Original account closure reason';
    warning.expires_at = null;
    page('/moderation/players/player-id');
    const reopen = await screen.findByRole('button', { name: 'Reopen closed account' });
    expect(screen.getByText('Original account closure reason')).toBeInTheDocument();
    expect(screen.getByText(/Permanent/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Replace sanction' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reverse sanction' })).not.toBeInTheDocument();
    await userEvent.click(reopen);
    const dialog = within(screen.getByRole('dialog', { name: 'Reopen closed account?' }));
    const reasonField = dialog.getByLabelText('Reason (optional)');
    expect(reasonField).not.toBeRequired();
    fireEvent.change(reasonField, { target: { value: reason } });
    await userEvent.click(dialog.getByRole('button', { name: 'Confirm change' }));
    await screen.findByText('Administrator changes saved.');
    const request = seen.find(
      ([path, options]) =>
        path.endsWith('/administration/players/player-id/') && options?.method === 'POST',
    );
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({ operation: 'reopen', reason });
    expect(warning.reason).toBe('Original account closure reason');
    expect(seen.some(([path]) => /\/warning-id\/(reverse|replace)\//.test(path))).toBe(false);
  },
);

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
    JSON.stringify({ decision: 'uphold', closing_reason: '' }),
  );
});

it('reminds the original issuer and requires one cancellable uphold confirmation', async () => {
  appeal.reviewer_is_issuer = true;
  warning.issued_by = 'previous-name';
  page('/moderation/appeals');
  expect(await screen.findByRole('note')).toHaveTextContent('You issued this sanction');
  await userEvent.click(screen.getByRole('button', { name: 'Uphold' }));
  let dialog = screen.getByRole('dialog', { name: 'Confirm uphold decision' });
  expect(dialog).toHaveTextContent(
    'You originally issued this sanction. Would you still like to uphold it?',
  );
  expect(seen.filter(([path]) => path.endsWith('/resolve/'))).toHaveLength(0);
  await userEvent.click(within(dialog).getByRole('button', { name: 'Go back' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(seen.filter(([path]) => path.endsWith('/resolve/'))).toHaveLength(0);
  await userEvent.click(screen.getByRole('button', { name: 'Uphold' }));
  dialog = screen.getByRole('dialog');
  await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm uphold' }));
  await screen.findByText('Review saved.');
  const submissions = seen.filter(([path]) => path.endsWith('/resolve/'));
  expect(submissions).toHaveLength(1);
  expect(JSON.parse(String(submissions[0][1]?.body))).toEqual({
    decision: 'uphold',
    closing_reason: '',
    confirm_own_uphold: true,
  });
});

it('uses the server relationship even when the displayed issuer name matches the reviewer', async () => {
  warning.issued_by = moderator.username;
  page('/moderation/appeals');
  await userEvent.click(await screen.findByRole('button', { name: 'Uphold' }));
  expect(screen.queryByRole('note')).not.toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await screen.findByText('Review saved.');
});

it('keeps the existing reversal workflow when reviewing an originally issued sanction', async () => {
  appeal.reviewer_is_issuer = true;
  page('/moderation/appeals');
  await userEvent.click(await screen.findByRole('button', { name: 'Reverse sanction' }));
  const dialog = screen.getByRole('dialog', { name: 'Reverse the appealed sanction?' });
  expect(within(dialog).queryByText('Confirm uphold')).not.toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole('button', { name: 'Reverse sanction' }));
  await screen.findByText('Review saved.');
  expect(JSON.parse(String(seen.find(([path]) => path.endsWith('/resolve/'))?.[1]?.body))).toEqual({
    decision: 'reverse',
    closing_reason: '',
  });
});

it('disables confirmation while saving and prevents duplicate appeal submissions', async () => {
  appeal.reviewer_is_issuer = true;
  let finish!: () => void;
  const fallback = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation((path, options) => {
    if (path.endsWith('/resolve/')) {
      seen.push([path, options]);
      return new Promise<void>((resolve) => {
        finish = resolve;
      });
    }
    return fallback(path, options);
  });
  page('/moderation/appeals');
  await userEvent.click(await screen.findByRole('button', { name: 'Uphold' }));
  const dialog = screen.getByRole('dialog');
  const confirm = within(dialog).getByRole('button', { name: 'Confirm uphold' });
  fireEvent.click(confirm);
  fireEvent.click(confirm);
  expect(within(dialog).getByRole('button', { name: 'Saving…' })).toBeDisabled();
  expect(within(dialog).getByRole('button', { name: 'Go back' })).toBeDisabled();
  expect(seen.filter(([path]) => path.endsWith('/resolve/'))).toHaveLength(1);
  finish();
  await screen.findByText('Review saved.');
});

it('does not show an issuer reminder on a resolved historical appeal', async () => {
  appeal.reviewer_is_issuer = true;
  appeal.status = 'upheld';
  page('/moderation/appeals');
  await screen.findByRole('heading', { name: 'Original warning' });
  expect(screen.queryByRole('note')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Uphold' })).not.toBeInTheDocument();
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

it('submits an explanation-required appeal on the normal-session notices page', async () => {
  current.user = { ...moderator, moderation_access: false };
  page('/account-notices');
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

it.each(['reports', 'appeals'])(
  'keeps %s empty cards padded by the shared card rule',
  async (kind) => {
    const original = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation((path, options) =>
      path.startsWith(`/api/moderation/workspace/${kind}/?`)
        ? Promise.resolve(pageData([]))
        : original(path, options),
    );
    const style = document.createElement('style');
    style.textContent = moderationCss;
    document.head.append(style);
    try {
      page(`/moderation/${kind}`);
      const heading = await screen.findByRole('heading', { name: 'All clear.' });
      const card = heading.parentElement!;
      expect(within(card).getByText(`No ${kind} need review right now.`)).toBeInTheDocument();
      const padding = getComputedStyle(card);
      expect(parseFloat(padding.paddingLeft)).toBeGreaterThan(0);
      expect(padding.paddingLeft).toBe(padding.paddingRight);
      expect(padding.paddingTop).toBe(padding.paddingLeft);
      expect(padding.paddingBottom).toBe(padding.paddingLeft);
    } finally {
      style.remove();
    }
  },
);

it.each(['probation', 'suspension'])(
  'can repeatedly switch fixed and indefinite %s before issuing',
  async (kind) => {
    page('/moderation/players/player-id');
    await userEvent.click(await screen.findByRole('button', { name: 'Issue sanction' }));
    const dialog = within(screen.getByRole('dialog'));
    await userEvent.click(dialog.getByRole('radio', { name: kind }));
    const duration = dialog.getByRole('combobox', { name: 'Duration' });
    expect(duration).toHaveValue('indefinite');
    for (let i = 0; i < 2; i++) {
      await userEvent.selectOptions(duration, 'fixed');
      const expiry = dialog.getByLabelText(/Expires at/);
      expect(expiry).toHaveValue('');
      expect(expiry).toBeRequired();
      fireEvent.change(expiry, { target: { value: '2027-06-01T12:30' } });
      await userEvent.selectOptions(duration, 'indefinite');
      expect(dialog.queryByLabelText(/Expires at/)).not.toBeInTheDocument();
    }
    await userEvent.click(dialog.getByRole('button', { name: 'Issue sanction' }));
    await screen.findByText('Sanction saved.');
    const request = seen.find(
      ([path, options]) => path.endsWith('/player-id/sanctions/') && options?.method === 'POST',
    );
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({ kind, expires_at: null });
  },
);

it.each(['probation', 'suspension'])(
  'prepopulates fixed %s replacement and clears expiry for indefinite',
  async (kind) => {
    warning.kind = kind;
    page('/moderation/players/player-id');
    await userEvent.click(await screen.findByRole('button', { name: 'Replace sanction' }));
    const dialog = within(screen.getByRole('dialog'));
    const duration = dialog.getByRole('combobox', { name: 'Duration' });
    expect(duration).toHaveValue('fixed');
    expect(dialog.getByLabelText(/Expires at/)).not.toHaveValue('');
    await userEvent.selectOptions(duration, 'indefinite');
    await userEvent.click(dialog.getByRole('button', { name: 'Replace sanction' }));
    await screen.findByText('Sanction saved.');
    const request = seen.find(([path]) => path.endsWith('/warning-id/replace/'));
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({ kind, expires_at: null });
  },
);

it.each(['probation', 'suspension'])(
  'prepopulates indefinite %s replacement and submits a fresh fixed expiry',
  async (kind) => {
    warning.kind = kind;
    warning.expires_at = null;
    page('/moderation/players/player-id');
    await screen.findByText('Indefinite', { exact: false });
    await userEvent.click(await screen.findByRole('button', { name: 'Replace sanction' }));
    const dialog = within(screen.getByRole('dialog'));
    const duration = dialog.getByRole('combobox', { name: 'Duration' });
    expect(duration).toHaveValue('indefinite');
    await userEvent.selectOptions(duration, 'fixed');
    const field = dialog.getByLabelText(/Expires at/);
    expect(field).toHaveValue('');
    await userEvent.click(dialog.getByRole('button', { name: 'Replace sanction' }));
    expect(field).toBeInvalid();
    expect(seen.some(([path]) => path.endsWith('/warning-id/replace/'))).toBe(false);
    fireEvent.change(field, { target: { value: '2027-06-01T12:30' } });
    await userEvent.click(dialog.getByRole('button', { name: 'Replace sanction' }));
    await screen.findByText('Sanction saved.');
    const request = seen.find(([path]) => path.endsWith('/warning-id/replace/'));
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      kind,
      expires_at: new Date('2027-06-01T12:30').toISOString(),
    });
  },
);

it.each(['probation', 'suspension'])(
  'shows %s upheld-decision cooldown and its next eligibility date',
  async (kind) => {
    notice.kind = kind;
    notice.expires_at = null;
    notice.appeal = {
      eligible: false,
      detail: 'The appeal cooldown has not ended since the last upheld decision.',
      available_at: '2027-03-15T12:00:00Z',
    };
    page('/account-notices');
    await screen.findByRole('heading', { name: 'Account notices', level: 1 });
    const region = await screen.findByRole('region', { name: 'Sanctions and appeals' });
    expect(await within(region).findByText(/last upheld decision/)).toBeInTheDocument();
    expect(
      within(region).getByText(new Date('2027-03-15T12:00:00Z').toLocaleString()),
    ).toBeInTheDocument();
    expect(within(region).getByText(/Indefinite/)).toBeInTheDocument();
    expect(
      within(region).queryByRole('button', { name: 'Appeal this sanction' }),
    ).not.toBeInTheDocument();
    expect(within(region).queryByText('Staff context.')).not.toBeInTheDocument();
  },
);

it.each(['closed', 'open', 'suspension', 'probation', 'inactive'])(
  'shows a red Closed badge only for authoritative closure: %s',
  async (state) => {
    const original = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, options) =>
      path.startsWith('/api/moderation/workspace/players/?')
        ? pageData([{ ...player, closed: state === 'closed', is_active: state !== 'inactive' }])
        : original(path, options),
    );
    page('/moderation/players');
    const link = await screen.findByRole('link', { name: /@pixelplayer/ });
    expect(link).toHaveAttribute('href', '/moderation/players/player-id');
    if (state === 'closed') {
      const badge = within(link).getByText('Closed');
      expect(badge).toHaveClass('mod-chip');
      expect(badge.closest('strong')).toHaveTextContent('@pixelplayer');
      expect(badge).toHaveClass('closed');
    } else expect(within(link).queryByText('Closed')).not.toBeInTheDocument();
    fireEvent.click(link);
    expect(await screen.findByRole('button', { name: 'Issue sanction' })).toBeInTheDocument();
  },
);

it('shows pending appeals without inventing a cooldown date', async () => {
  notice.kind = 'suspension';
  notice.appeal = {
    eligible: false,
    detail: 'An appeal of this type is already pending.',
    available_at: null,
  };
  page('/account-notices');
  await screen.findByText('An appeal of this type is already pending.');
  expect(screen.queryByText(/Next eligibility:/)).not.toBeInTheDocument();
});

it('links settings to notices without duplicating the full interface', async () => {
  page('/settings/account');
  expect(await screen.findByRole('link', { name: 'View account notices →' })).toHaveAttribute(
    'href',
    '/account-notices',
  );
  expect(screen.queryByRole('heading', { name: 'Active sanctions' })).not.toBeInTheDocument();
  expect(seen.some(([path]) => path === '/api/moderation/notices/')).toBe(false);
});

it.each([false, true])(
  'denies notices access without a normal session (closed: %s)',
  async (closed) => {
    current = {
      user: null,
      restrictions: null,
      account_closed: closed,
      closure_message: 'Your account has been closed.',
    };
    page('/account-notices');
    await screen.findByText('Make yourself at home');
    if (closed)
      expect(screen.getByRole('alert')).toHaveTextContent('Your account has been closed.');
    expect(screen.queryByLabelText('Password', { selector: 'input' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Username', { selector: 'input' })).not.toBeInTheDocument();
    expect(seen.some(([path]) => path === '/api/moderation/notices/')).toBe(false);
  },
);

it.each(['', '2020-01-01T12:30'])(
  'rejects a missing or past fixed expiry before sending a mutation: %s',
  async (value) => {
    page('/moderation/players/player-id');
    await userEvent.click(await screen.findByRole('button', { name: 'Issue sanction' }));
    const dialog = within(screen.getByRole('dialog'));
    await userEvent.click(dialog.getByRole('radio', { name: 'suspension' }));
    await userEvent.selectOptions(dialog.getByRole('combobox', { name: 'Duration' }), 'fixed');
    fireEvent.change(dialog.getByLabelText(/Expires at/), { target: { value } });
    // Exercise the handler even if browser-native validation is bypassed.
    fireEvent.submit(dialog.getByRole('button', { name: 'Issue sanction' }).closest('form')!);
    expect(await dialog.findByRole('alert')).toHaveTextContent(
      'Choose an expiration date in the future.',
    );
    expect(
      seen.some(
        ([path, options]) => path.endsWith('/player-id/sanctions/') && options?.method === 'POST',
      ),
    ).toBe(false);
  },
);

it.each([false, true])(
  'hides self-sanction actions for staff (administrator=%s)',
  async (administrator) => {
    current.user = { ...moderator, id: player.id, administrator };
    detail = {
      ...detail,
      player: { ...player, protected: true, moderator: true, can_remove_moderator: false },
    };
    page('/moderation/players/player-id');
    await screen.findByText('You cannot issue or replace sanctions on your own account.');
    expect(screen.queryByRole('button', { name: 'Issue sanction' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Replace sanction' })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Remove moderator access' }),
    ).not.toBeInTheDocument();
    if (administrator)
      expect(screen.getByRole('button', { name: 'Edit player names' })).toBeEnabled();
  },
);

it('does not offer moderator removal on another administrator profile', async () => {
  current.user = { ...moderator, administrator: true };
  detail = {
    ...detail,
    player: { ...player, protected: true, moderator: true, can_remove_moderator: false },
  };
  page('/moderation/players/player-id');
  await screen.findByRole('heading', { name: '@pixelplayer' });
  expect(screen.queryByRole('button', { name: 'Remove moderator access' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Issue sanction' })).toBeEnabled();
});

it('offers moderator removal for an eligible native moderator', async () => {
  current.user = { ...moderator, administrator: true };
  detail = {
    ...detail,
    player: { ...player, protected: true, moderator: true, can_remove_moderator: true },
  };
  page('/moderation/players/player-id');
  expect(await screen.findByRole('button', { name: 'Remove moderator access' })).toBeEnabled();
});
