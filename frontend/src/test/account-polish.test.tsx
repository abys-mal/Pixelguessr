import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api';
import { AuthContext, type AuthState } from '../auth/context';
import { AuthPage } from '../pages/Auth';
import { ReportPlayer } from '../components/ReportPlayer';
import { GameplayPreview } from '../administration/GameplayPreview';
import { noticeDate } from '../components/notices';

vi.mock('../api', async (original) => ({ ...(await original<object>()), api: vi.fn() }));
const auth: AuthState = {
  user: null,
  restrictions: null,
  loading: false,
  error: '',
  refresh: vi.fn(),
  signOut: vi.fn(),
};
beforeEach(() => {
  vi.mocked(api).mockReset().mockResolvedValue({});
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute('open', '');
    this.querySelector<HTMLElement>('button')?.focus();
  });
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.removeAttribute('open');
  });
});
afterEach(() => vi.useRealTimers());
function login() {
  render(
    <MemoryRouter>
      <AuthContext.Provider value={auth}>
        <AuthPage />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'closed-player' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct-password' } });
  const button = screen.getByRole('button', { name: 'Sign in' });
  button.focus();
  fireEvent.submit(button.closest('form')!);
  return button;
}
it.each(['Closure reason visible to player.', ''])(
  'shows only verified closure details in a dismissible modal: %s',
  async (reason) => {
    const issued_at = '2026-10-18T12:00:00Z';
    vi.mocked(api).mockRejectedValueOnce(
      new ApiError('Your account has been closed.', 400, 'account_closed', undefined, {
        reason,
        issued_at,
      }),
    );
    const opener = login();
    const dialog = await screen.findByRole('dialog', { name: 'Account closed' });
    expect(within(dialog).getByText(reason || 'No reason provided.')).toBeInTheDocument();
    expect(within(dialog).getByText(noticeDate(issued_at))).toHaveAttribute('dateTime', issued_at);
    expect(within(dialog).getByText(/may contact support/)).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toHaveValue('');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Close dialog' })).toHaveFocus();
    fireEvent.click(within(dialog).getByRole('button', { name: /^Close$/ }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(screen.getByLabelText('Username')).toHaveValue('closed-player');
  },
);
it('supports Escape dismissal and keeps incorrect credentials generic', async () => {
  vi.mocked(api).mockRejectedValueOnce(
    new ApiError('Closed', 400, 'account_closed', undefined, {
      reason: 'Public reason',
      issued_at: '2026-10-18T12:00:00Z',
    }),
  );
  login();
  fireEvent(await screen.findByRole('dialog'), new Event('cancel', { cancelable: true }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  vi.mocked(api).mockRejectedValueOnce(new ApiError('Invalid username or password.', 400));
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong-password' } });
  fireEvent.submit(screen.getByRole('button', { name: 'Sign in' }).closest('form')!);
  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password.');
  expect(screen.getByLabelText('Password')).toHaveValue('');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.queryByText('Public reason')).not.toBeInTheDocument();
});
function reportAuth(kind = ''): AuthState {
  return {
    ...auth,
    user: {
      id: 'reporter',
      username: 'reporter',
      email: '',
      display_name: '',
      rating: 1000,
      ranked_tier: null,
      ranked_matches: 0,
      ranked_wins: 0,
      ranked_losses: 0,
      title: null,
      date_joined: '',
    },
    restrictions: {
      blocked: false,
      suspension: kind === 'suspension',
      probation: kind === 'probation',
      unacknowledged_warnings: kind === 'warning' ? ['w'] : [],
    },
  };
}
it.each(['', 'warning', 'probation'])('preserves reporting for standing %s', async (kind) => {
  render(
    <AuthContext.Provider value={reportAuth(kind)}>
      <ReportPlayer id="other" username="other" />
    </AuthContext.Provider>,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Report' }));
  const dialog = within(screen.getByRole('dialog', { name: 'Report @other' }));
  fireEvent.change(dialog.getByLabelText('Reason for reporting'), {
    target: { value: 'A relevant report.' },
  });
  fireEvent.submit(dialog.getByRole('button', { name: 'Submit Report' }).closest('form')!);
  expect(await screen.findByText(/Report submitted/)).toBeInTheDocument();
  expect(api).toHaveBeenCalledTimes(1);
});
it('disables report access during suspension and restores it without reopening an old dialog', () => {
  const content = (kind: string) => (
    <AuthContext.Provider value={reportAuth(kind)}>
      <ReportPlayer id="other" username="other" />
    </AuthContext.Provider>
  );
  const view = render(content(''));
  fireEvent.click(screen.getByRole('button', { name: 'Report' }));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  view.rerender(content('suspension'));
  const button = screen.getByRole('button', { name: 'Report' });
  expect(button).toBeDisabled();
  expect(button).toHaveAccessibleDescription(
    'Reporting is unavailable while your account is suspended.',
  );
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  expect(screen.getByRole('tooltip', { hidden: true })).not.toBeVisible();
  const trigger = screen.getByRole('group', { name: 'Report unavailable' });
  vi.spyOn(document.documentElement, 'clientWidth', 'get').mockReturnValue(375);
  vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue(new DOMRect(230, 0, 110, 44));
  expect(trigger).toHaveAttribute('tabindex', '0');
  fireEvent.mouseEnter(trigger);
  expect(screen.getByRole('tooltip')).toBeVisible();
  const tooltipLeft = 230 + Number.parseFloat(screen.getByRole('tooltip').style.left);
  expect(tooltipLeft).toBeGreaterThanOrEqual(12);
  expect(tooltipLeft + 260).toBeLessThanOrEqual(375 - 12);
  expect(button).toBeDisabled();
  fireEvent.mouseLeave(trigger);
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  fireEvent.focus(trigger);
  expect(screen.getByRole('tooltip')).toBeVisible();
  fireEvent.keyDown(trigger, { key: 'Escape' });
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  fireEvent.focus(trigger);
  fireEvent.blur(trigger);
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  fireEvent.click(button);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();
  view.rerender(content(''));
  expect(screen.getByRole('button', { name: 'Report' })).toBeEnabled();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Report' }));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});
it('keeps one reveal run stable, completes at the chosen duration, and restarts with a fresh order', () => {
  vi.useFakeTimers();
  const view = render(<GameplayPreview url="/preview/" />);
  const original = screen.getByRole('img').getAttribute('src');
  fireEvent.change(screen.getByRole('slider'), { target: { value: '400' } });
  expect(screen.getByRole('img').getAttribute('src')?.split('&run=')[1]).toBe(
    original?.split('&run=')[1],
  );
  fireEvent.change(screen.getByLabelText('Preview duration'), { target: { value: '15' } });
  fireEvent.click(screen.getByRole('button', { name: 'Restart preview' }));
  const run = screen.getByRole('img').getAttribute('src')?.split('&run=')[1];
  expect(run).not.toBe(original?.split('&run=')[1]);
  expect(screen.getByRole('slider')).toHaveValue('0');
  act(() => vi.advanceTimersByTime(7500));
  expect(screen.getByRole('slider')).toHaveValue('200');
  expect(screen.getByRole('img').getAttribute('src')).toBe(`/preview/?reveal=200&run=${run}`);
  act(() => vi.advanceTimersByTime(7250));
  expect(Number((screen.getByRole('slider') as HTMLInputElement).value)).toBeLessThan(400);
  act(() => vi.advanceTimersByTime(250));
  expect(screen.getByRole('img', { name: '400 of 400 tiles revealed' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Restart preview' }));
  expect(screen.getByRole('slider')).toHaveValue('0');
  expect(screen.getByRole('img').getAttribute('src')?.split('&run=')[1]).not.toBe(run);
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
});
