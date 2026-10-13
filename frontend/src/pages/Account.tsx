import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { useParams } from 'react-router-dom';
import { AccountSecurity } from './AccountSecurity';
import { RankedProfile } from './RankedPublic';
import { api } from '../api';
import type { Page } from '../api';
import { useAuth } from '../auth/context';
import { Badge, PageHeading, SignInPrompt, StatusMessage } from '../components/ui';

interface Notice {
  id: string;
  kind: string;
  reason: string;
  expires_at: string | null;
  acknowledged_at: string | null;
}

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
  const { user, loading, signOut, refresh } = useAuth();
  const [notices, setNotices] = useState<Notice[]>([]);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  useEffect(() => {
    if (user)
      void api<Page<Notice>>('/api/moderation/sanctions/')
        .then((page) => setNotices(page.results))
        .catch((error: Error) => setError(error.message));
  }, [user]);
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
  const acknowledge = async (id: string) => {
    setPending(true);
    setError('');
    try {
      const notice = await api<Notice>(`/api/moderation/sanctions/${id}/acknowledge/`, {
        method: 'POST',
      });
      setNotices((items) => items.map((item) => (item.id === id ? notice : item)));
      await refresh();
      setMessage('Warning acknowledged.');
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
        <section className="panel">
          <h2>Account notices</h2>
          {notices.length === 0 && <p className="muted">No active account notices.</p>}
          {notices.map((notice) => (
            <article className="notice" key={notice.id}>
              <Badge>{notice.kind}</Badge>
              <p>{notice.reason}</p>
              {notice.expires_at && (
                <p className="field-help">
                  Expires {new Date(notice.expires_at).toLocaleDateString()}
                </p>
              )}
              {notice.kind === 'warning' && !notice.acknowledged_at && (
                <button
                  className="button secondary"
                  disabled={pending}
                  onClick={() => void acknowledge(notice.id)}
                >
                  Acknowledge warning
                </button>
              )}
              {notice.acknowledged_at && <p className="field-help">Acknowledged</p>}
            </article>
          ))}
          <button
            className="button secondary"
            disabled={pending}
            onClick={async () => {
              setPending(true);
              try {
                await signOut();
              } catch (error) {
                setError((error as Error).message);
              } finally {
                setPending(false);
              }
            }}
          >
            Sign out
          </button>
        </section>
      </div>
      {error && <StatusMessage error>{error}</StatusMessage>}
      {message && <StatusMessage>{message}</StatusMessage>}
    </>
  );
}
