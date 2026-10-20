import { PlayerIdentity } from '../components/PlayerIdentity';
import { ReportPlayer } from '../components/ReportPlayer';
import { useEffect, useRef, useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { api, type Page, type User } from '../api';
import { Badge, PageHeading, StatusMessage } from '../components/ui';
import { useAuth } from '../auth/context';
import { rankedApi, type HistoryEntry } from '../games/ranked';
import { RankIcon } from '../components/RankIcon';
import './ranked-presentation.css';
import { PageNavigation, type PaginationInfo } from '../components/Pagination';
import { usePageData } from '../moderation/usePageData';
export function Pagination({
  pagination,
  onPage,
}: {
  pagination: PaginationInfo;
  onPage: (page: number) => void;
}) {
  return <PageNavigation pagination={pagination} onPage={onPage} />;
}
export function Leaderboards() {
  const [page, setPage] = useState(1);
  const { data, error } = usePageData<Awaited<ReturnType<typeof rankedApi.leaderboard>>>(
    `/api/ranked/leaderboard/?page=${page}`,
    setPage,
    () => rankedApi.leaderboard(page),
  );
  const loading = !data && !error;
  return (
    <>
      <PageHeading eyebrow="A PLACE TO RISE" title="Leaderboards">
        The sharpest eyes, ranked by Elo. Complete one rated match to join.
      </PageHeading>
      {error && <StatusMessage error>{error}</StatusMessage>}
      {loading && <StatusMessage>Loading standings…</StatusMessage>}
      {data && (
        <section className="panel ranked-table">
          <p className="muted">
            {data.count} rated players{data.my_position ? ` · Your rank: #${data.my_position}` : ''}
          </p>
          {data.results.length ? (
            <table className="ranked-standings-table">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Player</th>
                  <th>Elo</th>
                  <th>Tier</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((p) => (
                  <tr key={p.username}>
                    <td>#{p.position}</td>
                    <td>
                      <Link to={`/players/${encodeURIComponent(p.username)}`}>
                        <PlayerIdentity username={p.username} title={p.title} />
                      </Link>
                    </td>
                    <td>{p.rating}</td>
                    <td>
                      {p.tier ? (
                        <span className="ranked-tier">
                          <RankIcon tier={p.tier} decorative />
                          {p.tier}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p>
              The first rated duel is still ahead. <Link to="/ranked">Find an opponent.</Link>
            </p>
          )}
          <Pagination pagination={data} onPage={setPage} />
        </section>
      )}
      <section className="panel tier-panel">
        <h2>The ranked journey</h2>
        <div className="category-list">
          {data?.tiers?.map(([minimum, name]) => (
            <Badge key={name}>
              <span className="ranked-tier">
                <RankIcon tier={name} decorative />
                {name} · {minimum}
              </span>
            </Badge>
          ))}
        </div>
        <p className="muted">
          Every account starts at {data?.starting_elo ?? 1000} Elo. Your exact Elo is shown without
          a tier badge until the first tier.
        </p>
      </section>
    </>
  );
}
export function RankedProfile({ username, own }: { username: string; own: boolean }) {
  const { user: account, signOut } = useAuth();
  const [signingOut, setSigningOut] = useState(false);
  const [logoutError, setLogoutError] = useState('');
  const logoutRequest = useRef(false);
  const logout = async () => {
    if (logoutRequest.current) return;
    logoutRequest.current = true;
    setSigningOut(true);
    setLogoutError('');
    try {
      await signOut();
    } catch (error) {
      setLogoutError((error as Error).message);
    } finally {
      logoutRequest.current = false;
      setSigningOut(false);
    }
  };
  const [profile, setProfile] = useState<Omit<User, 'email'> | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState('');
  const { data: history, error: historyError } = usePageData<Page<HistoryEntry>>(
    `/api/ranked/history/${encodeURIComponent(username)}/?page=${page}`,
    setPage,
    () => rankedApi.history(username, page),
  );
  useEffect(() => {
    let disposed = false;
    void api<Omit<User, 'email'>>(`/api/auth/profiles/${encodeURIComponent(username)}/`)
      .then((user) => {
        if (!disposed) {
          setProfile(user);
          setError('');
        }
      })
      .catch((err: Error) => {
        if (!disposed) setError(err.message);
      });
    return () => {
      disposed = true;
    };
  }, [username]);
  if (!own && profile && account?.id === profile.id) return <Navigate to="/profile" replace />;
  if (error || historyError) return <StatusMessage error>{error || historyError}</StatusMessage>;
  if (!profile || !history) return <StatusMessage>Loading profile…</StatusMessage>;
  return (
    <>
      <PageHeading eyebrow="A PLACE IN THE GRID" title={profile.display_name || profile.username}>
        <span className="profile-identity">
          <span className="profile-identity-name">
            <PlayerIdentity username={'@' + profile.username} title={profile.title} />
          </span>
          {!own && <ReportPlayer key={profile.id} id={profile.id} username={profile.username} />}
          {own && (
            <button
              className="button compact secondary"
              type="button"
              disabled={signingOut}
              onClick={() => void logout()}
            >
              {signingOut ? 'Signing out…' : 'Sign out'}
            </button>
          )}
        </span>
      </PageHeading>
      {logoutError && <StatusMessage error>{logoutError}</StatusMessage>}
      <section className="panel profile-panel">
        <div className="avatar" aria-hidden="true">
          {(profile.display_name || profile.username).slice(0, 1).toUpperCase()}
        </div>
        <div>
          <h2 className="profile-elo">
            <span>{profile.rating} Elo</span>
            <RankIcon tier={profile.ranked_tier} />
          </h2>

          <p>
            {profile.ranked_wins} wins · {profile.ranked_losses} losses · {profile.ranked_matches}{' '}
            rated matches
          </p>
          <p className="muted">Member since {new Date(profile.date_joined).toLocaleDateString()}</p>
          {own && (
            <Link className="button secondary" to="/settings/account">
              Account settings ↗
            </Link>
          )}
        </div>
      </section>
      <section className="panel ranked-table">
        <h2>Match history</h2>
        {history.results.length ? (
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Opponent</th>
                <th>Result</th>
                <th>Score</th>
                <th>Elo</th>
              </tr>
            </thead>
            <tbody>
              {history.results.map((entry) => (
                <tr key={entry.id}>
                  <td>{new Date(entry.date).toLocaleDateString()}</td>
                  <td>
                    {entry.opponent_deleted ? (
                      <span>Deleted player</span>
                    ) : (
                      <Link to={`/players/${encodeURIComponent(entry.opponent)}`}>
                        <PlayerIdentity username={entry.opponent} title={entry.opponent_title} />
                      </Link>
                    )}
                  </td>
                  <td>
                    <span className={`history-outcome history-outcome-${entry.outcome}`}>
                      {entry.outcome === 'no_contest' ? 'NO CONTEST' : entry.outcome.toUpperCase()}
                    </span>
                    {entry.forfeit && ' · Forfeit'}
                  </td>
                  <td>
                    {entry.score}–{entry.opponent_score}
                  </td>
                  <td>
                    {entry.rating_before} → {entry.rating_after} (
                    {entry.rating_delta > 0 ? '+' : ''}
                    {entry.rating_delta})
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">No completed duels yet.</p>
        )}
        <Pagination pagination={history} onPage={setPage} />
      </section>
    </>
  );
}
