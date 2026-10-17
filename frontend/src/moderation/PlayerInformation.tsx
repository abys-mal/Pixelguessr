import { useState } from 'react';
import type { Player } from './api';

export function PlayerInformation({ player }: { player: Player }) {
  const [copyStatus, setCopyStatus] = useState('');
  return (
    <section className="mod-card" aria-labelledby={`player-information-${player.id}`}>
      <h2 id={`player-information-${player.id}`}>Player Information</h2>
      <dl className="mod-player-information">
        <div>
          <dt>Username</dt>
          <dd>@{player.username}</dd>
        </div>
        <div>
          <dt>Display name</dt>
          <dd>{player.display_name || 'Not set'}</dd>
        </div>
        <div className="player-information-uuid">
          <dt>User UUID</dt>
          <dd>
            <code>{player.id}</code>
            <button
              className="mod-button subtle"
              type="button"
              aria-label="Copy user UUID"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(player.id);
                  setCopyStatus('UUID copied.');
                } catch {
                  setCopyStatus('Copy unavailable. Select and copy the UUID above.');
                }
              }}
            >
              Copy
            </button>
            <span role="status">{copyStatus}</span>
          </dd>
        </div>
        <div>
          <dt>Created (UTC, exact)</dt>
          <dd>
            <time dateTime={player.date_joined}>{player.date_joined}</time>
          </dd>
        </div>
        <div>
          <dt>Account status</dt>
          <dd>{player.statuses?.join(' · ') ?? 'Unavailable'}</dd>
        </div>
        <div>
          <dt>Player role</dt>
          <dd>{player.role ?? 'Unavailable'}</dd>
        </div>
        <div>
          <dt>Current Elo</dt>
          <dd>{player.rating}</dd>
        </div>
        {player.ranked_matches !== undefined && (
          <div>
            <dt>Rated matches</dt>
            <dd>
              {player.ranked_matches} played · {player.ranked_wins} wins · {player.ranked_losses}{' '}
              losses
            </dd>
          </div>
        )}
      </dl>
    </section>
  );
}
