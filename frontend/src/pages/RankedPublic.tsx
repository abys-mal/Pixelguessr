import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type Page, type User } from '../api';
import { Badge, PageHeading, StatusMessage } from '../components/ui';
import { rankedApi, type Standing, type HistoryEntry } from '../games/ranked';
export function Pagination({
  page,
  next,
  previous,
  onPage,
}: {
  page: number;
  next: string | null;
  previous: string | null;
  onPage: (page: number) => void;
}) {
  return (
    <nav className="ranked-pagination" aria-label="Page navigation">
      <button className="button secondary" disabled={!previous} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span>Page {page}</span>
      <button className="button secondary" disabled={!next} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </nav>
  );
}
export function Leaderboards() {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<
    | (Page<Standing> & {
        my_position: number | null;
        tiers?: [number, string][];
        starting_elo?: number;
      })
    | null
  >(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let disposed = false;
    void rankedApi
      .leaderboard(page)
      .then((next) => {
        if (!disposed) {
          setData(next);
          setError('');
        }
      })
      .catch((err: Error) => {
        if (!disposed) setError(err.message);
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [page]);
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
            <table>
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
                      <Link to={`/players/${encodeURIComponent(p.username)}`}>{p.username}</Link>
                    </td>
                    <td>{p.rating}</td>
                    <td>{p.tier ? <Badge tone="violet">{p.tier}</Badge> : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p>
              The first rated duel is still ahead. <Link to="/ranked">Find an opponent.</Link>
            </p>
          )}
          <Pagination
            page={page}
            next={data.next}
            previous={data.previous}
            onPage={(value) => {
              setLoading(true);
              setPage(value);
            }}
          />
        </section>
      )}
      <section className="panel tier-panel">
        <h2>The ranked journey</h2>
        <div className="category-list">
          {data?.tiers?.map(([minimum, name]) => (
            <Badge key={name}>
              {name} · {minimum}
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
  const [profile, setProfile] = useState<Omit<User, 'email'> | null>(null);
  const [history, setHistory] = useState<Page<HistoryEntry> | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState('');
  useEffect(() => {
    let disposed = false;
    void Promise.all([
      api<Omit<User, 'email'>>(`/api/auth/profiles/${encodeURIComponent(username)}/`),
      rankedApi.history(username, page),
    ])
      .then(([user, matches]) => {
        if (!disposed) {
          setProfile(user);
          setHistory(matches);
          setError('');
        }
      })
      .catch((err: Error) => {
        if (!disposed) setError(err.message);
      });
    return () => {
      disposed = true;
    };
  }, [username, page]);
  if (error) return <StatusMessage error>{error}</StatusMessage>;
  if (!profile || !history) return <StatusMessage>Loading profile…</StatusMessage>;
  return (
    <>
      <PageHeading eyebrow="A PLACE IN THE GRID" title={profile.display_name || profile.username}>
        @{profile.username}
      </PageHeading>
      <section className="panel profile-panel">
        <div className="avatar" aria-hidden="true">
          {(profile.display_name || profile.username).slice(0, 1).toUpperCase()}
        </div>
        <div>
          <h2>{profile.rating} Elo</h2>
          {profile.ranked_tier && <Badge tone="violet">{profile.ranked_tier}</Badge>}
          {profile.title && <Badge tone="mint">{profile.title}</Badge>}
          <p>
            {profile.ranked_wins} wins · {profile.ranked_losses} losses · {profile.ranked_matches}{' '}
            rated matches
          </p>
          <p className="muted">Member since {new Date(profile.date_joined).toLocaleDateString()}</p>
          {own && (
            <Link className="button secondary" to="/settings">
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
                    <Link to={`/players/${encodeURIComponent(entry.opponent)}`}>
                      {entry.opponent}
                    </Link>
                  </td>
                  <td>
                    {entry.outcome === 'no_contest'
                      ? 'No Contest'
                      : entry.outcome === 'win'
                        ? 'Win'
                        : 'Loss'}
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
        <Pagination page={page} next={history.next} previous={history.previous} onPage={setPage} />
      </section>
    </>
  );
}
