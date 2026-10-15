import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { api, ApiError, type User } from '../api';
import { AuthContext } from '../auth/context';
import { AuthProvider } from '../auth/AuthProvider';
import type { AccountSettings } from '../pages/AccountSecurity';

vi.mock('../api', async (original) => ({ ...(await original<object>()), api: vi.fn() }));
const originalUser: User = {
  id: 'user-id',
  username: 'pixelplayer',
  email: 'player@example.test',
  display_name: '',
  rating: 1400,
  ranked_tier: 'silver',
  ranked_matches: 5,
  ranked_wins: 3,
  ranked_losses: 2,
  title: null,
  date_joined: '2026-01-01T00:00:00Z',
};
let user: User;
let settings: AccountSettings;
const refresh = vi.fn<() => Promise<void>>();
const notices = { count: 0, next: null, previous: null, results: [] };
const restrictions = { blocked: false, probation: false, unacknowledged_warnings: [] };
beforeEach(() => {
  user = { ...originalUser };
  settings = {
    username: user.username,
    email: user.email,
    username_change_available: true,
    username_change_available_at: '2026-04-01T00:00:00Z',
  };
  refresh.mockReset().mockResolvedValue(undefined);
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path, options) => {
      if (path === '/api/auth/me/') return { user: { ...user }, restrictions };
      if (path === '/api/auth/settings/') return settings;
      if (path === '/api/moderation/notices/') return { sanctions: notices.results, appeals: [] };
      if (path.startsWith('/api/auth/change-')) {
        const data = JSON.parse(String(options?.body));
        if (data.new_username) {
          user.username = data.new_username;
          settings = { ...settings, username: data.new_username, username_change_available: false };
        }
        if (data.new_email) {
          user.email = data.new_email;
          settings = { ...settings, email: data.new_email };
        }
        return { settings };
      }
      return {};
    });
});
const page = (path = '/settings/account', guest = false) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthContext.Provider
        value={{
          user: guest ? null : user,
          restrictions: guest ? null : restrictions,
          loading: false,
          error: '',
          refresh,
          signOut: vi.fn(),
        }}
      >
        <App />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
const open = async (name: string) => {
  await screen.findByRole('button', { name: `Change ${name}` });
  fireEvent.click(screen.getByRole('button', { name: `Change ${name}` }));
};
const submitForm = () =>
  fireEvent.submit(screen.getByLabelText('Current password').closest('form')!);
const calls = () =>
  vi.mocked(api).mock.calls.filter(([path]) => path.startsWith('/api/auth/change-'));

it('renders existing notices/profile settings and three protected actions without password inputs', async () => {
  page();
  await screen.findByRole('button', { name: 'Change Email' });
  for (const name of ['Username', 'Email', 'Password', 'Profile details', 'Account notices'])
    expect(screen.getByRole('heading', { name })).toBeInTheDocument();
  expect(screen.queryByLabelText('Current password')).not.toBeInTheDocument();
  expect(
    screen.getByText('player@example.test', { selector: '.account-value' }),
  ).toBeInTheDocument();
  expect(screen.getByText(/A username change is available/)).toBeInTheDocument();
});

it('shows the precise UTC cooldown date and disables unavailable username changes', async () => {
  settings.username_change_available = false;
  settings.username_change_available_at = '2027-01-10T14:30:00Z';
  page();
  expect(await screen.findByRole('button', { name: 'Change Username' })).toBeDisabled();
  expect(screen.getByText(/January 10, 2027/)).toHaveAttribute('dateTime', '2027-01-10T14:30:00Z');
  expect(screen.getByText(/Account creation starts/)).toBeInTheDocument();
});

it('requires a registered session', () => {
  page('/settings/account', true);
  expect(screen.getByRole('heading', { name: 'Make yourself at home' })).toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();
});

it.each([
  ['Username', 'New username', 'PIXELPLAYER', 'Choose a different username.'],
  ['Email', 'New email address', 'PLAYER@EXAMPLE.TEST', 'Choose a different email address.'],
])('rejects unchanged %s before submission', async (name, label, value, message) => {
  page();
  await open(name);
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.change(screen.getByLabelText('Current password'), {
    target: { value: 'current-password' },
  });
  submitForm();
  expect(screen.getByRole('alert')).toHaveTextContent(message);
  expect(calls()).toHaveLength(0);
});

it('rejects mismatched new passwords and uses required password fields', async () => {
  page();
  await open('Password');
  fireEvent.change(screen.getByLabelText('Current password'), {
    target: { value: 'current-password' },
  });
  fireEvent.change(screen.getByLabelText('New password'), {
    target: { value: 'strong-new-password' },
  });
  fireEvent.change(screen.getByLabelText('Confirm new password'), {
    target: { value: 'different-password' },
  });
  submitForm();
  expect(screen.getByRole('alert')).toHaveTextContent('New passwords do not match.');
  for (const label of ['Current password', 'New password', 'Confirm new password']) {
    expect(screen.getByLabelText(label)).toHaveAttribute('type', 'password');
    expect(screen.getByLabelText(label)).toBeRequired();
  }
  expect(calls()).toHaveLength(0);
});

it.each([
  ['Username', 'New username', 'renamed', 'Your username has been updated.'],
  ['Email', 'New email address', 'new@example.test', 'Your email address has been updated.'],
])('updates %s and refreshes shared account information', async (name, label, value, message) => {
  page();
  await open(name);
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.change(screen.getByLabelText('Current password'), {
    target: { value: 'current-password' },
  });
  submitForm();
  await screen.findByText(message);
  expect(refresh).toHaveBeenCalledOnce();
  expect(
    screen.getByText(name === 'Username' ? `@${value}` : value, { selector: '.account-value' }),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText('Current password')).not.toBeInTheDocument();
  const data = JSON.parse(String(calls()[0][1]?.body));
  expect(data).toEqual({
    current_password: 'current-password',
    [name === 'Username' ? 'new_username' : 'new_email']: value,
  });
});

it('clears all passwords after a successful password change and keeps the session', async () => {
  page();
  await open('Password');
  fireEvent.change(screen.getByLabelText('Current password'), {
    target: { value: 'current-password' },
  });
  fireEvent.change(screen.getByLabelText('New password'), {
    target: { value: 'strong-new-password' },
  });
  fireEvent.change(screen.getByLabelText('Confirm new password'), {
    target: { value: 'strong-new-password' },
  });
  submitForm();
  await screen.findByText('Your password has been changed successfully.');
  expect(refresh).toHaveBeenCalledOnce();
  await open('Password');
  for (const label of ['Current password', 'New password', 'Confirm new password'])
    expect(screen.getByLabelText(label)).toHaveValue('');
});

it('restores keyboard focus and discards passwords when cancelling an inline form', async () => {
  page();
  await open('Email');
  expect(screen.getByLabelText('New email address')).toHaveFocus();
  fireEvent.change(screen.getByLabelText('Current password'), {
    target: { value: 'secret-password' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.getByRole('button', { name: 'Change Email' })).toHaveFocus();
  await open('Email');
  expect(screen.getByLabelText('Current password')).toHaveValue('');
});

it('shows pending state and blocks duplicate submissions', async () => {
  page();
  await open('Email');
  let finish!: (value: unknown) => void;
  vi.mocked(api).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  fireEvent.change(screen.getByLabelText('New email address'), {
    target: { value: 'new@example.test' },
  });
  fireEvent.change(screen.getByLabelText('Current password'), {
    target: { value: 'secret-password' },
  });
  submitForm();
  submitForm();
  expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
  expect(screen.getByLabelText('Current password')).toBeDisabled();
  expect(calls()).toHaveLength(1);
  await act(async () => finish({ settings: { ...settings, email: 'new@example.test' } }));
  expect(screen.getByText('Your email address has been updated.')).toBeInTheDocument();
});

it('announces server validation errors and clears password inputs without dropping the intended email', async () => {
  page();
  await open('Email');
  vi.mocked(api).mockRejectedValueOnce(new ApiError('Current password is incorrect.', 400));
  fireEvent.change(screen.getByLabelText('New email address'), {
    target: { value: 'new@example.test' },
  });
  fireEvent.change(screen.getByLabelText('Current password'), {
    target: { value: 'wrong-password' },
  });
  submitForm();
  expect(await screen.findByRole('alert')).toHaveTextContent('Current password is incorrect.');
  expect(screen.getByLabelText('Current password')).toHaveValue('');
  expect(screen.getByLabelText('New email address')).toHaveValue('new@example.test');
});

it('refreshes authentication when a session expires during submission', async () => {
  page();
  await open('Email');
  vi.mocked(api).mockRejectedValueOnce(new ApiError('Sign in required.', 403));
  fireEvent.change(screen.getByLabelText('New email address'), {
    target: { value: 'new@example.test' },
  });
  fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'password' } });
  submitForm();
  await screen.findByRole('alert');
  expect(refresh).toHaveBeenCalledOnce();
});

it('aborts requests and ignores late responses after navigating away', async () => {
  page();
  await open('Email');
  let finish!: (value: unknown) => void;
  vi.mocked(api).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  fireEvent.change(screen.getByLabelText('New email address'), {
    target: { value: 'new@example.test' },
  });
  fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'password' } });
  submitForm();
  const signal = calls()[0][1]?.signal;
  fireEvent.click(screen.getByRole('link', { name: 'Play' }));
  expect(signal?.aborted).toBe(true);
  await act(async () => finish({ settings: { ...settings, email: 'new@example.test' } }));
  expect(refresh).not.toHaveBeenCalled();
  expect(screen.queryByText('Your email address has been updated.')).not.toBeInTheDocument();
});

it('updates the navigation and existing profile details through the actual AuthProvider refresh', async () => {
  render(
    <MemoryRouter initialEntries={['/settings/account']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
  await open('Username');
  fireEvent.change(screen.getByLabelText('New username'), {
    target: { value: 'new_navigation_name' },
  });
  fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'password' } });
  submitForm();
  await waitFor(() =>
    expect(screen.getByRole('link', { name: /new_navigation_name/ })).toBeInTheDocument(),
  );
  expect(screen.getByText(/@new_navigation_name · player@example.test/)).toBeInTheDocument();
});

it('registration sends confirmation and rejects a mismatch before making a request', async () => {
  page('/register', true);
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'new-user' } });
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'new@example.test' } });
  fireEvent.change(screen.getByLabelText('Password', { exact: true }), {
    target: { value: 'a-strong-new-password' },
  });
  const confirmation = screen.getByLabelText('Confirm password', { exact: true });
  expect(confirmation).toHaveAttribute('type', 'password');
  expect(confirmation).toBeRequired();
  fireEvent.change(confirmation, { target: { value: 'different-password' } });
  fireEvent.submit(confirmation.closest('form')!);
  expect(screen.getByRole('alert')).toHaveTextContent('Passwords do not match.');
  expect(api).not.toHaveBeenCalled();
  fireEvent.change(confirmation, { target: { value: 'a-strong-new-password' } });
  fireEvent.submit(confirmation.closest('form')!);
  await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
  const body = JSON.parse(String(vi.mocked(api).mock.calls[0][1]?.body));
  expect(body.password_confirm).toBe(body.password);
});

it.each(['registration', 'change'])(
  'describes the username rules accessibly in the %s form',
  async (flow) => {
    if (flow === 'registration') page('/register', true);
    else {
      page();
      await open('Username');
    }
    const input = screen.getByLabelText(flow === 'registration' ? 'Username' : 'New username');
    expect(input).toHaveAttribute('maxLength', '150');
    expect(input).toHaveAccessibleDescription(
      'Up to 150 characters. Must be unique (case-insensitive), with no whitespace. Cannot end with - or _.',
    );
  },
);

it('keeps username assignment requirements out of the existing login form', () => {
  page('/login', true);
  expect(screen.getByLabelText('Username')).not.toHaveAttribute('aria-describedby');
  expect(screen.queryByText(/Must be unique/)).not.toBeInTheDocument();
});
