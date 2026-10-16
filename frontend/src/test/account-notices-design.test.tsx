import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { api, type Session, type User } from '../api';
import { AuthContext } from '../auth/context';
import {
  noticeDate,
  noticeTime,
  type AccountNoticesData,
  type AccountSanction,
} from '../components/notices';

vi.mock('../api', async (original) => ({ ...(await original<object>()), api: vi.fn() }));
const user: User = {
  id: 'player',
  username: 'player',
  display_name: '',
  email: 'private@example.test',
  rating: 1000,
  ranked_tier: null,
  ranked_matches: 0,
  ranked_wins: 0,
  ranked_losses: 0,
  title: null,
  date_joined: '2026-01-01T12:00:00Z',
};
let session: Session;
let data: AccountNoticesData;
const refresh = vi.fn<() => Promise<void>>();
function sanction(
  kind: string,
  id = kind,
  overrides: Partial<AccountSanction> = {},
): AccountSanction {
  return {
    id,
    kind,
    active: true,
    reason: `Public ${id} reason`,
    starts_at: '2026-10-15T12:00:00Z',
    expires_at: null,
    revoked_at: null,
    acknowledged_at: null,
    appeal: { eligible: true, detail: 'You can appeal this sanction.', available_at: null },
    ...overrides,
  };
}
function setStatus(
  kind: 'warning' | 'probation' | 'suspension' | null,
  expires: string | null = null,
) {
  session.restrictions = {
    blocked: false,
    suspension: kind === 'suspension',
    probation: kind === 'probation',
    unacknowledged_warnings: kind === 'warning' ? ['warning'] : [],
    notice: kind
      ? { kind, message: 'Server-selected current restriction.', expires_at: expires }
      : null,
  };
}
function page(path = '/account-notices') {
  const tree = () => (
    <MemoryRouter initialEntries={[path]}>
      <AuthContext.Provider
        value={{ ...session, loading: false, error: '', refresh, signOut: vi.fn() }}
      >
        <App />
      </AuthContext.Provider>
    </MemoryRouter>
  );
  const view = render(tree());
  return { ...view, update: () => view.rerender(tree()) };
}
beforeEach(() => {
  session = { user, restrictions: null };
  setStatus(null);
  data = { sanctions: [], appeals: [] };
  refresh.mockReset().mockResolvedValue(undefined);
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path) => {
      if (path === '/api/moderation/notices/') return structuredClone(data);
      if (path === '/api/auth/settings/')
        return {
          username: 'player',
          email: user.email,
          username_change_available: true,
          username_change_available_at: '2026-01-01T12:00:00Z',
        };
      if (path.endsWith('/acknowledge/')) {
        data.sanctions[0].acknowledged_at = '2026-10-15T12:05:00Z';
        setStatus(null);
        return {};
      }
      return {};
    });
});

it('shows the server-selected most severe sanction and sorts simultaneous active cards by severity and newest date', async () => {
  setStatus('suspension');
  data.sanctions = [
    sanction('warning', 'old-warning', { starts_at: '2026-10-01T12:00:00Z' }),
    sanction('probation'),
    sanction('warning', 'new-warning'),
    sanction('suspension'),
  ];
  page();
  const status = screen.getByRole('region', { name: 'Current account status' });
  expect(status).toHaveClass('tone-suspension');
  expect(within(status).getByRole('heading', { name: 'Suspended' })).toBeInTheDocument();
  await within(status).findByText(/3 additional active sanctions/);
  const active = await screen.findByRole('region', { name: /^Active sanctions/ });
  const cards = within(active).getAllByRole('article');
  expect(cards.map((card) => within(card).getByRole('heading').textContent)).toEqual([
    'Suspension',
    'Probation',
    'Warning',
    'Warning',
  ]);
  expect(cards[2]).toHaveTextContent('Public new-warning reason');
  expect(cards[3]).toHaveTextContent('Public old-warning reason');
  expect(cards[0]).toHaveClass('tone-suspension');
  expect(cards[1]).toHaveClass('tone-probation');
  expect(cards[2]).toHaveClass('tone-warning');
  cards.forEach((card) => expect(within(card).getByText('Active')).toBeVisible());
});

it.each([
  ['suspension', 'Suspended'],
  ['probation', 'On probation'],
  ['warning', '1 warning needs acknowledgment'],
] as const)(
  'renders the %s settings summary without loading or embedding full notices',
  async (kind, title) => {
    const expiry = '2027-02-01T12:00:00Z';
    setStatus(kind, expiry);
    page('/settings/account');
    const card = screen.getByRole('region', { name: 'Account notices summary' });
    expect(card).toHaveClass(`tone-${kind}`);
    expect(card).toHaveTextContent(title);
    expect(card).toHaveTextContent(noticeDate(expiry));
    expect(within(card).getByRole('link', { name: 'View account notices →' })).toHaveAttribute(
      'href',
      '/account-notices',
    );
    await screen.findByRole('button', { name: 'Change Email' });
    expect(vi.mocked(api).mock.calls.some(([path]) => path === '/api/moderation/notices/')).toBe(
      false,
    );
    expect(screen.queryByRole('heading', { name: /^Active sanctions/ })).not.toBeInTheDocument();
  },
);

it('shows good standing and quiet empty states, including an acknowledged active warning', async () => {
  data.sanctions = [
    sanction('warning', 'acknowledged', { acknowledged_at: '2026-10-15T12:01:00Z' }),
  ];
  page();
  const status = screen.getByRole('region', { name: 'Current account status' });
  expect(status).toHaveClass('tone-good');
  expect(status).toHaveTextContent('Your account is in good standing.');
  expect(await screen.findByText('Acknowledged', { exact: true })).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Acknowledge warning' })).not.toBeInTheDocument();
  expect(screen.getByText('No historical sanctions.')).toBeInTheDocument();
  expect(screen.getByText('No appeals submitted.')).toBeInTheDocument();
});

it('has a compact good-standing settings card and one working notices link', async () => {
  page('/settings/account');
  const card = screen.getByRole('region', { name: 'Account notices summary' });
  expect(card).toHaveClass('tone-good');
  expect(card).toHaveTextContent('No active restrictions require your attention.');
  expect(screen.getAllByRole('link', { name: 'View account notices →' })).toHaveLength(1);
  await userEvent.click(within(card).getByRole('link', { name: 'View account notices →' }));
  await screen.findByRole('heading', { name: 'Account notices', level: 1 });
  expect(await screen.findByText('No active sanctions.')).toBeInTheDocument();
});

it.each(['/settings/account', '/account-notices'])(
  'synchronizes %s with authoritative issued, reversed and expired account status',
  async (path) => {
    const view = page(path);
    const name =
      path === '/settings/account' ? 'Account notices summary' : 'Current account status';
    for (const kind of [
      'warning',
      'probation',
      'suspension',
      'probation',
      'warning',
      null,
    ] as const) {
      setStatus(kind);
      data.sanctions = kind ? [sanction(kind)] : [];
      view.update();
      const status = screen.getByRole('region', { name });
      expect(status).toHaveClass(`tone-${kind ?? 'good'}`);
      if (path === '/account-notices')
        await waitFor(() =>
          expect(
            vi.mocked(api).mock.calls.filter(([route]) => route === '/api/moderation/notices/')
              .length,
          ).toBeGreaterThan(0),
        );
    }
  },
);

it('acknowledges a warning and refreshes both the status and card actions', async () => {
  setStatus('warning');
  data.sanctions = [sanction('warning')];
  const view = page();
  refresh.mockImplementation(async () => view.update());
  await userEvent.click(await screen.findByRole('button', { name: 'Acknowledge warning' }));
  await screen.findByText('Warning acknowledged.');
  expect(screen.getByRole('region', { name: 'Current account status' })).toHaveClass('tone-good');
  expect(await screen.findByText('Acknowledged', { exact: true })).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Acknowledge warning' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Appeal this sanction' })).toBeVisible();
});

it('keeps eligibility and the exact backend cooldown date visible outside expandable history', async () => {
  setStatus('suspension');
  const until = '2027-01-13T12:33:00Z';
  data.sanctions = [
    sanction('suspension', 'suspension', {
      appeal: {
        eligible: false,
        detail: 'The appeal cooldown has not ended since the last upheld decision.',
        available_at: until,
      },
    }),
  ];
  page();
  const active = await screen.findByRole('region', { name: /^Active sanctions/ });
  expect(within(active).getByText(noticeTime(until))).toBeVisible();
  expect(within(active).getByText(/last upheld decision/)).toBeVisible();
  expect(
    within(active).queryByRole('button', { name: 'Appeal this sanction' }),
  ).not.toBeInTheDocument();
});

it('uses neutral historical sanctions, blue pending appeals and readable decisions with expandable details', async () => {
  data.sanctions = [
    sanction('suspension', 'old', { active: false, revoked_at: '2026-10-15T12:01:00Z' }),
  ];
  data.appeals = ['pending', 'upheld', 'reversed', 'sanction_changed'].map((status) => ({
    id: status,
    kind: 'suspension',
    status,
    explanation: `Full ${status} explanation`,
    created_at: '2026-10-15T12:00:00Z',
    resolved_at: status === 'pending' ? null : '2026-10-15T12:01:00Z',
  }));
  page();
  const history = await screen.findByRole('region', { name: /^Sanction history/ });
  const record = within(history).getByText('Suspension').closest('details')!;
  expect(record).not.toHaveClass('tone-suspension');
  expect(within(record).getByText('Reversed')).toHaveClass('neutral');
  const appeals = screen.getByRole('region', { name: /^Appeal history/ });
  const pending = within(appeals).getByText('Pending').closest('details')!;
  expect(pending).toHaveClass('tone-pending');
  expect(within(pending).getByText('Full pending explanation')).not.toBeVisible();
  await userEvent.click(pending.querySelector('summary')!);
  expect(within(pending).getByText('Full pending explanation')).toBeVisible();
  expect(within(appeals).getByText('Upheld')).toBeVisible();
  expect(within(appeals).getByText('Reversed')).toBeVisible();
  expect(within(appeals).getByText('Sanction changed')).toBeVisible();
});

it('preserves full lengthy public reasons while hiding private fields', async () => {
  const reason = 'A detailed public reason. '.repeat(30);
  data.sanctions = [
    Object.assign(sanction('warning', 'long', { reason }), {
      internal_note: 'PRIVATE-MODERATOR-NOTE',
    }),
  ];
  page();
  const full = await screen.findByText(reason.trim());
  expect(full).not.toBeVisible();
  await userEvent.click(screen.getByText(/Read full reason/).closest('summary')!);
  expect(full).toBeVisible();
  expect(screen.queryByText('PRIVATE-MODERATOR-NOTE')).not.toBeInTheDocument();
});

it('preserves notice loading, error and retry states', async () => {
  let reject!: (reason: Error) => void;
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation((path, options) =>
    path === '/api/moderation/notices/'
      ? new Promise((_, fail) => {
          reject = fail;
        })
      : original(path, options),
  );
  page();
  expect(screen.getByText('Loading notices…')).toBeVisible();
  reject(new Error('Notices are temporarily unavailable.'));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Notices are temporarily unavailable.',
  );
  vi.mocked(api).mockImplementation(original);
  await userEvent.click(screen.getByRole('button', { name: 'Retry notices' }));
  await screen.findByText('No active sanctions.');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
