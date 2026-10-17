import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useAuth } from '../auth/context';
import {
  root,
  post,
  label,
  date,
  expiry,
  type Kind,
  type Sanction,
  type PlayerDetail as Detail,
} from './api';
import { Dialog, Feedback, Heading, Loading } from './components';
import { useData } from './useData';
import { PlayerNames } from './PlayerNames';
import { AdministratorPlayerControls } from '../administration/PlayerControls';
import { PlayerIdentity } from '../components/PlayerIdentity';
import { moderationCategories } from './categories';
import { PlayerInformation } from './PlayerInformation';

function SanctionForm({
  player,
  original,
  close,
  saved,
}: {
  player: string;
  original?: Sanction;
  close: () => void;
  saved: () => void;
}) {
  const [kind, setKind] = useState<Kind>(original?.kind ?? 'warning');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const localExpiry = original?.expires_at
    ? new Date(
        new Date(original.expires_at).getTime() -
          new Date(original.expires_at).getTimezoneOffset() * 60000,
      )
        .toISOString()
        .slice(0, 16)
    : '';
  const [duration, setDuration] = useState<'indefinite' | 'fixed'>(
    original?.expires_at ? 'fixed' : 'indefinite',
  );
  const [initialExpiry, setInitialExpiry] = useState(localExpiry);
  const [minimumExpiry] = useState(() => {
    const now = new Date();
    return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  });
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    const form = new FormData(event.currentTarget);
    const needsExpiry = !['warning', 'closed'].includes(kind) && duration === 'fixed';
    const selectedExpiry = needsExpiry ? new Date(String(form.get('expiry') ?? '')) : null;
    if (
      selectedExpiry &&
      (!Number.isFinite(selectedExpiry.getTime()) || selectedExpiry <= new Date())
    ) {
      setError('Choose an expiration date in the future.');
      return;
    }
    setPending(true);
    setError('');
    try {
      await post(
        original
          ? `${root}sanctions/${original.id}/replace/`
          : `${root}players/${player}/sanctions/`,
        {
          kind,
          category: form.get('category'),
          reason: form.get('reason'),
          internal_note: form.get('internal_note'),
          expires_at: selectedExpiry?.toISOString() ?? null,
        },
      );
      saved();
      close();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setPending(false);
    }
  };
  return (
    <Dialog
      title={original ? 'Replace sanction' : 'Issue a sanction'}
      close={close}
      pending={pending}
    >
      <form className="mod-form" onSubmit={(event) => void submit(event)}>
        <fieldset>
          <legend>Sanction</legend>
          <div className="mod-kind-options">
            {(['warning', 'probation', 'suspension', 'closed'] as Kind[]).map((value) => (
              <label className={kind === value ? 'selected' : ''} key={value}>
                <input
                  type="radio"
                  name="kind"
                  value={value}
                  checked={kind === value}
                  onChange={() => {
                    setKind(value);
                    setDuration('indefinite');
                    setInitialExpiry('');
                  }}
                />
                {value === 'closed' ? 'Closure' : label(value)}
              </label>
            ))}
          </div>
        </fieldset>
        <p className="mod-muted">
          {kind === 'warning'
            ? 'Warnings expire after 90 days. Acknowledgment clears the notice; gameplay stays available.'
            : kind === 'probation'
              ? 'Blocks ranked play and image submissions.'
              : kind === 'suspension'
                ? 'Blocks parties, ranked play and image submissions. Sign-in and singleplayer stay available.'
                : 'Permanently blocks account access. Only an administrator can reverse closure.'}
        </p>
        <label>
          Category
          <select name="category" defaultValue={original?.category ?? 'fair_play'}>
            {moderationCategories.map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
        </label>
        {!['warning', 'closed'].includes(kind) && (
          <>
            <label>
              Duration
              <select
                value={duration}
                onChange={(event) => {
                  setDuration(event.target.value as 'indefinite' | 'fixed');
                  setInitialExpiry('');
                }}
              >
                <option value="indefinite">Indefinite</option>
                <option value="fixed">Fixed duration</option>
              </select>
            </label>
            {duration === 'fixed' ? (
              <label>
                Expires at <span>(your local time)</span>
                <input
                  type="datetime-local"
                  name="expiry"
                  required
                  defaultValue={initialExpiry}
                  min={minimumExpiry}
                />
              </label>
            ) : (
              <p className="mod-muted">Indefinite — remains active until reversed.</p>
            )}
          </>
        )}
        <label>
          Public reason <span>(optional · visible to the player)</span>
          <textarea name="reason" rows={3} maxLength={2000} defaultValue={original?.reason ?? ''} />
        </label>
        <label>
          Internal note <span>(optional · staff only)</span>
          <textarea
            name="internal_note"
            rows={3}
            maxLength={2000}
            defaultValue={original?.internal_note ?? ''}
          />
        </label>
        {original && (
          <p className="mod-muted">
            The original sanction will be reversed and linked to its replacement. Pending appeals
            will be marked Sanction changed.
          </p>
        )}
        <Feedback error={error} />
        <div className="mod-actions">
          <button className="mod-button subtle" type="button" disabled={pending} onClick={close}>
            Cancel
          </button>
          <button className={`mod-button ${kind === 'closed' ? 'danger' : ''}`} disabled={pending}>
            {pending
              ? 'Saving…'
              : original
                ? 'Replace sanction'
                : kind === 'closed'
                  ? 'Close account'
                  : 'Issue sanction'}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export function PlayerDetail({ id }: { id: string }) {
  const { user, refresh } = useAuth();
  const { data, error, reload } = useData<Detail>(`${root}players/${id}/`);
  const [form, setForm] = useState<Sanction | 'new' | null>(null);
  const [reversing, setReversing] = useState<Sanction | null>(null);
  const [access, setAccess] = useState<boolean | null>(null);
  const [pending, setPending] = useState(false);
  const [actionError, setActionError] = useState('');
  const [message, setMessage] = useState('');
  const [editingNames, setEditingNames] = useState(false);
  if (!data) return <Loading error={error} retry={reload} />;
  const isSelf = user?.id === data.player.id;
  const canAct = !!user?.administrator || !data.player.protected;
  const canSanction = canAct && !isSelf;
  const run = async (url: string, body = {}) => {
    if (pending) return;
    setPending(true);
    setActionError('');
    try {
      await post(url, body);
      setReversing(null);
      setAccess(null);
      setMessage('Changes saved.');
      reload();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setPending(false);
    }
  };
  const active = data.sanctions.filter((s) => s.active);
  return (
    <div className="mod-player-detail">
      <section className="mod-card">
        <div className="mod-player-header">
          <div className="mod-avatar" aria-hidden="true">
            {data.player.username.slice(0, 1).toUpperCase()}
          </div>
          <div>
            <h2>
              <PlayerIdentity username={'@' + data.player.username} title={data.player.title} />
            </h2>
            <p className="mod-muted">
              {data.player.display_name || 'Player'} · {data.player.rating} Elo
            </p>
          </div>
          <span className="mod-chip">{data.player.protected ? 'Staff account' : 'Player'}</span>
        </div>
        <div className="mod-player-meta">
          <span>Joined {new Date(data.player.date_joined).toLocaleDateString()}</span>
          <Link to={`/players/${data.player.username}`}>Public profile ↗</Link>
        </div>
        <div className="mod-actions">
          {canAct && (
            <button className="mod-button subtle" onClick={() => setEditingNames(true)}>
              Edit player names
            </button>
          )}
          {canSanction && (
            <button className="mod-button" onClick={() => setForm('new')}>
              Issue sanction
            </button>
          )}
          {user?.administrator && !data.player.protected && (
            <button className="mod-button subtle" onClick={() => setAccess(true)}>
              Grant moderator access
            </button>
          )}
          {user?.administrator && !isSelf && data.player.can_remove_moderator && (
            <button className="mod-button subtle" onClick={() => setAccess(false)}>
              Remove moderator access
            </button>
          )}
        </div>
        {isSelf && (
          <p className="mod-muted">You cannot issue or replace sanctions on your own account.</p>
        )}
        <Feedback error={actionError} message={message} />
      </section>
      <PlayerInformation player={data.player} />
      <AdministratorPlayerControls detail={data} saved={reload} />
      <section className="mod-card">
        <div className="mod-section-title">
          <h2>Active sanctions</h2>
          <span className="mod-muted">{active.length}</span>
        </div>
        {!active.length && <p className="mod-empty">No active sanctions.</p>}
        {active.map((s) => (
          <article className="mod-sanction" key={s.id}>
            <div className="mod-section-title">
              <span className={`mod-chip ${s.kind}`}>{label(s.kind)}</span>
              <small>
                {s.origin === 'voluntary' ? 'Voluntary closure requested by' : 'Issued by'} @
                {s.issued_by}
              </small>
            </div>
            <p>{s.reason || 'No public reason provided.'}</p>
            {s.internal_note && (
              <p className="mod-internal">
                <strong>Internal note</strong> {s.internal_note}
              </p>
            )}
            <p className="mod-muted">
              {date(s.starts_at)} · {expiry(s)}
              {s.acknowledged_at ? ' · Acknowledged' : ''}
            </p>
            {canAct && (user?.administrator || s.kind !== 'closed') && (
              <div className="mod-actions">
                {canSanction && (
                  <button className="mod-button subtle" onClick={() => setForm(s)}>
                    Replace sanction
                  </button>
                )}
                <button
                  className="mod-button subtle"
                  onClick={() => {
                    setActionError('');
                    setReversing(s);
                  }}
                >
                  Reverse sanction
                </button>
              </div>
            )}
          </article>
        ))}
      </section>
      <section className="mod-card">
        <h2>Previous sanctions</h2>
        {!data.sanctions.some((s) => !s.active) && (
          <p className="mod-empty">No previous sanctions.</p>
        )}
        {data.sanctions
          .filter((s) => !s.active)
          .map((s) => (
            <article className="mod-history-row" key={s.id}>
              <div>
                <strong>{label(s.kind)}</strong>
                <p>{s.reason || 'No public reason provided.'}</p>
                {s.internal_note && <p className="mod-internal">Internal: {s.internal_note}</p>}
                <small>
                  Issued by @{s.issued_by} · {date(s.starts_at)}
                  {s.replaces && ' · Linked replacement'}
                  {s.revoked_at && (
                    <>
                      <br />
                      Reversed by @{s.revoked_by} · {date(s.revoked_at)}
                    </>
                  )}
                </small>
              </div>
              <span className="mod-chip">{label(s.state)}</span>
            </article>
          ))}
      </section>
      <section className="mod-card">
        <h2>Reports & appeals</h2>
        {!data.reports.length && !data.appeals.length && (
          <p className="mod-empty">No reports or appeals on record.</p>
        )}
        {data.reports.map((r) => (
          <article key={r.id} className="mod-history-row">
            <div>
              <Link to="/moderation/reports">Report · {label(r.category)}</Link>
              <p>{r.details}</p>
              <small>
                {date(r.created_at)} · {r.resolution || (r.resolved_at ? 'Resolved' : 'Pending')}
              </small>
            </div>
          </article>
        ))}
        {data.appeals.map((a) => (
          <article key={a.id} className="mod-history-row">
            <div>
              <Link to="/moderation/appeals">Appeal · {label(a.kind)}</Link>
              <p>{a.explanation}</p>
              <small>
                {date(a.created_at)} · {label(a.status)}
              </small>
            </div>
          </article>
        ))}
      </section>
      <section className="mod-card">
        <h2>Activity</h2>
        <ol className="mod-timeline">
          {data.activity.map((a) => (
            <li key={a.id}>
              <strong>{label(a.action)}</strong>
              <p>
                @{a.actor} · {date(a.created_at)}
              </p>
              {typeof a.changes.reason === 'string' && a.changes.reason && (
                <p>{a.changes.reason}</p>
              )}
              {typeof a.changes.internal_note === 'string' && a.changes.internal_note && (
                <p className="mod-internal">Internal: {String(a.changes.internal_note)}</p>
              )}
              {a.action === 'player_names_changed' &&
                ['username', 'display_name'].map((field) => {
                  const change = a.changes[field];
                  if (
                    !change ||
                    typeof change !== 'object' ||
                    !('old' in change) ||
                    !('new' in change)
                  )
                    return null;
                  return (
                    <p key={field}>
                      {field === 'username' ? 'Username' : 'Display name'}:{' '}
                      {String(change.old) || '(blank)'} → {String(change.new) || '(blank)'}
                    </p>
                  );
                })}
            </li>
          ))}
        </ol>
        {!data.activity.length && (
          <p className="mod-empty">
            No recorded actions yet. Historical sanctions are listed above.
          </p>
        )}
      </section>
      {editingNames && (
        <PlayerNames
          player={data.player}
          close={() => setEditingNames(false)}
          saved={() => {
            setMessage('Player names saved.');
            reload();
            if (user?.id === id) void refresh();
          }}
        />
      )}
      {form && (
        <SanctionForm
          player={id}
          original={form === 'new' ? undefined : form}
          close={() => setForm(null)}
          saved={() => {
            setMessage('Sanction saved.');
            reload();
          }}
        />
      )}
      {reversing && (
        <Dialog title="Reverse sanction?" close={() => setReversing(null)} pending={pending}>
          <p>
            Reverse this {label(reversing.kind)} for @{data.player.username}? The original record
            and audit history will be preserved.
          </p>
          <Feedback error={actionError} />
          <div className="mod-actions">
            <button
              className="mod-button subtle"
              disabled={pending}
              onClick={() => setReversing(null)}
            >
              Cancel
            </button>
            <button
              className="mod-button"
              disabled={pending}
              onClick={() => void run(`${root}sanctions/${reversing.id}/reverse/`)}
            >
              {pending ? 'Saving…' : 'Reverse sanction'}
            </button>
          </div>
        </Dialog>
      )}
      {access !== null && (
        <Dialog
          title={access ? 'Grant moderator access?' : 'Remove moderator access?'}
          close={() => setAccess(null)}
          pending={pending}
        >
          <p>
            @{data.player.username}{' '}
            {access
              ? 'will gain access to the native moderation workspace. Django Admin access is not granted.'
              : 'will lose native moderation access. Historical actions will be preserved.'}
          </p>
          <Feedback error={actionError} />
          <div className="mod-actions">
            <button
              className="mod-button subtle"
              disabled={pending}
              onClick={() => setAccess(null)}
            >
              Cancel
            </button>
            <button
              className="mod-button"
              disabled={pending}
              onClick={() => void run(`${root}players/${id}/access/`, { enabled: access })}
            >
              Confirm
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

export function ModerationPlayer() {
  const { id } = useParams();
  return (
    <>
      <Heading
        title="Player review"
        detail="Account context, sanctions, and the complete moderation history."
      />
      <Link className="mod-back" to="/moderation/players">
        ← All players
      </Link>
      {id && <PlayerDetail key={id} id={id} />}
    </>
  );
}
