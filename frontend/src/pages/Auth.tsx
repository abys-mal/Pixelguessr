import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../auth/context';
import { PageHeading, StatusMessage } from '../components/ui';

export function AuthPage({ register = false }: { register?: boolean }) {
  const { user, refresh, loading } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  if (loading) return <StatusMessage>Checking your session…</StatusMessage>;
  if (user) return <Navigate to="/profile" replace />;
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setPending(true);
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api(`/api/auth/${register ? 'register' : 'login'}/`, {
        method: 'POST',
        body: JSON.stringify(data),
      });
      await refresh();
      navigate('/profile');
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Unable to sign in.');
    } finally {
      setPending(false);
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
          <input name="username" autoComplete="username" maxLength={150} required />
        </label>
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
    </div>
  );
}
