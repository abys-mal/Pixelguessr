import { useRef, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, type Page } from '../api';
import { Dialog, Feedback, Heading, Loading, Pager } from '../moderation/components';
import { usePageData } from '../moderation/usePageData';
import { adminRoot } from './api';

const ipActivities = [
  ['registration', 'Account registration'],
  ['login', 'Login'],
  ['singleplayer', 'Singleplayer'],
  ['parties', 'Parties'],
  ['submissions', 'Image submissions'],
  ['community', 'Community interactions'],
] as const;
type ListKind = 'blacklist' | 'whitelist';
type Activity = (typeof ipActivities)[number][0];
interface IPEntry {
  id: string;
  list_kind: ListKind;
  address: string;
  reason: string;
  activities: Activity[];
  expires_at: string | null;
  status: 'active' | 'expired';
  created_at: string;
  updated_at: string;
  created_by: string;
  updated_by: string;
}
const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
function localInput(iso: string) {
  const date = new Date(iso);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 19);
}
const endpoint = (kind: ListKind, id = '') => `${adminRoot}ip-access/${kind}/${id ? id + '/' : ''}`;

function IPForm({
  kind,
  entry,
  close,
  saved,
}: {
  kind: ListKind;
  entry?: IPEntry;
  close: () => void;
  saved: () => void;
}) {
  const [activities, setActivities] = useState<Activity[]>(entry?.activities ?? []);
  const [duration, setDuration] = useState(entry?.expires_at ? 'temporary' : 'indefinite');
  const [expires, setExpires] = useState(entry?.expires_at ? localInput(entry.expires_at) : '');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const lock = useRef(false);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (lock.current) return;
    const form = new FormData(event.currentTarget);
    setError('');
    if (kind === 'blacklist' && !activities.length) {
      setError('Select at least one blocked activity.');
      return;
    }
    let expiration: string | null = null;
    if (kind === 'blacklist' && duration === 'temporary') {
      const date = new Date(expires);
      const local = expires.replace(/\.0+$/, '');
      if (
        !Number.isFinite(date.getTime()) ||
        date.getTime() <= Date.now() ||
        localInput(date.toISOString()).slice(0, local.length) !== local
      ) {
        setError('Choose a valid future expiration in the displayed time zone.');
        return;
      }
      expiration = date.toISOString();
    }
    lock.current = true;
    setPending(true);
    try {
      await api<IPEntry>(endpoint(kind, entry?.id), {
        method: 'POST',
        body: JSON.stringify({
          address: String(form.get('address')).trim(),
          reason: String(form.get('reason')).trim(),
          ...(kind === 'blacklist' ? { activities, duration, expires_at: expiration } : {}),
        }),
      });
      saved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      lock.current = false;
      setPending(false);
    }
  };
  return (
    <Dialog
      title={`${entry ? 'Edit' : 'Add'} ${kind === 'blacklist' ? 'blacklist' : 'whitelist'} IP`}
      close={close}
      pending={pending}
    >
      <form className="mod-form admin-ip-form" onSubmit={(event) => void submit(event)}>
        <label>
          IP address
          <input
            name="address"
            required
            maxLength={64}
            autoComplete="off"
            spellCheck={false}
            defaultValue={entry?.address ?? ''}
            disabled={pending}
            placeholder="IPv4 or IPv6; exact addresses only"
          />
        </label>
        {kind === 'blacklist' && (
          <>
            <fieldset disabled={pending}>
              <legend>Blocked activities</legend>
              <div className="admin-ip-selection-actions">
                <button
                  type="button"
                  className="mod-button subtle"
                  onClick={() => setActivities(ipActivities.map(([key]) => key))}
                >
                  Select all
                </button>
                <button
                  type="button"
                  className="mod-button subtle"
                  onClick={() => setActivities([])}
                >
                  Clear
                </button>
              </div>
              <div className="admin-ip-checkboxes">
                {ipActivities.map(([key, label]) => (
                  <label key={key}>
                    <input
                      type="checkbox"
                      checked={activities.includes(key)}
                      onChange={(event) =>
                        setActivities((current) =>
                          event.target.checked
                            ? [...current, key]
                            : current.filter((item) => item !== key),
                        )
                      }
                    />
                    {label}
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset disabled={pending}>
              <legend>Duration</legend>
              <div className="admin-ip-duration">
                {['temporary', 'indefinite'].map((value) => (
                  <label key={value}>
                    <input
                      type="radio"
                      name="duration"
                      value={value}
                      checked={duration === value}
                      onChange={() => setDuration(value)}
                    />
                    {value === 'temporary' ? 'Temporary' : 'Indefinite'}
                  </label>
                ))}
              </div>
              {duration === 'temporary' && (
                <label>
                  Expiration date and time
                  <input
                    type="datetime-local"
                    step="1"
                    required
                    value={expires}
                    onChange={(event) => setExpires(event.target.value)}
                    aria-describedby="ip-expiration-zone"
                  />
                </label>
              )}
              <p id="ip-expiration-zone" className="mod-muted">
                Time zone: {zone}
              </p>
            </fieldset>
          </>
        )}
        <label>
          Internal reason
          <textarea
            name="reason"
            required
            maxLength={2000}
            rows={3}
            defaultValue={entry?.reason ?? ''}
            disabled={pending}
          />
        </label>
        <Feedback error={error} />
        <div className="mod-actions">
          <button className="mod-button subtle" type="button" disabled={pending} onClick={close}>
            Cancel
          </button>
          <button className="mod-button" disabled={pending}>
            {pending ? 'Saving…' : 'Save IP'}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export function IPManagement() {
  const [params, setParams] = useSearchParams();
  const kind: ListKind = params.get('list') === 'whitelist' ? 'whitelist' : 'blacklist';
  const q = params.get('q') ?? '';
  const update = (changes: Record<string, string>, replace = false) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        for (const [key, value] of Object.entries(changes)) next.set(key, value);
        return next;
      },
      { replace },
    );
  const query = new URLSearchParams({ q, page: params.get('page') ?? '1' });
  const { data, error, reload } = usePageData<Page<IPEntry>>(endpoint(kind) + '?' + query, (page) =>
    update({ page: String(page) }, true),
  );
  const [editing, setEditing] = useState<IPEntry | 'new' | null>(null);
  const [deleting, setDeleting] = useState<IPEntry | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [actionError, setActionError] = useState('');
  const deleteLock = useRef(false);
  const remove = async () => {
    if (!deleting || deleteLock.current) return;
    deleteLock.current = true;
    setPending(true);
    setActionError('');
    try {
      await api(endpoint(kind, deleting.id), { method: 'DELETE' });
      setDeleting(null);
      setMessage('IP entry deleted.');
      reload();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      deleteLock.current = false;
      setPending(false);
    }
  };
  const selectTab = (value: ListKind) => {
    update({ list: value, page: '1' });
    setMessage('');
    setEditing(null);
    setDeleting(null);
  };
  return (
    <div className="admin-ip-page">
      <Heading
        title="IP Management"
        detail="Activity restrictions apply while signed out. Login restrictions also sign out existing sessions."
      />
      <div className="mod-filter" role="tablist" aria-label="IP access lists">
        {(['blacklist', 'whitelist'] as const).map((value) => (
          <button
            key={value}
            role="tab"
            id={`ip-tab-${value}`}
            aria-controls="ip-list-panel"
            aria-selected={kind === value}
            className={kind === value ? 'selected' : ''}
            onClick={() => selectTab(value)}
            onKeyDown={(event) => {
              if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
                event.preventDefault();
                const next =
                  event.key === 'Home'
                    ? 'blacklist'
                    : event.key === 'End'
                      ? 'whitelist'
                      : value === 'blacklist'
                        ? 'whitelist'
                        : 'blacklist';
                selectTab(next);
                document.getElementById('ip-tab-' + next)?.focus();
              }
            }}
          >
            {value === 'blacklist' ? 'Blacklist' : 'Whitelist'}
          </button>
        ))}
      </div>
      <section
        id="ip-list-panel"
        role="tabpanel"
        aria-labelledby={`ip-tab-${kind}`}
        className="admin-ip-panel"
      >
        <button
          className="mod-button admin-ip-add"
          onClick={() => {
            setEditing('new');
            setMessage('');
          }}
        >
          Add IP
        </button>
        <form
          className="admin-filters"
          key={kind}
          onSubmit={(event) => {
            event.preventDefault();
            update({
              q: String(new FormData(event.currentTarget).get('q') ?? '').trim(),
              page: '1',
            });
          }}
        >
          <label>
            Search IP addresses or reasons
            <input name="q" maxLength={150} defaultValue={q} />
          </label>
          <button className="mod-button subtle">Search</button>
        </form>
        <p className="mod-muted">
          IP addresses may be shared. Moderators and administrators are exempt from IP restrictions.
          Whitelist entries override IP restrictions. These entries do not suspend accounts. Times
          use {zone}.
        </p>
        <Feedback message={message} />
        {!data ? (
          <Loading error={error} retry={reload} />
        ) : (
          <>
            <ul
              className="admin-ip-list"
              aria-label={kind === 'blacklist' ? 'Blacklisted IPs' : 'Whitelisted IPs'}
            >
              {data.results.map((entry) => (
                <li key={entry.id} className="mod-card admin-ip-entry">
                  <div className="mod-section-title">
                    <strong className="admin-ip-address">{entry.address}</strong>
                    <span className="mod-chip">
                      {entry.status === 'expired' ? 'Expired' : 'Active'}
                    </span>
                  </div>
                  <p className="admin-ip-reason">{entry.reason}</p>
                  {kind === 'blacklist' && (
                    <>
                      <ul className="admin-ip-activities">
                        {entry.activities.map((key) => (
                          <li className="mod-chip" key={key}>
                            {ipActivities.find(([activity]) => activity === key)?.[1]}
                          </li>
                        ))}
                      </ul>
                      {!entry.activities.length && (
                        <p className="mod-muted">
                          Legacy ranked-only entry: no longer enforced. Edit to choose restrictions
                          or delete.
                        </p>
                      )}
                      <p className="mod-muted">
                        {entry.expires_at
                          ? `Expires ${new Date(entry.expires_at).toLocaleString()}`
                          : 'Indefinite'}
                      </p>
                    </>
                  )}
                  <p className="mod-muted">
                    Added {new Date(entry.created_at).toLocaleString()} by @{entry.created_by}
                  </p>
                  <div className="mod-actions">
                    <button
                      className="mod-button subtle"
                      onClick={() => setEditing(entry)}
                      aria-label={`Edit ${entry.address}`}
                    >
                      Edit
                    </button>
                    <button
                      className="mod-button subtle"
                      onClick={() => {
                        setDeleting(entry);
                        setActionError('');
                      }}
                      aria-label={`Delete ${entry.address}`}
                    >
                      Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
            {!data.count && (
              <p className="mod-card mod-empty">No {kind} entries match this view.</p>
            )}
            <Pager pagination={data} change={(page) => update({ page: String(page) })} />
          </>
        )}
      </section>
      {editing && (
        <IPForm
          kind={kind}
          entry={editing === 'new' ? undefined : editing}
          close={() => setEditing(null)}
          saved={() => {
            setEditing(null);
            setMessage('IP entry saved.');
            reload();
          }}
        />
      )}
      {deleting && (
        <Dialog title="Delete IP entry?" close={() => setDeleting(null)} pending={pending}>
          <p>
            Remove {deleting.address} from the {kind}?
          </p>
          <Feedback error={actionError} />
          <div className="mod-actions">
            <button
              className="mod-button subtle"
              disabled={pending}
              onClick={() => setDeleting(null)}
            >
              Cancel
            </button>
            <button className="mod-button" disabled={pending} onClick={() => void remove()}>
              {pending ? 'Deleting…' : 'Delete IP'}
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
