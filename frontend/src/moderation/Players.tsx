import { PlayerIdentity } from '../components/PlayerIdentity';
import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import type { Page } from '../api';
import { root, type Player } from './api';
import { Heading, Loading, Pager, Feedback } from './components';
import { useData } from './useData';

export function ModerationPlayers() {
  const location = useLocation();
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const { data, error, reload } = useData<Page<Player>>(
    `${root}players/?q=${encodeURIComponent(query)}&page=${page}`,
  );
  return (
    <>
      <Heading
        title="Players"
        detail="Find an account. Review its history. Take action when needed."
      />
      {location.state?.accountDeleted && (
        <Feedback message="Account permanently deleted. Approved images and shared history were preserved anonymously." />
      )}
      <form
        className="mod-search"
        onSubmit={(event) => {
          event.preventDefault();
          setQuery(search.trim());
          setPage(1);
        }}
      >
        <label htmlFor="player-search">Search by username</label>
        <div>
          <input
            id="player-search"
            type="search"
            autoComplete="off"
            maxLength={150}
            value={search}
            placeholder="Find a player…"
            onChange={(event) => setSearch(event.target.value)}
          />
          <button className="mod-button">Search</button>
        </div>
      </form>
      {!data ? (
        <Loading error={error} retry={reload} />
      ) : (
        <section className="mod-card">
          <div className="mod-section-title">
            <h2>{query ? 'Search results' : 'Player directory'}</h2>
            <span className="mod-muted">{data.count} accounts</span>
          </div>
          {!data.results.length && <p className="mod-empty">No accounts match your search.</p>}
          <div className="mod-directory">
            {data.results.map((player) => (
              <Link key={player.id} to={`/moderation/players/${player.id}`}>
                <span className="mod-avatar" aria-hidden="true">
                  {player.username.slice(0, 1).toUpperCase()}
                </span>
                <span>
                  <strong className="mod-player-name">
                    <PlayerIdentity username={'@' + player.username} title={player.title} />
                    {player.closed && <span className="mod-chip closed">Closed</span>}
                  </strong>
                  <small>
                    {player.display_name || 'Player'} · {player.rating} Elo
                  </small>
                </span>
                <span className="mod-chip">{player.protected ? 'Staff' : 'Player'}</span>
                <span aria-hidden="true">→</span>
              </Link>
            ))}
          </div>
          <Pager page={page} next={data.next} previous={data.previous} change={setPage} />
        </section>
      )}
    </>
  );
}
