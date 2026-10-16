import { useState } from 'react';
import type { FormEvent } from 'react';
import { useParams } from 'react-router-dom';
import { AccountSecurity } from './AccountSecurity';
import { AccountNoticeStatus } from '../components/AccountNoticeStatus';
import { RankedProfile } from './RankedPublic';
import { api } from '../api';
import { useAuth } from '../auth/context';
import { PageHeading, SignInPrompt, StatusMessage } from '../components/ui';

export function Profile() {
  const { user, loading } = useAuth();
  const { username } = useParams();
  if (username)
    return <RankedProfile key={username} username={username} own={user?.username === username} />;
  if (loading) return <StatusMessage>Loading profile…</StatusMessage>;
  if (!user) return <SignInPrompt feature="view your profile" />;
  return <RankedProfile key={user.username} username={user.username} own />;
}

export function Settings() {
  const { user, loading, refresh } = useAuth();
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  if (loading) return <StatusMessage>Loading account…</StatusMessage>;
  if (!user) return <SignInPrompt feature="manage your account" />;
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPending(true);
    setError('');
    setMessage('');
    const display_name = new FormData(event.currentTarget).get('display_name');
    try {
      await api('/api/auth/me/', { method: 'PATCH', body: JSON.stringify({ display_name }) });
      await refresh();
      setMessage('Your display name has been saved.');
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setPending(false);
    }
  };
  return (
    <>
      <PageHeading eyebrow="MAKE IT YOURS" title="Account settings">
        Manage your sign-in details, profile, and account notices.
      </PageHeading>
      <AccountSecurity user={user} />
      <div className="settings-grid">
        <form className="panel form-stack" onSubmit={(event) => void save(event)}>
          <h2>Profile details</h2>
          <p className="muted">
            @{user.username} · {user.email}
          </p>
          <label>
            Display name
            <input
              name="display_name"
              defaultValue={user.display_name}
              maxLength={40}
              autoComplete="nickname"
            />
          </label>
          <button className="button" disabled={pending}>
            {pending ? 'Please wait…' : 'Save display name'}
          </button>
        </form>
        <AccountNoticeStatus compact />
      </div>
      {error && <StatusMessage error>{error}</StatusMessage>}
      {message && <StatusMessage>{message}</StatusMessage>}
    </>
  );
}
