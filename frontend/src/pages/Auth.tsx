import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { api, ApiError, type ClosureDetails } from '../api';
import { useAuth } from '../auth/context';
import { PageHeading, StatusMessage } from '../components/ui';
import { UsernameRequirements } from '../components/UsernameRequirements';
import { Dialog } from '../moderation/components';
import { noticeDate } from '../components/notices';

export function AuthPage({ register = false }: { register?: boolean }) {
  const { user, refresh, loading, dismissClosure } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [closure, setClosure] = useState<ClosureDetails | null>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  if (loading) return <StatusMessage>Checking your session…</StatusMessage>;
  if (user) return <Navigate to="/profile" replace />;
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (request.current) return;
    setError('');
    dismissClosure?.();
    setClosure(null);
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    if (register && data.password !== data.password_confirm) {
      setError('Passwords do not match.');
      return;
    }
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    try {
      await api(`/api/auth/${register ? 'register' : 'login'}/`, {
        method: 'POST',
        body: JSON.stringify(data),
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      form.reset();
      await refresh();
      if (!controller.signal.aborted) navigate('/profile');
    } catch (error) {
      if (controller.signal.aborted) return;
      form.querySelectorAll<HTMLInputElement>('input[type="password"]').forEach((input) => {
        input.value = '';
      });
      if (
        !register &&
        error instanceof ApiError &&
        error.code === 'account_closed' &&
        error.closure
      )
        setClosure(error.closure);
      else setError(error instanceof Error ? error.message : 'Unable to sign in.');
    } finally {
      if (!controller.signal.aborted) {
        request.current = null;
        setPending(false);
      }
    }
  };
  return (
    <div className="form-page">
      <PageHeading
        eyebrow="YOUR NEXT PERSPECTIVE"
        title={register ? 'Join the picture.' : 'Welcome back.'}
      >
        {register
          ? 'A place for your profile, contributions, and future ranked duels.'
          : 'Sign in to your Pixelguessr account.'}
      </PageHeading>
      <form className="panel form-stack" onSubmit={(event) => void submit(event)}>
        <label>
          Username
          <input
            name="username"
            autoComplete="username"
            maxLength={150}
            required
            aria-describedby={register ? 'registration-username-rules' : undefined}
          />
        </label>
        {register && <UsernameRequirements id="registration-username-rules" />}
        {register && (
          <>
            <label>
              Email
              <input type="email" name="email" autoComplete="email" required />
            </label>
            <label>
              Display name <span className="muted">(optional)</span>
              <input name="display_name" autoComplete="nickname" maxLength={40} />
            </label>
          </>
        )}
        <label>
          Password
          <input
            type="password"
            name="password"
            autoComplete={register ? 'new-password' : 'current-password'}
            minLength={register ? 10 : undefined}
            maxLength={128}
            required
          />
        </label>
        {register && (
          <label>
            Confirm password
            <input
              type="password"
              name="password_confirm"
              autoComplete="new-password"
              minLength={10}
              maxLength={128}
              required
            />
          </label>
        )}
        {register && (
          <p className="field-help">
            Use at least 10 characters. Avoid common passwords and personal details.
          </p>
        )}
        {error && <StatusMessage error>{error}</StatusMessage>}
        <button className="button" disabled={pending}>
          {pending ? 'Please wait…' : register ? 'Create account' : 'Sign in'}
          <span aria-hidden="true">↗</span>
        </button>
        <p className="form-footer">
          {register ? 'Already part of the picture? ' : 'New here? '}
          <Link to={register ? '/login' : '/register'}>
            {register ? 'Sign in' : 'Create an account'}
          </Link>
        </p>
      </form>
      {closure && (
        <Dialog title="Account closed" close={() => setClosure(null)}>
          <div className="closure-login-content">
            <p>This account has been closed and can no longer be used to sign in.</p>
            <dl className="closure-login-details">
              <div>
                <dt>Reason</dt>
                <dd>{closure.reason || 'No reason provided.'}</dd>
              </div>
              <div>
                <dt>Issued</dt>
                <dd>
                  <time dateTime={closure.issued_at}>{noticeDate(closure.issued_at)}</time>
                </dd>
              </div>
            </dl>
            <p className="muted">
              If you believe this closure was made in error, you may contact support.
            </p>
            <button className="button secondary" type="button" onClick={() => setClosure(null)}>
              Close
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
