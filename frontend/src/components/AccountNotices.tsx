import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useLocation } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../auth/context';
import { StatusMessage } from './ui';

interface Notice {
  id: string;
  active: boolean;
  kind: string;
  reason: string;
  starts_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  acknowledged_at: string | null;
  appeal: { eligible: boolean; detail: string; available_at: string | null };
}
interface Appeal {
  id: string;
  kind: string;
  explanation: string;
  status: string;
  created_at: string;
  resolved_at: string | null;
}
interface Notices {
  sanctions: Notice[];
  appeals: Appeal[];
}
const label = (value: string) => value.replaceAll('_', ' ');
const date = (value: string) => new Date(value).toLocaleString();

export function AccountNotices() {
  const { restrictions, refresh } = useAuth();
  const { hash } = useLocation();
  const section = useRef<HTMLElement>(null);
  const [data, setData] = useState<Notices | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState(false);
  const [appealing, setAppealing] = useState('');
  const [explanation, setExplanation] = useState('');
  const [revision, setRevision] = useState(0);
  // Public restriction changes arrive over the normal account socket. History also polls
  // to receive appeal decisions that need not change the current restrictions.
  const signature = JSON.stringify(restrictions);
  const ready = Boolean(data);
  useEffect(() => {
    if (hash !== '#account-notices' || !ready) return;
    const frame = requestAnimationFrame(() => {
      section.current?.focus();
      section.current?.scrollIntoView?.({ block: 'start' });
    });
    return () => cancelAnimationFrame(frame);
  }, [hash, ready]);
  useEffect(() => {
    let live = true;
    const load = () =>
      void api<Notices>('/api/moderation/notices/')
        .then((next) => {
          if (live) {
            setData(next);
            setError('');
          }
        })
        .catch((err: Error) => {
          if (live) setError(err.message);
        });
    load();
    const timer = setInterval(load, 5000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [signature, revision]);
  const acknowledge = async (id: string) => {
    if (pending) return;
    setPending(true);
    setError('');
    setMessage('');
    try {
      await api(`/api/moderation/sanctions/${id}/acknowledge/`, { method: 'POST' });
      await refresh();
      setRevision((value) => value + 1);
      setMessage('Warning acknowledged.');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  };
  const appeal = async (event: FormEvent) => {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError('');
    setMessage('');
    try {
      await api(`/api/moderation/sanctions/${appealing}/appeal/`, {
        method: 'POST',
        body: JSON.stringify({ explanation }),
      });
      setAppealing('');
      setExplanation('');
      setRevision((value) => value + 1);
      setMessage('Your appeal has been submitted for review.');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  };
  return (
    <section className="panel account-notices" id="account-notices" ref={section} tabIndex={-1}>
      <h2>Account notices</h2>
      <p className="muted">Your sanctions, acknowledgment history, and appeals.</p>
      {error && <StatusMessage error>{error}</StatusMessage>}
      {message && <StatusMessage>{message}</StatusMessage>}
      {!data ? (
        <StatusMessage>Loading notices…</StatusMessage>
      ) : (
        <>
          <div className="account-notice-list">
            {!data.sanctions.length && <p className="muted">No account notices on record.</p>}
            {data.sanctions.map((notice) => (
              <article className="notice" key={notice.id}>
                <h3>
                  {label(notice.kind)}
                  {notice.revoked_at && <span className="muted"> · Reversed</span>}
                </h3>
                <p>{notice.reason}</p>
                <p className="field-help">
                  Issued {date(notice.starts_at)} ·{' '}
                  {notice.expires_at ? `Expires ${date(notice.expires_at)}` : 'No expiry'}
                </p>
                {notice.acknowledged_at && <p className="field-help">Acknowledged</p>}
                {notice.kind === 'warning' &&
                  !notice.acknowledged_at &&
                  !notice.revoked_at &&
                  notice.active && (
                    <button
                      className="button secondary"
                      disabled={pending}
                      onClick={() => void acknowledge(notice.id)}
                    >
                      Acknowledge warning
                    </button>
                  )}
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
                    }}
                  >
                    Appeal this sanction
                  </button>
                )}
                {appealing === notice.id && (
                  <form className="form-stack" onSubmit={(event) => void appeal(event)}>
                    <label htmlFor={`appeal-${notice.id}`}>
                      Why should this sanction be reconsidered?
                    </label>
                    <textarea
                      id={`appeal-${notice.id}`}
                      rows={4}
                      required
                      maxLength={4000}
                      value={explanation}
                      onChange={(event) => setExplanation(event.target.value)}
                    />
                    <div className="appeal-actions">
                      <button className="button" disabled={pending || !explanation.trim()}>
                        {pending ? 'Submitting…' : 'Submit appeal'}
                      </button>
                      <button
                        type="button"
                        className="button secondary"
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
          <h3>Appeal history</h3>
          {!data.appeals.length && <p className="muted">No appeals submitted.</p>}
          {data.appeals.map((item) => (
            <article className="notice" key={item.id}>
              <strong>
                {label(item.kind)} · {label(item.status)}
              </strong>
              <p>{item.explanation}</p>
              <small>
                Submitted {date(item.created_at)}
                {item.resolved_at && ` · Reviewed ${date(item.resolved_at)}`}
              </small>
            </article>
          ))}
        </>
      )}
    </section>
  );
}
