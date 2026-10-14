import { useState } from 'react';
import type { Page } from '../api';
import { root, post, label, date, type Appeal, type Report } from './api';
import { Dialog, Feedback, Heading, Loading, Pager } from './components';
import { PlayerDetail } from './Player';
import { useData } from './useData';

export function ModerationInbox({ appeals = false }: { appeals?: boolean }) {
  const [filter, setFilter] = useState('pending');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState('');
  const [decision, setDecision] = useState('');
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [actionError, setActionError] = useState('');
  const kind = appeals ? 'appeals' : 'reports';
  const { data, error, reload } = useData<Page<Report | Appeal>>(
    `${root}${kind}/?status=${filter}&page=${page}`,
  );
  const item = data?.results.find((row) => row.id === selected) ?? data?.results[0];
  const player = item ? ('player' in item ? item.player : item.subject) : null;
  const resolved = item
    ? 'status' in item
      ? item.status !== 'pending'
      : !!item.resolved_at
    : false;
  const submit = async (choice: string) => {
    if (pending || !item) return;
    setPending(true);
    setActionError('');
    try {
      await post(`${root}${kind}/${item.id}/resolve/`, { decision: choice });
      setDecision('');
      setMessage('Review saved.');
      reload();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setPending(false);
    }
  };
  return (
    <>
      <Heading
        title={appeals ? 'Appeals' : 'Reports'}
        detail={
          appeals
            ? 'Hear the player’s explanation and review the original sanction.'
            : 'Read the context, review the player, and decide what comes next.'
        }
      />
      <div className="mod-filter" role="group" aria-label="Inbox filter">
        {['pending', 'all'].map((value) => (
          <button
            className={filter === value ? 'selected' : ''}
            aria-pressed={filter === value}
            key={value}
            onClick={() => {
              setFilter(value);
              setPage(1);
              setSelected('');
              setMessage('');
            }}
          >
            {value === 'pending' ? 'Needs review' : 'All history'}
          </button>
        ))}
      </div>
      <Feedback message={message} error={actionError} />
      {!data ? (
        <Loading error={error} retry={reload} />
      ) : !data.results.length ? (
        <section className="mod-card mod-empty">
          <h2>All clear.</h2>
          <p>
            {filter === 'pending' ? `No ${kind} need review right now.` : `No ${kind} on record.`}
          </p>
        </section>
      ) : (
        <div className="mod-inbox">
          <section className="mod-inbox-list" aria-label={`${kind} inbox`}>
            {data.results.map((row) => (
              <button
                className={row.id === item?.id ? 'selected' : ''}
                aria-pressed={row.id === item?.id}
                key={row.id}
                onClick={() => {
                  setSelected(row.id);
                  setActionError('');
                }}
              >
                <span className="mod-section-title">
                  <strong>@{'player' in row ? row.player.username : row.subject.username}</strong>
                  <span aria-hidden="true">→</span>
                </span>
                <span>{'kind' in row ? label(row.kind) + ' appeal' : label(row.category)}</span>
                <small>{date(row.created_at)}</small>
                <span className="mod-preview">
                  {'explanation' in row ? row.explanation : row.details}
                </span>
              </button>
            ))}
            <Pager page={page} next={data.next} previous={data.previous} change={setPage} />
          </section>
          {item && player && (
            <div className="mod-inbox-detail" key={item.id}>
              <article className="mod-card">
                <p className="mod-eyebrow">{appeals ? 'PLAYER APPEAL' : 'PLAYER REPORT'}</p>
                <div className="mod-section-title">
                  <h2>@{player.username}</h2>
                  <span className="mod-chip">
                    {'status' in item
                      ? label(item.status)
                      : item.resolution || (item.resolved_at ? 'Resolved' : 'Pending')}
                  </span>
                </div>
                <p className="mod-muted">
                  {date(item.created_at)}
                  {'reporter' in item && ` · Reporter @${item.reporter} (staff only)`}
                </p>
                <blockquote>{'explanation' in item ? item.explanation : item.details}</blockquote>
                {'sanction' in item && (
                  <div className="mod-original">
                    <h3>Original {label(item.sanction.kind)}</h3>
                    <p>{item.sanction.reason || 'No public reason provided.'}</p>
                    {item.sanction.internal_note && (
                      <p className="mod-internal">Internal: {item.sanction.internal_note}</p>
                    )}
                    <small>
                      Issued by @{item.sanction.issued_by} · {date(item.sanction.starts_at)} ·{' '}
                      {date(item.sanction.expires_at)}
                    </small>
                  </div>
                )}
                {!resolved && (
                  <div className="mod-actions">
                    {appeals ? (
                      <>
                        <button
                          className="mod-button"
                          disabled={pending}
                          onClick={() => setDecision('reverse')}
                        >
                          Reverse sanction
                        </button>
                        <button
                          className="mod-button subtle"
                          disabled={pending}
                          onClick={() => void submit('uphold')}
                        >
                          Uphold
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          className="mod-button"
                          disabled={pending}
                          onClick={() => void submit('resolved')}
                        >
                          Resolve report
                        </button>
                        <button
                          className="mod-button subtle"
                          disabled={pending}
                          onClick={() => void submit('dismissed')}
                        >
                          Dismiss
                        </button>
                      </>
                    )}
                  </div>
                )}
                {!appeals && (
                  <p className="mod-muted">
                    Issue a sanction directly from the player review below. Resolving a report does
                    not issue a sanction.
                  </p>
                )}
              </article>
              <PlayerDetail id={player.id} />
            </div>
          )}
        </div>
      )}
      {decision && (
        <Dialog
          title="Reverse the appealed sanction?"
          close={() => setDecision('')}
          pending={pending}
        >
          <p>
            The appeal will be accepted and its sanction reversed. All records and earlier decisions
            will be preserved.
          </p>
          <Feedback error={actionError} />
          <div className="mod-actions">
            <button
              className="mod-button subtle"
              disabled={pending}
              onClick={() => setDecision('')}
            >
              Cancel
            </button>
            <button className="mod-button" disabled={pending} onClick={() => void submit(decision)}>
              {pending ? 'Saving…' : 'Reverse sanction'}
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
