import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../api';
import { useAuth } from '../auth/context';
import { StatusMessage } from './ui';

import { AccountNoticeStatus } from './AccountNoticeStatus';
import {
  appealLabel,
  historicalLabel,
  noticeDate,
  noticeTime,
  orderSanctions,
  sanctionLabel,
  type AccountSanction,
  type AccountNoticesData,
} from './notices';

function SanctionDates({ notice }: { notice: AccountSanction }) {
  return (
    <dl className="notice-dates">
      <div>
        <dt>Issued</dt>
        <dd>
          <time dateTime={notice.starts_at}>{noticeDate(notice.starts_at)}</time>
        </dd>
      </div>
      <div>
        <dt>Expiration</dt>
        <dd>
          {notice.expires_at ? (
            <time dateTime={notice.expires_at}>{noticeDate(notice.expires_at)}</time>
          ) : notice.kind === 'closed' ? (
            'Permanent'
          ) : (
            'Indefinite'
          )}
        </dd>
      </div>
    </dl>
  );
}
function PublicReason({ reason }: { reason: string }) {
  return (
    <div className="notice-reason">
      <p className="notice-field-label">Public reason</p>
      {reason.length > 240 ? (
        <details>
          <summary>
            {reason.slice(0, 180)}… <span>Read full reason</span>
          </summary>
          <p>{reason}</p>
        </details>
      ) : (
        <p>{reason}</p>
      )}
    </div>
  );
}

export function AccountNotices() {
  const { restrictions, refresh } = useAuth();
  const [data, setData] = useState<AccountNoticesData | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState(false);
  const [appealing, setAppealing] = useState('');
  const [explanation, setExplanation] = useState('');
  const [revision, setRevision] = useState(0);
  // Public restriction changes arrive over the normal account socket. History also polls
  // to receive appeal decisions that need not change the current restrictions.
  const signature = JSON.stringify(restrictions);
  useEffect(() => {
    let live = true;
    const load = () =>
      void api<AccountNoticesData>('/api/moderation/notices/')
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

  const active = data ? orderSanctions(data.sanctions.filter((notice) => notice.active)) : [];
  const history = data?.sanctions.filter((notice) => !notice.active) ?? [];
  const pendingAppeals = data?.appeals.filter((item) => item.status === 'pending').length ?? 0;
  return (
    <div
      className="account-notices"
      id="account-notices"
      role="region"
      aria-label="Sanctions and appeals"
    >
      <AccountNoticeStatus activeCount={data ? active.length : undefined} />
      {error && (
        <div className="notice-feedback">
          <StatusMessage error>{error}</StatusMessage>
          <button
            className="button secondary compact"
            onClick={() => setRevision((value) => value + 1)}
          >
            Retry notices
          </button>
        </div>
      )}
      {message && <StatusMessage>{message}</StatusMessage>}
      {!data ? (
        <StatusMessage>Loading notices…</StatusMessage>
      ) : (
        <>
          <section aria-labelledby="active-sanctions-title" className="notice-section">
            <div className="notice-section-heading">
              <h2 id="active-sanctions-title">
                Active sanctions <span className="notice-count">{active.length}</span>
              </h2>
              <p>Current notices and available actions.</p>
            </div>
            {!active.length ? (
              <p className="notice-empty">No active sanctions.</p>
            ) : (
              <div className={`notice-active-grid${active.length === 1 ? ' single' : ''}`}>
                {active.map((notice) => (
                  <article
                    className={`notice-card tone-${notice.kind}`}
                    key={notice.id}
                    aria-label={`${sanctionLabel(notice.kind)} issued ${noticeDate(notice.starts_at)}`}
                  >
                    <header className="notice-card-heading">
                      <h3>{sanctionLabel(notice.kind)}</h3>
                      <div className="notice-badges">
                        <span className="notice-badge">Active</span>
                        {notice.acknowledged_at && (
                          <span className="notice-badge neutral">Acknowledged</span>
                        )}
                      </div>
                    </header>
                    <PublicReason reason={notice.reason} />
                    <SanctionDates notice={notice} />
                    <div className="notice-eligibility">
                      <p>{notice.appeal.detail}</p>
                      {notice.appeal.available_at && (
                        <p className="notice-cooldown">
                          Next eligibility:{' '}
                          <time dateTime={notice.appeal.available_at}>
                            {noticeTime(notice.appeal.available_at)}
                          </time>
                          .
                        </p>
                      )}
                      {((notice.kind === 'warning' && !notice.acknowledged_at) ||
                        notice.appeal.eligible) && (
                        <div className="notice-actions">
                          {notice.kind === 'warning' && !notice.acknowledged_at && (
                            <button
                              className="button secondary compact"
                              disabled={pending}
                              onClick={() => void acknowledge(notice.id)}
                            >
                              Acknowledge warning
                            </button>
                          )}
                          {notice.appeal.eligible && appealing !== notice.id && (
                            <button
                              className="button secondary compact"
                              disabled={pending}
                              onClick={() => {
                                setAppealing(notice.id);
                                setExplanation('');
                              }}
                            >
                              Appeal this sanction
                            </button>
                          )}
                        </div>
                      )}
                    </div>
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
            )}
          </section>
          <section
            aria-labelledby="notice-history-title"
            className="notice-section notice-history-section"
          >
            <div className="notice-section-heading">
              <h2 id="notice-history-title">History and appeals</h2>
              <p>Past records stay available. Expand a record for its full details.</p>
            </div>
            <div className="notice-history-grid">
              <section aria-labelledby="sanction-history-title">
                <h3 id="sanction-history-title">
                  Sanction history <span className="notice-count">{history.length}</span>
                </h3>
                {!history.length && <p className="notice-empty">No historical sanctions.</p>}
                {history.map((notice) => (
                  <details className="notice-record" key={notice.id}>
                    <summary>
                      <span className="notice-record-heading">
                        <strong>{sanctionLabel(notice.kind)}</strong>
                        <span className="notice-badge neutral">{historicalLabel(notice)}</span>
                      </span>
                      <span className="notice-record-date">
                        Issued {noticeDate(notice.starts_at)}
                      </span>
                    </summary>
                    <div className="notice-record-body">
                      <PublicReason reason={notice.reason} />
                      <SanctionDates notice={notice} />
                      {notice.revoked_at && (
                        <p className="notice-record-date">
                          Reversed {noticeTime(notice.revoked_at)}
                        </p>
                      )}
                      {notice.acknowledged_at && (
                        <p className="notice-record-date">
                          Acknowledged {noticeTime(notice.acknowledged_at)}
                        </p>
                      )}
                    </div>
                  </details>
                ))}
              </section>
              <section aria-labelledby="appeal-history-title">
                <h3 id="appeal-history-title">
                  Appeal history <span className="notice-count">{data.appeals.length}</span>
                </h3>
                {pendingAppeals > 0 && (
                  <p className="notice-pending-count">{pendingAppeals} pending review</p>
                )}
                {!data.appeals.length && <p className="notice-empty">No appeals submitted.</p>}
                {data.appeals.map((item) => (
                  <details
                    className={`notice-record${item.status === 'pending' ? ' tone-pending' : ''}`}
                    key={item.id}
                  >
                    <summary>
                      <span className="notice-record-heading">
                        <strong>{sanctionLabel(item.kind)} appeal</strong>
                        <span
                          className={`notice-badge ${item.status === 'pending' ? '' : 'neutral'}`}
                        >
                          {appealLabel(item.status)}
                        </span>
                      </span>
                      <span className="notice-record-date">
                        Submitted {noticeDate(item.created_at)}
                      </span>
                    </summary>
                    <div className="notice-record-body">
                      <p className="notice-field-label">Your explanation</p>
                      <p className="notice-explanation">{item.explanation}</p>
                      <dl className="notice-dates">
                        <div>
                          <dt>Submitted</dt>
                          <dd>{noticeTime(item.created_at)}</dd>
                        </div>
                        <div>
                          <dt>Decision</dt>
                          <dd>
                            {item.resolved_at ? noticeTime(item.resolved_at) : 'Awaiting review'}
                          </dd>
                        </div>
                      </dl>
                    </div>
                  </details>
                ))}
              </section>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
