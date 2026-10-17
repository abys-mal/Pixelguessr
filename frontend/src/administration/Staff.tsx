import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { Page } from '../api';
import { PlayerIdentity } from '../components/PlayerIdentity';
import { Dialog, Feedback, Heading, Loading, Pager } from '../moderation/components';
import { useData } from '../moderation/useData';
import type { Player } from '../moderation/api';
import { adminRoot, send } from './api';

interface StaffPlayer extends Player {
  role: string;
  account_status: string;
  assigned_at: string | null;
  recent_activity: string | null;
}
export function StaffRoles() {
  const [role, setRole] = useState('all');
  const [page, setPage] = useState(1);
  const [q, setQ] = useState('');
  const { data, error, reload } = useData<Page<StaffPlayer>>(
    `${adminRoot}staff/?role=${role}&page=${page}`,
  );
  const search = useData<Page<Player>>(`${adminRoot}players/?q=${encodeURIComponent(q)}`);
  const [target, setTarget] = useState<{ player: Player; enabled: boolean } | null>(null);
  const [pending, setPending] = useState(false);
  const [actionError, setActionError] = useState('');
  const [message, setMessage] = useState('');
  const confirm = async () => {
    if (!target || pending) return;
    setPending(true);
    setActionError('');
    try {
      await send(`players/${target.player.id}/`, {
        operation: 'moderator',
        enabled: target.enabled,
      });
      setMessage(target.enabled ? 'Moderator access granted.' : 'Moderator access removed.');
      setTarget(null);
      setQ('');
      reload();
      search.reload();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setPending(false);
    }
  };
  return (
    <>
      <Heading
        title="Staff & Roles"
        detail="A focused directory of the people looking after the game."
      />
      <div className="admin-filters">
        <label>
          Staff role
          <select
            value={role}
            onChange={(e) => {
              setRole(e.target.value);
              setPage(1);
            }}
          >
            <option value="all">All staff</option>
            <option value="administrators">Administrators</option>
            <option value="moderators">Moderators</option>
          </select>
        </label>
      </div>
      <Feedback message={message} />
      {!data ? (
        <Loading error={error} retry={reload} />
      ) : (
        <>
          <div className="admin-staff-list">
            {data.results.map((person) => (
              <article className="mod-card" key={person.id}>
                <div className="mod-section-title">
                  <h2>
                    <PlayerIdentity username={person.username} title={person.title} />
                  </h2>
                  <span className="mod-chip">{person.role}</span>
                </div>
                <p>
                  {person.display_name || 'No display name'} · {person.account_status}
                </p>
                <p className="mod-muted">
                  Assigned:{' '}
                  {person.assigned_at
                    ? new Date(person.assigned_at).toLocaleString()
                    : 'Historical assignment date unknown'}
                </p>
                <p className="mod-muted">
                  Recent action:{' '}
                  {person.recent_activity?.replaceAll('_', ' ') || 'No recorded activity'}
                </p>
                <div className="mod-actions">
                  <Link to={`/moderation/players/${person.id}`}>Review player →</Link>
                  {person.role === 'Moderator' && (
                    <button
                      className="mod-button subtle"
                      onClick={() => {
                        setActionError('');
                        setTarget({ player: person, enabled: false });
                      }}
                    >
                      Remove moderator access
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
          {!data.count && <p className="mod-card mod-empty">No staff match this filter.</p>}
          <Pager page={page} next={data.next} previous={data.previous} change={setPage} />
        </>
      )}
      <section className="mod-card">
        <h2>Promote a player</h2>
        <p className="mod-muted">
          Grant native moderation access. Administrator assignment and removal are
          command-line-only.
        </p>
        <form
          className="admin-filters"
          onSubmit={(e) => {
            e.preventDefault();
            setQ(String(new FormData(e.currentTarget).get('username') ?? ''));
          }}
        >
          <label>
            Find an ordinary player
            <input name="username" required maxLength={150} />
          </label>
          <button className="mod-button subtle">Search players</button>
        </form>
        {search.error && <Feedback error={search.error} />}
        <ul className="admin-search-results">
          {search.data?.results.map((person) => (
            <li key={person.id}>
              <div>
                <PlayerIdentity username={person.username} title={person.title} />
                <small>
                  {person.display_name} · {person.rating} Elo · Joined{' '}
                  {new Date(person.date_joined).toLocaleDateString()}
                </small>
              </div>
              <button
                className="mod-button subtle"
                onClick={() => {
                  setActionError('');
                  setTarget({ player: person, enabled: true });
                }}
              >
                Promote to moderator
              </button>
            </li>
          ))}
        </ul>
        {q && search.data && !search.data.count && <p>No ordinary players match.</p>}
      </section>
      {target && (
        <Dialog
          title={target.enabled ? 'Promote to moderator?' : 'Remove moderator access?'}
          close={() => setTarget(null)}
          pending={pending}
        >
          <p>
            Confirm {target.enabled ? 'granting' : 'removing'} moderator privileges for{' '}
            <strong>@{target.player.username}</strong> (
            {target.player.display_name || 'No display name'}).
          </p>
          <p className="mod-muted">Account ID: {target.player.id}</p>
          <Feedback error={actionError} />
          <div className="mod-actions">
            <button
              className="mod-button subtle"
              disabled={pending}
              onClick={() => setTarget(null)}
            >
              Cancel
            </button>
            <button className="mod-button" disabled={pending} onClick={() => void confirm()}>
              {pending ? 'Saving…' : 'Confirm role change'}
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
