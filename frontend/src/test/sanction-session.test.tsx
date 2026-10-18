import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { api, type Session, type User } from '../api';
import { AuthProvider } from '../auth/AuthProvider';
import { useAuth } from '../auth/context';
import { SanctionBanner } from '../components/SanctionBanner';

let receive: (session: Session) => void;
const stop = vi.fn();
vi.mock('../api', async (original) => ({ ...(await original<object>()), api: vi.fn() }));
vi.mock('../auth/live', () => ({
  connectAccount: (callback: (value: Session) => void) => {
    receive = callback;
    return stop;
  },
}));
const user: User = {
  id: 'p',
  username: 'player',
  display_name: '',
  email: 'private@example.test',
  rating: 1000,
  ranked_tier: null,
  ranked_matches: 0,
  ranked_wins: 0,
  ranked_losses: 0,
  title: null,
  date_joined: '2026-01-01T00:00:00Z',
};
const clean: Session = {
  user,
  restrictions: {
    blocked: false,
    suspension: false,
    probation: false,
    unacknowledged_warnings: [],
    notice: null,
  },
};
const notice = (kind: 'warning' | 'probation' | 'suspension'): Session => ({
  user,
  restrictions: {
    blocked: false,
    suspension: kind === 'suspension',
    probation: kind === 'probation',
    unacknowledged_warnings: kind === 'warning' ? ['w'] : [],
    notice: {
      kind,
      message: `${kind} public restriction explanation`,
      expires_at: '2027-01-01T00:00:00Z',
    },
  },
});

beforeEach(() => {
  receive = undefined!;
  stop.mockReset();
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path) => {
      if (path === '/api/auth/me/') return clean;
      if (path === '/api/auth/settings/')
        return {
          username: 'player',
          email: user.email,
          username_change_available: true,
          username_change_available_at: '2026-01-01T00:00:00Z',
        };
      if (path === '/api/moderation/notices/') return { sanctions: [], appeals: [] };
      return {};
    });
});

function Status() {
  const { user } = useAuth();
  return (
    <>
      <p>Signed in: {user?.username ?? 'no'}</p>
      <SanctionBanner />
    </>
  );
}
function page(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

it.each(['warning', 'probation', 'suspension'] as const)(
  'updates the homepage %s banner without losing the session',
  async (kind) => {
    page();
    await waitFor(() => expect(receive).toBeTypeOf('function'));
    act(() => receive(notice(kind)));
    const banner = await screen.findByRole('status');
    expect(banner).toHaveTextContent(`${kind} public restriction explanation`);
    if (kind === 'suspension') {
      expect(screen.getByRole('heading', { name: /^Suspension$/ })).toBeInTheDocument();
      expect(screen.queryByText('Multiplayer suspension')).not.toBeInTheDocument();
    }
    expect(banner).toHaveTextContent('Expires');
    expect(screen.getByRole('link', { name: 'View details →' })).toHaveAttribute(
      'href',
      '/account-notices',
    );
    expect(screen.getByRole('link', { name: /^player/ })).toHaveAttribute('href', '/profile');
    act(() => receive(clean));
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  },
);

it.each(['probation', 'suspension'] as const)(
  'keeps the normal notices page accessible during %s',
  async (kind) => {
    page('/account-notices');
    await screen.findByRole('heading', { name: 'Account notices', level: 1 });
    await waitFor(() => expect(receive).toBeTypeOf('function'));
    act(() => receive(notice(kind)));
    expect(screen.getByRole('heading', { name: 'Account notices', level: 1 })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: /^Active sanctions/ })).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Username' })).not.toBeInTheDocument();
  },
);

it('replaces signed-in access with a clear closure message from a live event', async () => {
  page();
  await screen.findByRole('link', { name: /^player/ });
  await waitFor(() => expect(receive).toBeTypeOf('function'));
  act(() =>
    receive({
      user: null,
      restrictions: null,
      account_closed: true,
      closure_message: 'Your account has been closed.',
    }),
  );
  expect(await screen.findByRole('alert')).toHaveTextContent('Your account has been closed.');
  expect(screen.queryByRole('link', { name: /^player/ })).not.toBeInTheDocument();
  expect(stop).toHaveBeenCalled();
});

it.each(['dismiss', 'navigate', 'timeout'])(
  'clears the closure banner after %s and does not restore it on refresh',
  async (action) => {
    const view = page();
    await screen.findByRole('link', { name: /^player/ });
    if (action === 'timeout') vi.useFakeTimers();
    act(() => receive({ user: null, restrictions: null, account_closed: true }));
    expect(screen.getByRole('alert')).toHaveTextContent('Your account has been closed.');
    if (action === 'dismiss')
      fireEvent.click(screen.getByRole('button', { name: 'Dismiss account closure message' }));
    else if (action === 'navigate') {
      fireEvent.click(screen.getByRole('link', { name: 'About & rules' }));
      fireEvent.click(screen.getByRole('link', { name: 'Pixelguessr home' }));
    } else {
      try {
        act(() => vi.advanceTimersByTime(10000));
      } finally {
        vi.useRealTimers();
      }
    }
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    view.unmount();
    vi.mocked(api).mockResolvedValue({ user: null, restrictions: null });
    page();
    await screen.findByRole('link', { name: 'Sign in' });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  },
);

it('does not carry a closure banner into another signed-in account', async () => {
  function RefreshAccount() {
    const { refresh } = useAuth();
    return <button onClick={() => void refresh()}>Refresh session</button>;
  }
  render(
    <MemoryRouter>
      <AuthProvider>
        <App />
        <RefreshAccount />
      </AuthProvider>
    </MemoryRouter>,
  );
  await screen.findByRole('link', { name: /^player/ });
  act(() => receive({ user: null, restrictions: null, account_closed: true }));
  expect(screen.getByRole('alert')).toBeInTheDocument();
  vi.mocked(api).mockResolvedValue({ ...clean, user: { ...user, id: 'other', username: 'other' } });
  fireEvent.click(screen.getByRole('button', { name: 'Refresh session' }));
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  expect(screen.getByRole('link', { name: /^other/ })).toBeInTheDocument();
});

it('ignores an old HTTP refresh when a newer account event has arrived', async () => {
  let finish!: (session: Session) => void;
  let calls = 0;
  vi.mocked(api).mockImplementation(async () => {
    if (++calls === 1) return clean;
    return new Promise<Session>((resolve) => {
      finish = resolve;
    });
  });
  const { unmount } = render(
    <MemoryRouter>
      <AuthProvider>
        <Status />
      </AuthProvider>
    </MemoryRouter>,
  );
  await screen.findByText('Signed in: player');
  await waitFor(() => expect(receive).toBeTypeOf('function'));
  fireEvent(window, new Event('focus'));
  await waitFor(() => expect(finish).toBeTypeOf('function'));
  act(() => receive(notice('suspension')));
  await act(async () => finish(clean));
  expect(screen.getByRole('status')).toHaveTextContent('suspension public restriction explanation');
  unmount();
});
