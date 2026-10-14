import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../api';
import { useAuth } from '../auth/context';
import { PageHeading, StatusMessage } from '../components/ui';
import { post, label, date } from '../moderation/api';
import { useData } from '../moderation/useData';

interface Notice {
  id: string;
  kind: string;
  reason: string;
  starts_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  appeal: { eligible: boolean; detail: string; available_at: string | null };
}
interface Appeal {
  id: string;
  sanction: string;
  kind: string;
  explanation: string;
  status: string;
  created_at: string;
}
interface Notices {
  username: string;
  sanctions: Notice[];
  appeals: Appeal[];
}

export function PlayerAppeals() {
  const { user } = useAuth();
  const { data, error, reload } = useData<Notices>('/api/moderation/notices/');
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [actionError, setActionError] = useState('');
  const [appealing, setAppealing] = useState('');
  const [explanation, setExplanation] = useState('');
  const login = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    const form = new FormData(event.currentTarget);
    setPending(true);
    setActionError('');
    try {
      await post('/api/moderation/notice-login/', {
        username: form.get('username'),
        password: form.get('password'),
      });
      reload();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setPending(false);
    }
  };
  const appeal = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setActionError('');
    try {
      await post(`/api/moderation/sanctions/${appealing}/appeal/`, { explanation });
      setAppealing('');
      setExplanation('');
      setMessage('Your appeal has been submitted for review.');
      reload();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setPending(false);
    }
  };
  return (
    <>
      <PageHeading eyebrow="YOUR ACCOUNT" title="Notices & appeals">
        Review moderation notices and ask for a second look.
      </PageHeading>
      {actionError && <StatusMessage error>{actionError}</StatusMessage>}
      {message && <StatusMessage>{message}</StatusMessage>}
      {!data ? (
        error ? (
          <>
            <p className="muted">
              Verify your account to view notices. Suspended players can use this page while game
              access remains restricted.
            </p>
            <form className="panel form-stack" onSubmit={(event) => void login(event)}>
              <label>
                Username
                <input name="username" required autoComplete="username" maxLength={150} />
              </label>
              <label>
                Password
                <input
                  type="password"
                  name="password"
                  required
                  autoComplete="current-password"
                  maxLength={128}
                />
              </label>
              <button className="button" disabled={pending}>
                {pending ? 'Verifying…' : 'View my notices'}
              </button>
              <p className="field-help">
                Appeal access lasts 15 minutes and does not sign you into the game.
              </p>
              {!error.includes('credentials') && <StatusMessage error>{error}</StatusMessage>}
            </form>
          </>
        ) : (
          <StatusMessage>Loading notices…</StatusMessage>
        )
      ) : (
        <>
          <div className="appeal-page-heading">
            <h2>@{data.username}</h2>
            {!user && (
              <button
                className="button compact secondary"
                disabled={pending}
                onClick={async () => {
                  if (pending) return;
                  setPending(true);
                  setActionError('');
                  setMessage('');
                  try {
                    await api('/api/moderation/notices/', { method: 'DELETE' });
                    setAppealing('');
                    setExplanation('');
                    reload();
                  } catch (error) {
                    setActionError((error as Error).message);
                  } finally {
                    setPending(false);
                  }
                }}
              >
                End appeal access
              </button>
            )}
          </div>
          <div className="appeal-notices">
            {!data.sanctions.length && (
              <section className="panel">
                <p>No moderation notices on record.</p>
              </section>
            )}
            {data.sanctions.map((notice) => (
              <article className="panel" key={notice.id}>
                <h2>{label(notice.kind)}</h2>
                <p>{notice.reason}</p>
                <p className="field-help">
                  Issued {date(notice.starts_at)} · {date(notice.expires_at)}
                  {notice.revoked_at && ' · Reversed'}
                </p>
                <p className="field-help">
                  {notice.appeal.detail}
                  {notice.appeal.available_at &&
                    ` Next eligibility: ${date(notice.appeal.available_at)}.`}
                </p>
                {notice.appeal.eligible && appealing !== notice.id && (
                  <button
                    className="button secondary"
                    disabled={pending}
                    onClick={() => {
                      setAppealing(notice.id);
                      setExplanation('');
                      setActionError('');
                    }}
                  >
                    Appeal this sanction
                  </button>
                )}
                {appealing === notice.id && (
                  <form className="form-stack" onSubmit={(event) => void appeal(event)}>
                    <label htmlFor={`explanation-${notice.id}`}>
                      Why should this sanction be reconsidered?
                    </label>
                    <textarea
                      id={`explanation-${notice.id}`}
                      required
                      maxLength={4000}
                      rows={5}
                      value={explanation}
                      onChange={(event) => setExplanation(event.target.value)}
                    />
                    <div className="appeal-actions">
                      <button className="button" disabled={pending || !explanation.trim()}>
                        {pending ? 'Submitting…' : 'Submit appeal'}
                      </button>
                      <button
                        className="button secondary"
                        type="button"
                        disabled={pending}
                        onClick={() => setAppealing('')}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                )}
              </article>
            ))}
          </div>
          <section className="panel appeal-history">
            <h2>Appeal history</h2>
            {!data.appeals.length && <p className="muted">No appeals submitted.</p>}
            {data.appeals.map((appeal) => (
              <article className="notice" key={appeal.id}>
                <strong>
                  {label(appeal.kind)} · {label(appeal.status)}
                </strong>
                <p>{appeal.explanation}</p>
                <small>{date(appeal.created_at)}</small>
              </article>
            ))}
          </section>
        </>
      )}
    </>
  );
}
