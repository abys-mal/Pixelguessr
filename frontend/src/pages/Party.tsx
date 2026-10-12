import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../auth/context';
import { Reveal } from '../games/Reveal';
import { partyApi, type PartyState, type PartyScore } from '../games/parties';
import { useParty } from '../games/useParty';

function PartyLinks() {
  return (
    <nav className="party-nav" aria-label="Game modes">
      <Link to="/singleplayer">Singleplayer</Link>
      <Link to="/party/new">Create Party</Link>
      <Link to="/party/join">Join Party</Link>
    </nav>
  );
}
function SettingsFields({
  seconds,
  rounds,
  onSeconds,
  onRounds,
  disabled = false,
}: {
  seconds: number;
  rounds: number;
  onSeconds: (value: number) => void;
  onRounds: (value: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="party-settings-fields">
      <label>
        Reveal duration
        <select
          value={seconds}
          onChange={(e) => onSeconds(Number(e.target.value))}
          disabled={disabled}
        >
          {[15, 30, 45, 60].map((n) => (
            <option key={n} value={n}>
              {n} seconds
            </option>
          ))}
        </select>
      </label>
      <label>
        Number of rounds
        <select
          value={rounds}
          onChange={(e) => onRounds(Number(e.target.value))}
          disabled={disabled}
        >
          {[5, 10, 15, 20].map((n) => (
            <option key={n} value={n}>
              {n} rounds
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
function PlayingIdentity() {
  const { user } = useAuth();
  return (
    <p className="muted">
      {user
        ? `Playing as ${user.display_name || user.username}`
        : 'Your guest name is assigned automatically.'}
    </p>
  );
}
export function PartyEntry({ create = false }: { create?: boolean }) {
  const navigate = useNavigate();
  const [code, setCode] = useState('');
  const [seconds, setSeconds] = useState(30);
  const [rounds, setRounds] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const requestId = useRef(crypto.randomUUID());
  const lock = useRef(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError('');
    try {
      const state = create
        ? await partyApi.create({
            reveal_seconds: seconds,
            round_limit: rounds,
            request_id: requestId.current,
          })
        : await partyApi.join(code.trim().toUpperCase());
      navigate(`/party/${state.code}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to open this party.');
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };
  return (
    <section className="party-page">
      <PartyLinks />
      <div className="panel party-entry">
        <p className="eyebrow">Parties</p>
        <h1>{create ? 'Create Party' : 'Join Party'}</h1>
        <form onSubmit={(event) => void submit(event)}>
          <PlayingIdentity />
          {create ? (
            <SettingsFields
              seconds={seconds}
              rounds={rounds}
              onSeconds={setSeconds}
              onRounds={setRounds}
              disabled={busy}
            />
          ) : (
            <label>
              Party code
              <input
                name="code"
                className="party-code-input"
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                maxLength={6}
                minLength={6}
                pattern="[A-Za-z0-9]{6}"
                required
                autoComplete="off"
                placeholder="K7M2Q9"
              />
            </label>
          )}
          {error && (
            <p role="alert" className="message error">
              {error}
            </p>
          )}
          <button className="button" disabled={busy}>
            {busy ? 'Opening…' : create ? 'Create Party' : 'Join Party'}
          </button>
        </form>
        <p className="muted party-rules-note">
          2–12 players · Wrong guesses: −50 points, 2-second cooldown
        </p>
      </div>
    </section>
  );
}
function Leaderboard({
  players,
  me,
  round = false,
  finished = false,
}: {
  players: PartyScore[];
  me: string;
  round?: boolean;
  finished?: boolean;
}) {
  const sorted = round ? [...players].sort((a, b) => a.round_rank - b.round_rank) : players;
  return (
    <div className="party-table-wrap">
      <table className="party-leaderboard">
        <caption>{round ? 'Round ranking' : 'Overall leaderboard'}</caption>
        <thead>
          <tr>
            <th scope="col">Rank</th>
            <th scope="col">Player</th>
            <th scope="col">Round</th>
            <th scope="col">Total</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((p, index) => (
            <tr key={p.id} className={p.id === me ? 'is-me' : ''}>
              <td>{index + 1}</td>
              <th scope="row">
                <span>
                  {p.name}
                  {p.id === me ? ' (you)' : ''}
                </span>
                <small>
                  {p.left
                    ? 'Left'
                    : p.solved
                      ? 'Solved'
                      : finished
                        ? 'Unsolved'
                        : p.connected
                          ? 'Guessing'
                          : 'Disconnected'}
                </small>
              </th>
              <td>
                {p.round_score > 0 ? '+' : ''}
                {p.round_score}
              </td>
              <td>{p.total_score.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function RemovePlayerDialog({
  name,
  busy,
  remove,
  dismiss,
  restoreFocus,
  error,
}: {
  name: string;
  busy: boolean;
  remove: (ban: boolean) => Promise<boolean>;
  dismiss: () => void;
  restoreFocus: () => void;
  error: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const [ban, setBan] = useState(false);
  useEffect(() => {
    const node = dialog.current;
    if (node?.showModal) node.showModal();
    else node?.setAttribute('open', '');
    cancel.current?.focus();
    return () => {
      node?.close?.();
      restoreFocus();
    };
  }, [restoreFocus]);
  return (
    <dialog
      ref={dialog}
      className="party-remove-dialog"
      aria-labelledby="remove-player-title"
      aria-describedby="remove-player-message"
      onCancel={(event) => {
        event.preventDefault();
        dismiss();
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          dismiss();
        }
        if (event.key === 'Tab') {
          const controls = Array.from(
            event.currentTarget.querySelectorAll<HTMLElement>(
              'input:not(:disabled), button:not(:disabled)',
            ),
          );
          const first = controls[0],
            last = controls[controls.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first?.focus();
          }
        }
      }}
    >
      <h2 id="remove-player-title">Remove player?</h2>
      <p id="remove-player-message">Remove {name} from this party?</p>
      <label className="party-ban-choice">
        <input
          type="checkbox"
          checked={ban}
          onChange={(event) => setBan(event.target.checked)}
          disabled={busy}
        />
        Prevent this player from re-joining
      </label>
      {error && (
        <p role="alert" className="message error">
          {error}
        </p>
      )}
      <div className="final-actions">
        <button className="button secondary" ref={cancel} onClick={dismiss}>
          Cancel
        </button>
        <button
          className="button danger"
          disabled={busy}
          onClick={async () => {
            if (await remove(ban)) dismiss();
          }}
        >
          {busy ? 'Removing…' : 'Remove player'}
        </button>
      </div>
    </dialog>
  );
}
function Lobby({
  state,
  busy,
  settings,
  start,
  kick,
  error,
}: {
  state: PartyState;
  busy: boolean;
  settings: (value: PartyState['settings']) => Promise<boolean>;
  start: () => void;
  kick: (target: string, ban: boolean) => Promise<boolean>;
  error: string;
}) {
  const [seconds, setSeconds] = useState(state.settings.reveal_seconds);
  const [rounds, setRounds] = useState(state.settings.round_limit);
  const host = state.me_id === state.host_id;
  const [targetId, setTargetId] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const target = host
    ? state.members.find((member) => member.id === targetId && member.id !== state.host_id)
    : undefined;
  const focusLobby = useCallback((node: HTMLHeadingElement | null) => {
    heading.current = node;
    node?.focus();
  }, []);
  const restoreFocus = useCallback(() => {
    if (trigger.current?.isConnected) trigger.current.focus();
    else if (heading.current?.isConnected) heading.current.focus();
    else document.querySelector<HTMLElement>('.party-page .result-focus-target')?.focus();
  }, []);
  return (
    <div className="party-lobby">
      {target && (
        <RemovePlayerDialog
          key={target.id}
          name={target.name}
          busy={busy}
          remove={(ban) => kick(target.id, ban)}
          dismiss={() => setTargetId(null)}
          restoreFocus={restoreFocus}
          error={error}
        />
      )}
      <section className="panel">
        <h2 className="result-focus-target" ref={focusLobby} tabIndex={-1}>
          Lobby <span className="muted">{state.members.length} / 12</span>
        </h2>
        <ul className="party-members">
          {state.members.map((member) => (
            <li key={member.id}>
              <span
                className={`presence-dot ${member.connected ? 'online' : ''}`}
                aria-hidden="true"
              />
              <strong>
                {member.name}
                {member.id === state.me_id ? ' (you)' : ''}
              </strong>
              {member.id === state.host_id && <span className="party-host">Host</span>}
              <small>{member.connected ? 'Connected' : 'Reconnecting'}</small>
              {host && member.id !== state.host_id && (
                <button
                  type="button"
                  className="party-kick"
                  aria-label={`Remove ${member.name}`}
                  disabled={busy}
                  onClick={(event) => {
                    trigger.current = event.currentTarget;
                    setTargetId(member.id);
                  }}
                >
                  <span aria-hidden="true">×</span>
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>
      <section className="panel">
        <h2>Game settings</h2>
        {host ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void settings({ reveal_seconds: seconds, round_limit: rounds });
            }}
          >
            <SettingsFields
              seconds={seconds}
              rounds={rounds}
              onSeconds={setSeconds}
              onRounds={setRounds}
              disabled={busy}
            />
            <button
              className="button secondary"
              disabled={
                busy ||
                (seconds === state.settings.reveal_seconds && rounds === state.settings.round_limit)
              }
            >
              Save Settings
            </button>
          </form>
        ) : (
          <dl className="party-setting-summary">
            <dt>Reveal duration</dt>
            <dd>{state.settings.reveal_seconds} seconds</dd>
            <dt>Number of rounds</dt>
            <dd>{state.settings.round_limit}</dd>
          </dl>
        )}
        <p className="party-rules-note">
          Wrong guesses cost 50 points and have a 2-second cooldown.
        </p>
        {host ? (
          <>
            <button
              className="button game-button"
              onClick={start}
              disabled={busy || state.members.length < 2}
            >
              {busy ? 'Starting…' : 'Start Game'}
            </button>
            {state.members.length < 2 && <p className="muted">Invite one more player to start.</p>}
          </>
        ) : (
          <p role="status" className="waiting-message">
            Waiting for {state.members.find((m) => m.id === state.host_id)?.name || 'a host'} to
            start.
          </p>
        )}
      </section>
    </div>
  );
}
const focusHeading = (node: HTMLHeadingElement | null) => node?.focus();
export function PartyRoute() {
  const { code } = useParams();
  return <PartyGame key={code} />;
}
export function PartyGame() {
  const { code: rawCode = '' } = useParams();
  const code = rawCode.toUpperCase();
  const game = useParty(code);
  const navigate = useNavigate();
  const [guessDraft, setGuessDraft] = useState({ roundId: '', text: '' });
  const [copied, setCopied] = useState(false);
  const input = useRef<HTMLInputElement | null>(null);
  const focusGuess = useCallback((node: HTMLInputElement | null) => {
    input.current = node;
    node?.focus();
  }, []);
  const state = game.state;
  const round = state?.round;
  const guess = guessDraft.roundId === round?.id ? guessDraft.text : '';
  const countdown = round
    ? Math.max(
        0,
        Math.ceil(
          (Date.parse(
            round.status === 'countdown'
              ? round.started_at
              : round.status === 'results'
                ? round.next_starts_at || round.reveal_finishes_at
                : round.reveal_finishes_at,
          ) -
            game.now) /
            1000,
        ),
      )
    : 0;
  const cooldown = round?.me.cooldown_until
    ? Math.max(0, Math.ceil((Date.parse(round.me.cooldown_until) - game.now) / 1000))
    : 0;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const submittedInput = input.current;
    const submittedRound = round?.id;
    if (guess.trim() && (await game.guess(guess.trim())))
      setGuessDraft((previous) =>
        previous.roundId === submittedRound ? { ...previous, text: '' } : previous,
      );
    if (submittedInput?.isConnected) submittedInput.focus();
  };
  const invite = `${window.location.origin}/party/${code}`;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(invite);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  if (game.loading)
    return (
      <section className="party-page">
        <PartyLinks />
        <p role="status">Loading party…</p>
      </section>
    );
  if (game.joinNeeded)
    return (
      <section className="party-page">
        <PartyLinks />
        <div className="panel party-entry">
          <h1>Join Party {code}</h1>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void game.join();
            }}
          >
            <PlayingIdentity />
            <button className="button" disabled={game.busy}>
              Join Party
            </button>
            {game.error && (
              <p role="alert" className="message error">
                {game.error}
              </p>
            )}
          </form>
        </div>
      </section>
    );
  if (!state)
    return (
      <section className="party-page">
        <PartyLinks />
        <div className="panel">
          <h1 className="result-focus-target" ref={focusHeading} tabIndex={-1}>
            {['party_removed', 'party_banned'].includes(game.accessCode)
              ? 'Removed from party'
              : 'Party unavailable'}
          </h1>
          <p role="alert">{game.error || 'Create a party or check your invite code.'}</p>
          <Link className="button" to="/">
            Return Home
          </Link>
          <Link className="button secondary" to="/party/join">
            Join a Party
          </Link>
        </div>
      </section>
    );
  if (state.status === 'aborted' || state.status === 'closed')
    return (
      <section className="party-page">
        <PartyLinks />
        <section className="panel final-results">
          <h1 className="result-focus-target" ref={focusHeading} tabIndex={-1}>
            {state.status === 'aborted' ? 'Match ended' : 'Party closed'}
          </h1>
          <p role="status">{state.end_message || 'This party has ended.'}</p>
          <Link className="button" to="/">
            Return Home
          </Link>
        </section>
      </section>
    );
  return (
    <section
      className="party-page"
      onKeyDownCapture={(event) => {
        if (event.key === 'Enter' && event.repeat) event.preventDefault();
      }}
    >
      <PartyLinks />
      <header className="game-heading">
        <div>
          <p className="eyebrow">
            Party <span className="party-code">{code}</span>
          </p>
          <h1>
            {state.status === 'lobby'
              ? 'Party lobby'
              : state.status === 'complete'
                ? 'Final standings'
                : `Round ${round?.number} of ${state.settings.round_limit}`}
          </h1>
        </div>
        <div className="party-header-actions">
          <button className="button secondary" onClick={() => void copy()}>
            {copied ? 'Link copied' : 'Copy Invite Link'}
          </button>
          <button
            className="button secondary"
            disabled={game.busy}
            onClick={async () => {
              if (await game.leave()) navigate('/party/join');
            }}
          >
            Leave Party
          </button>
        </div>
      </header>
      {state.status === 'lobby' && (
        <p className="party-invite">
          <a href={invite}>{invite}</a>
        </p>
      )}
      {!game.connection && (
        <p className="service-banner" role="status">
          Reconnecting… Your progress is saved.
        </p>
      )}
      {game.error && (
        <p role="alert" className="message error">
          {game.error}
        </p>
      )}
      {state.message && (
        <p role="alert" className="message error">
          {state.message} The party will retry automatically.
        </p>
      )}
      {state.status === 'lobby' ? (
        <Lobby
          key={`${state.host_id}:${state.settings.reveal_seconds}:${state.settings.round_limit}`}
          state={state}
          busy={game.busy}
          settings={game.settings}
          start={() => void game.action('start')}
          kick={game.kick}
          error={game.error}
        />
      ) : state.status === 'complete' ? (
        <section className="panel final-results">
          <h2 className="result-focus-target" ref={focusHeading} tabIndex={-1}>
            Final Results
          </h2>
          <p className="party-winner">
            {state.winners.length > 1 ? 'Tied winners: ' : 'Winner: '}
            {state.leaderboard
              .filter((p) => state.winners.includes(p.id))
              .map((p) => p.name)
              .join(', ')}
          </p>
          <Leaderboard players={state.leaderboard} me={state.me_id} finished />
          <div className="final-actions">
            <button
              className="button"
              disabled={game.busy}
              onClick={() => void game.action('lobby')}
            >
              Return to Lobby
            </button>
            <Link className="button secondary" to="/party/new">
              Create Another Party
            </Link>
          </div>
        </section>
      ) : (
        round && (
          <>
            <div className="game-layout">
              <section className="picture-panel">
                <div className="picture-toolbar">
                  <span>
                    {round.status === 'countdown'
                      ? 'Starting soon'
                      : round.status === 'results'
                        ? 'Round complete'
                        : 'Image reveal'}
                  </span>
                  <strong
                    className="game-clock"
                    aria-label={round.status === 'countdown' ? 'Start countdown' : 'Time Remaining'}
                  >
                    {round.status === 'results' ? '0' : countdown}s
                  </strong>
                </div>
                <Reveal round={round} />
                <div
                  className="reveal-progress"
                  role="progressbar"
                  aria-label="Image revealed"
                  aria-valuemin={0}
                  aria-valuemax={round.total_tiles}
                  aria-valuenow={round.revealed_count}
                >
                  <span style={{ width: `${(round.revealed_count / round.total_tiles) * 100}%` }} />
                </div>
                <div className="picture-caption">
                  <span>
                    {round.revealed_count} / {round.total_tiles} tiles
                  </span>
                  <span>{state.settings.reveal_seconds}-second reveal</span>
                </div>
              </section>
              <aside className="guess-panel">
                {round.status === 'countdown' ? (
                  <div key={`${round.id}:countdown`}>
                    <h2 className="result-focus-target" ref={focusHeading} tabIndex={-1}>
                      Get ready
                    </h2>
                    <p className="party-start-count" role="status">
                      {countdown || 'Starting…'}
                    </p>
                  </div>
                ) : round.status === 'results' ? (
                  <div key={`${round.id}:results`}>
                    <h2 className="result-focus-target" ref={focusHeading} tabIndex={-1}>
                      Round {round.number} results
                    </h2>
                    <p className="result-answer">{round.completion?.answer}</p>
                    <p role="status" className="waiting-message">
                      {round.number === state.settings.round_limit
                        ? 'Final standings'
                        : 'Next round'}{' '}
                      in {countdown}s
                    </p>
                    <details className="image-credit">
                      <summary>Image credit</summary>
                      <p>
                        {round.completion?.category} · {round.completion?.license}
                      </p>
                      <p>{round.completion?.attribution}</p>
                    </details>
                  </div>
                ) : round.me.solved ? (
                  <div key={`${round.id}:solved`}>
                    <h2 className="result-focus-target" ref={focusHeading} tabIndex={-1}>
                      Correct!
                    </h2>
                    <p role="status">Waiting for the round to end.</p>
                    <p className="party-earned">
                      {round.me.round_score} <span>round points</span>
                    </p>
                  </div>
                ) : (
                  <>
                    <form className="guess-form" onSubmit={(event) => void submit(event)}>
                      <label htmlFor="party-guess">Your Guess</label>
                      <input
                        key={round.id}
                        ref={focusGuess}
                        id="party-guess"
                        value={guess}
                        onChange={(event) =>
                          setGuessDraft({ roundId: round.id, text: event.target.value })
                        }
                        maxLength={120}
                        autoComplete="off"
                        placeholder="Enter a guess"
                        aria-describedby="party-feedback"
                      />
                      <button
                        className="button game-button"
                        disabled={game.busy || cooldown > 0 || !guess.trim()}
                      >
                        {game.busy ? 'Checking…' : cooldown ? `Wait ${cooldown}s` : 'Submit Guess'}
                      </button>
                    </form>
                    <p id="party-feedback" role="status" className="guess-feedback">
                      {game.feedback || 'Wrong guesses cost 50 points.'}
                    </p>
                    <p className="muted">Round score: {round.me.round_score}</p>
                  </>
                )}
              </aside>
            </div>
            {round.status === 'results' && (
              <section className="panel party-round-ranking">
                <Leaderboard players={state.leaderboard} me={state.me_id} round finished />
              </section>
            )}
            {round.status !== 'results' && (
              <p className="party-solved-status" role="status">
                {state.leaderboard.filter((player) => !player.left && player.solved).length} of{' '}
                {state.leaderboard.filter((player) => !player.left).length} players solved
              </p>
            )}
            {round.status === 'results' && (
              <section className="panel party-overall">
                <Leaderboard players={state.leaderboard} me={state.me_id} finished />
              </section>
            )}
          </>
        )
      )}
    </section>
  );
}
