import { useState } from 'react';
import { useAuth } from '../auth/context';
import { Link } from 'react-router-dom';
import type { Page } from '../api';
import { PlayerIdentity } from '../components/PlayerIdentity';
import { Dialog, Feedback, Heading, Loading, Pager } from '../moderation/components';
import { usePageData } from '../moderation/usePageData';
import type { Player } from '../moderation/api';
import { adminRoot, send } from './api';

interface StaffPlayer extends Player {
  role: string;
  account_status: string;
  assigned_at: string | null;
  recent_activity: string | null;
}
export function StaffRoles() {
  const { user } = useAuth();
  const [role, setRole] = useState('all');
  const [page, setPage] = useState(1);
  const [q, setQ] = useState('');
  const [searchPage, setSearchPage] = useState(1);
  const { data, error, reload } = usePageData<Page<StaffPlayer>>(
    `${adminRoot}staff/?role=${role}&page=${page}`,
    setPage,
  );
  const search = usePageData<Page<Player>>(
    `${adminRoot}players/?q=${encodeURIComponent(q)}&page=${searchPage}`,
    setSearchPage,
  );
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
      setSearchPage(1);
      reload();
      search.reload();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setPending(false);
    }
  };
  return (
    <div className="admin-staff-page">
      <Heading
        title="Staff & Roles"
        detail="A focused directory of the people looking after the game."
      />
      <Feedback message={message} />
      <section className="mod-card" aria-labelledby="promote-player-heading">
        <h2 id="promote-player-heading">Promote a Player</h2>
        <p className="mod-muted">
          Grant native moderation access. Administrator assignment and removal are
          command-line-only.
        </p>
        <form
          className="admin-filters"
          onSubmit={(e) => {
            e.preventDefault();
            setQ(String(new FormData(e.currentTarget).get('username') ?? ''));
            setSearchPage(1);
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
        {q && search.data && <Pager pagination={search.data} change={setSearchPage} />}
      </section>
      <section className="mod-card" aria-labelledby="current-staff-heading">
        <h2 id="current-staff-heading">Current Staff</h2>
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
        {!data ? (
          <Loading error={error} retry={reload} />
        ) : (
          <>
            <ul className="admin-staff-list" aria-label="Current staff">
              {data.results.map((person) => (
                <li className="admin-staff-row" key={person.id}>
                  <div className="admin-staff-identity">
                    <strong>
                      <PlayerIdentity username={person.username} title={person.title} />
                    </strong>
                    <span className="mod-muted">{person.display_name || 'No display name'}</span>
                    <details className="admin-staff-history">
                      <summary>Role history</summary>
                      <p>
                        Assigned:{' '}
                        {person.assigned_at
                          ? new Date(person.assigned_at).toLocaleString()
                          : 'Historical assignment date unknown'}
                      </p>
                      <p>
                        Recent action:{' '}
                        {person.recent_activity?.replaceAll('_', ' ') || 'No recorded activity'}
                      </p>
                    </details>
                  </div>
                  <div className="admin-staff-status">
                    <span className="mod-chip">{person.role}</span>
                    <span className="mod-muted">{person.account_status}</span>
                  </div>
                  <div className="mod-actions admin-staff-actions">
                    <Link to={`/moderation/players/${person.id}`}>Review player →</Link>
                    {person.role === 'Moderator' &&
                      person.can_remove_moderator &&
                      person.id !== user?.id && (
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
                </li>
              ))}
            </ul>
            {!data.count && <p className="mod-empty">No staff match this filter.</p>}
            <Pager pagination={data} change={setPage} />
          </>
        )}
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
    </div>
  );
}
