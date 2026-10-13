import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError, type User } from '../api';
import { useAuth } from '../auth/context';
import { StatusMessage } from '../components/ui';
import { UsernameRequirements } from '../components/UsernameRequirements';

type Change = 'username' | 'email' | 'password';
export interface AccountSettings {
  username: string;
  email: string;
  username_change_available: boolean;
  username_change_available_at: string;
}
const titles: Record<Change, string> = {
  username: 'Username',
  email: 'Email',
  password: 'Password',
};
const messages: Record<Change, string> = {
  username: 'Your username has been updated.',
  email: 'Your email address has been updated.',
  password: 'Your password has been changed successfully.',
};

export function AccountSecurity({ user }: { user: User }) {
  const { refresh } = useAuth();
  const [settings, setSettings] = useState<AccountSettings | null>(null);
  const [editing, setEditing] = useState<Change | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState(false);
  const [reload, setReload] = useState(0);
  const request = useRef<AbortController | null>(null);
  const focusAfter = useRef<Change | null>(null);
  const triggers = useRef<Partial<Record<Change, HTMLButtonElement | null>>>({});
  const headings = useRef<Partial<Record<Change, HTMLHeadingElement | null>>>({});
  useEffect(() => {
    if (editing || pending || !focusAfter.current) return;
    const operation = focusAfter.current;
    const button = triggers.current[operation];
    if (button && !button.disabled) button.focus({ preventScroll: true });
    else headings.current[operation]?.focus({ preventScroll: true });
    focusAfter.current = null;
  }, [editing, pending]);
  useEffect(() => {
    const controller = new AbortController();
    void api<AccountSettings>('/api/auth/settings/', { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) {
          setSettings(value);
          setError('');
        }
      })
      .catch(async (err: Error) => {
        if (!controller.signal.aborted) {
          setError(err.message);
          if (err instanceof ApiError && [401, 403].includes(err.status)) await refresh();
        }
      });
    return () => {
      controller.abort();
      request.current?.abort();
    };
  }, [user.id, reload, refresh]);
  const close = () => {
    setEditing(null);
    setError('');
  };
  const submit = async (event: FormEvent<HTMLFormElement>, operation: Change) => {
    event.preventDefault();
    if (request.current) return;
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    setError('');
    setMessage('');
    if (operation === 'password' && data.new_password !== data.password_confirm) {
      setError('New passwords do not match.');
      return;
    }
    if (
      operation === 'username' &&
      String(data.new_username).toLowerCase() === settings?.username.toLowerCase()
    ) {
      setError('Choose a different username.');
      return;
    }
    if (
      operation === 'email' &&
      String(data.new_email).trim().toLowerCase() === settings?.email.toLowerCase()
    ) {
      setError('Choose a different email address.');
      return;
    }
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    try {
      const result = await api<{ settings: AccountSettings }>(`/api/auth/change-${operation}/`, {
        method: 'POST',
        body: JSON.stringify(data),
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      form.reset();
      setSettings(result.settings);
      setEditing(null);
      setMessage(messages[operation]);
      await refresh();
    } catch (err) {
      if (controller.signal.aborted) return;
      // Passwords stay in the form only, and are cleared on every server response.
      form.querySelectorAll<HTMLInputElement>('input[type="password"]').forEach((input) => {
        input.value = '';
      });
      setError((err as Error).message);
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) await refresh();
    } finally {
      if (!controller.signal.aborted) {
        request.current = null;
        setPending(false);
      }
    }
  };
  if (!settings)
    return (
      <section className="panel account-security-loading">
        <StatusMessage error={!!error}>{error || 'Loading sign-in settings…'}</StatusMessage>
        {error && (
          <button className="button secondary" onClick={() => setReload((value) => value + 1)}>
            Retry account settings
          </button>
        )}
      </section>
    );
  const availableAt = new Intl.DateTimeFormat(undefined, {
    dateStyle: 'long',
    timeStyle: 'short',
    timeZone: 'UTC',
  }).format(new Date(settings.username_change_available_at));
  return (
    <section aria-label="Sign-in settings" className="account-security">
      {(Object.keys(titles) as Change[]).map((operation) => (
        <section
          className="panel account-security-card"
          key={operation}
          aria-labelledby={`account-${operation}-title`}
        >
          <h2
            tabIndex={-1}
            ref={(node) => {
              headings.current[operation] = node;
            }}
            id={`account-${operation}-title`}
          >
            {titles[operation]}
          </h2>
          {operation === 'username' && (
            <>
              <p className="account-value">@{settings.username}</p>
              <p className="field-help" id="username-availability">
                {settings.username_change_available ? (
                  'A username change is available. Your next change starts a new 90-day cooldown.'
                ) : (
                  <>
                    Next change available on{' '}
                    <time dateTime={settings.username_change_available_at}>{availableAt} UTC</time>.
                    Account creation starts the first 90-day cooldown.
                  </>
                )}
              </p>
            </>
          )}
          {operation === 'email' && (
            <>
              <p className="account-value">{settings.email}</p>
              <p className="field-help">
                Your new address takes effect immediately after password confirmation.
              </p>
            </>
          )}
          {operation === 'password' && (
            <p className="field-help">
              Use a strong, unique password with at least 10 characters. Avoid common passwords and
              personal details.
            </p>
          )}
          {editing !== operation ? (
            <button
              ref={(node) => {
                triggers.current[operation] = node;
              }}
              className="button secondary"
              type="button"
              disabled={
                pending || (operation === 'username' && !settings.username_change_available)
              }
              aria-describedby={operation === 'username' ? 'username-availability' : undefined}
              aria-expanded={false}
              aria-controls={`account-${operation}-form`}
              onClick={() => {
                focusAfter.current = operation;
                setEditing(operation);
                setMessage('');
                setError('');
              }}
            >
              Change {titles[operation]}
            </button>
          ) : (
            <form
              id={`account-${operation}-form`}
              className="form-stack account-change-form"
              onSubmit={(event) => void submit(event, operation)}
            >
              <fieldset disabled={pending}>
                {operation === 'username' && (
                  <>
                    <label>
                      New username
                      <input
                        name="new_username"
                        aria-describedby="change-username-rules"
                        autoComplete="username"
                        maxLength={150}
                        required
                        autoFocus
                      />
                    </label>
                    <UsernameRequirements id="change-username-rules" />
                  </>
                )}
                {operation === 'email' && (
                  <label>
                    New email address
                    <input
                      type="email"
                      name="new_email"
                      autoComplete="email"
                      maxLength={254}
                      required
                      autoFocus
                    />
                  </label>
                )}
                <label>
                  Current password
                  <input
                    type="password"
                    name="current_password"
                    autoComplete="current-password"
                    maxLength={128}
                    required
                    autoFocus={operation === 'password'}
                  />
                </label>
                {operation === 'password' && (
                  <>
                    <label>
                      New password
                      <input
                        type="password"
                        name="new_password"
                        autoComplete="new-password"
                        minLength={10}
                        maxLength={128}
                        required
                      />
                    </label>
                    <label>
                      Confirm new password
                      <input
                        type="password"
                        name="password_confirm"
                        autoComplete="new-password"
                        minLength={10}
                        maxLength={128}
                        required
                      />
                    </label>
                    <p className="field-help">
                      This session stays signed in. Your other signed-in sessions will be ended.
                    </p>
                  </>
                )}
              </fieldset>
              {error && <StatusMessage error>{error}</StatusMessage>}
              <div className="account-change-actions">
                <button className="button" disabled={pending}>
                  {pending ? 'Saving…' : `Save ${operation}`}
                </button>
                <button
                  className="button secondary"
                  type="button"
                  disabled={pending}
                  onClick={close}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </section>
      ))}
      {!editing && error && <StatusMessage error>{error}</StatusMessage>}
      {message && <StatusMessage>{message}</StatusMessage>}
    </section>
  );
}
