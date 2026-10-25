import { PlayerIdentity } from '../components/PlayerIdentity';
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../auth/context';
import { Badge, PageHeading, SignInPrompt, StatusMessage } from '../components/ui';
import { RankedReveal } from '../games/RankedReveal';
import { connectRanked, rankedApi, type ConnectionStatus, type QueueState } from '../games/ranked';
import { useRanked, useServerTime } from '../games/useRanked';
import { SanctionAccessNotice } from '../components/SanctionAccessNotice';
import { restrictedSanction } from '../components/sanctionAccess';
import { createRequestId } from '../requestId';
import './ranked-presentation.css';

export function RankedEntry() {
  const { user, loading, restrictions } = useAuth();
  if (loading) return <StatusMessage>Loading account…</StatusMessage>;
  if (!user) return <SignInPrompt feature="play Ranked Duel" />;
  const restriction = restrictedSanction(restrictions, 'ranked');
  return (
    <RankedQueue key={restriction && restriction !== 'warning' ? 'restricted' : 'available'} />
  );
}
function RankedQueue() {
  const { user, restrictions } = useAuth();
  const restriction = restrictedSanction(restrictions, 'ranked');
  const unavailable = !!restriction && restriction !== 'warning';
  const navigate = useNavigate();
  const [queue, setQueue] = useState<QueueState | null>(null);
  const [pending, setPending] = useState(!unavailable);
  const [error, setError] = useState('');
  const [connection, setConnection] = useState<ConnectionStatus>('Connecting');
  const ticket = queue?.status === 'searching' ? queue.ticket : null;
  const activeTicket = useRef<string | null>(null);
  const locked = useRef(false);
  const mounted = useRef(true);
  const receive = useCallback(
    (next: QueueState) => {
      if (!mounted.current) {
        if (next.status === 'searching' && next.ticket)
          void rankedApi.cancel(next.ticket).catch(() => {});
        return;
      }
      if (next.status === 'matched' && next.match_id) {
        activeTicket.current = null;
        navigate(`/ranked/${next.match_id}`, { replace: true });
      } else {
        activeTicket.current = next.status === 'searching' ? next.ticket : null;
        setQueue(next);
      }
    },
    [navigate],
  );
  useEffect(() => {
    if (unavailable) {
      return;
    }
    let disposed = false;
    void rankedApi
      .queue()
      .then((next) => {
        if (!disposed) receive(next);
      })
      .catch((err: Error) => {
        if (!disposed) setError(err.message);
      })
      .finally(() => {
        if (!disposed) setPending(false);
      });
    return () => {
      disposed = true;
    };
  }, [receive, unavailable]);
  useEffect(() => {
    if (!ticket) return;
    return connectRanked<QueueState>(`/ws/ranked/queue/${ticket}/`, receive, setConnection, (err) =>
      setError(err.message),
    );
  }, [ticket, receive]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const value = activeTicket.current;
      if (value) void rankedApi.cancel(value).catch(() => {});
    };
  }, []);
  const now = useServerTime(ticket ? queue?.server_now : undefined);
  const search = async () => {
    if (restriction) return;
    if (locked.current) return;
    locked.current = true;
    setPending(true);
    setError('');
    try {
      receive(await rankedApi.join(createRequestId()));
    } catch (err) {
      setError((err as Error).message);
      try {
        receive(await rankedApi.queue());
      } catch {
        /* Original error remains visible. */
      }
    } finally {
      locked.current = false;
      setPending(false);
    }
  };
  const cancel = async () => {
    if (locked.current || !ticket) return;
    locked.current = true;
    setPending(true);
    setError('');
    try {
      receive(await rankedApi.cancel(ticket));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      locked.current = false;
      setPending(false);
    }
  };
  return (
    <section className="ranked-lobby">
      <PageHeading eyebrow="ONE ON ONE" title="Ranked Duel" />
      <section className="panel ranked-queue">
        <div className="ranked-emblem" aria-hidden="true">
          ◇
        </div>
        <p className="eyebrow">YOUR RATING</p>
        <h2>{queue?.rating ?? user?.rating} Elo</h2>
        <SanctionAccessNotice feature="ranked" />

        {ticket ? (
          <>
            <h3>Finding your opponent…</h3>
            <p className="ranked-timer">
              {Math.max(0, Math.floor((now - Date.parse(queue!.queued_at!)) / 1000))}s
            </p>
            <p className="muted">
              Searching within ±{queue?.search_window} Elo · {connection}
            </p>
            <button className="button secondary" disabled={pending} onClick={() => void cancel()}>
              Cancel search
            </button>
          </>
        ) : (
          <>
            <p className="ranked-rules">
              45-second reveal · One guess per round · First to 4 decisive wins
            </p>
            <p className="ranked-wash">Wash: neither player wins the round. Play another image.</p>
            <button
              className="button"
              disabled={pending || !!restriction}
              onClick={() => void search()}
            >
              {pending ? 'Please wait…' : 'Find opponent'}
            </button>
            <p className="ranked-warning">
              Leaving an active match counts as a loss. Connection interrupted? You have 30 seconds
              to return.
            </p>
          </>
        )}
        {error && <StatusMessage error>{error}</StatusMessage>}
      </section>
      <nav className="ranked-entry-links" aria-label="Ranked lobby navigation">
        <Link to="/leaderboards">View Standings</Link>
        <Link to="/">Back to Menu</Link>
      </nav>
    </section>
  );
}
export function RankedRoute() {
  const { id } = useParams();
  const { user, loading } = useAuth();
  if (loading) return <StatusMessage>Loading account…</StatusMessage>;
  if (!user) return <SignInPrompt feature="resume Ranked Duel" />;
  return <RankedGame key={id} id={id!} />;
}
function RankedGame({ id }: { id: string }) {
  const { state, connection, error, pending, guess, leave, clock } = useRanked(id);
  const [draft, setDraft] = useState({ round: '', text: '' });
  const [confirmLeave, setConfirmLeave] = useState(false);
  const now = useServerTime(state?.status === 'complete' ? undefined : state?.server_now, clock);
  const heading = useRef<HTMLHeadingElement>(null);
  const input = useRef<HTMLInputElement | null>(null);
  const focusInput = useCallback((node: HTMLInputElement | null) => {
    input.current = node;
    if (node) node.focus({ preventScroll: true });
  }, []);
  const phase = state?.status === 'complete' ? 'complete' : state?.round?.status;
  const roundId = state?.round?.id;
  useEffect(() => {
    if (phase === 'results' || phase === 'complete' || phase === 'countdown')
      heading.current?.focus({ preventScroll: true });
  }, [phase, roundId]);
  const guessUsed = state?.round?.guessed_ids.includes(state.me_id);
  useEffect(() => {
    if (phase === 'active' && connection === 'Connected' && !guessUsed)
      input.current?.focus({ preventScroll: true });
  }, [phase, roundId, connection, guessUsed]);
  if (!state)
    return <StatusMessage error={!!error}>{error || 'Connecting to your duel…'}</StatusMessage>;
  const round = state.round;
  const me = state.players.find((p) => p.id === state.me_id)!;
  const opponent = state.players.find((p) => p.id !== state.me_id);
  const opponentGuessedIncorrectly =
    !!opponent && round?.incorrect_guess_ids?.includes(opponent.id);
  const complete = state.status === 'complete';
  const used = round?.guessed_ids.includes(me.id);
  const seconds = (date: string | null | undefined) =>
    date ? Math.max(0, Math.ceil((Date.parse(date) - now) / 1000)) : 0;
  const title = complete
    ? state.outcome === 'no_contest'
      ? 'No Contest'
      : state.winner_id === me.id
        ? 'Victory'
        : 'Defeat'
    : phase === 'countdown'
      ? 'Face to face.'
      : phase === 'results'
        ? round?.winner_id
          ? round.winner_id === me.id
            ? 'Round won!'
            : 'Opponent wins this round'
          : 'Wash'
        : `Round ${round?.number}`;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (draft.round === round?.id && draft.text.trim()) void guess(draft.text.trim());
  };
  return (
    <section
      className="ranked-game"
      onKeyDownCapture={(event) => {
        if (event.key === 'Enter' && event.repeat) {
          event.preventDefault();
          event.stopPropagation();
        }
      }}
    >
      {complete && state.message && <StatusMessage>{state.message}</StatusMessage>}
      <div className="game-heading">
        <p className="eyebrow">RANKED DUEL · FIRST TO 4</p>
        {!complete && (
          <span className="field-help" role="status">
            {connection}
          </span>
        )}
      </div>
      <div className="panel duel-scoreboard">
        {state.players.map((p) => (
          <div key={p.id} className="duel-player">
            {p.deleted ? (
              <span>Deleted player</span>
            ) : (
              <Link to={`/players/${encodeURIComponent(p.username)}`}>
                <PlayerIdentity username={p.username} title={p.title} />
              </Link>
            )}
            {!p.deleted && (
              <span className="muted">{complete ? p.rating_after : p.rating_before} Elo </span>
            )}
            <strong aria-label={`${p.username} wins`}>{p.wins}</strong>
          </div>
        ))}
        <span className="duel-vs" aria-hidden="true">
          VS
        </span>
      </div>
      <h1 className="result-heading result-focus-target" ref={heading} tabIndex={-1}>
        {title}
      </h1>
      {complete ? (
        <section className="panel duel-final">
          <p>
            {state.outcome === 'no_contest'
              ? 'Both players disconnected together. Ratings and rated-match counts are unchanged.'
              : `${state.players.find((p) => p.id === state.winner_id)?.username} wins${state.outcome === 'forfeit' ? ' by forfeit' : ''}.`}
          </p>
          <div className="duel-ratings">
            {state.players.map((p) => (
              <div key={p.id}>
                <h2>
                  <PlayerIdentity username={p.username} title={p.title} />
                </h2>
                {!p.deleted && (
                  <>
                    <p>
                      {p.rating_before} → <strong>{p.rating_after}</strong> Elo
                    </p>
                    <Badge tone={p.rating_delta! > 0 ? 'mint' : ''}>
                      {p.rating_delta! > 0 ? '+' : ''}
                      {p.rating_delta} Elo
                    </Badge>
                  </>
                )}
              </div>
            ))}
          </div>
          <div className="result-actions ranked-result-actions">
            <Link className="button" to="/ranked">
              Play Again
            </Link>
            <Link className="button secondary" to="/">
              Back to Menu
            </Link>
          </div>
        </section>
      ) : (
        <>
          {phase === 'countdown' ? (
            <div className="panel duel-countdown">
              <span className="ranked-timer">{seconds(round?.started_at)}</span>
              <p>One guess each. Make it count.</p>
            </div>
          ) : (
            <div className="ranked-play-grid">
              <div>
                <RankedReveal round={round} />
                {round?.completion && (
                  <p className="field-help">
                    {round.completion.attribution} · {round.completion.license}
                  </p>
                )}
              </div>
              <div className="panel ranked-controls">
                {phase === 'active' && (
                  <>
                    <p className="eyebrow">TIME REMAINING</p>
                    <p className="ranked-timer" aria-label="Time remaining">
                      {seconds(round?.reveal_finishes_at)}s
                    </p>
                    {used ? (
                      <StatusMessage>
                        Your guess was incorrect. Watch the reveal while your opponent guesses.
                      </StatusMessage>
                    ) : (
                      <form className="form-stack" onSubmit={submit}>
                        <label htmlFor="ranked-guess">Your one guess</label>
                        <input
                          key={roundId}
                          ref={focusInput}
                          id="ranked-guess"
                          autoComplete="off"
                          maxLength={120}
                          value={draft.round === roundId ? draft.text : ''}
                          onChange={(event) =>
                            setDraft({ round: roundId!, text: event.target.value })
                          }
                          disabled={pending || connection !== 'Connected'}
                        />
                        <button
                          className="button"
                          disabled={
                            pending ||
                            connection !== 'Connected' ||
                            draft.round !== roundId ||
                            !draft.text.trim()
                          }
                        >
                          {pending ? 'Submitting…' : 'Submit guess'}
                        </button>
                      </form>
                    )}
                    {opponentGuessedIncorrectly && (
                      <p className="field-help" role="status">
                        Your opponent guessed incorrectly!
                      </p>
                    )}
                  </>
                )}
                {phase === 'results' && (
                  <>
                    <p className="eyebrow">THE ANSWER</p>
                    <h2>{round?.completion?.answer}</h2>
                    <p className="muted">
                      {round?.winner_id
                        ? 'First correct guess takes the round.'
                        : 'No decisive winner. This image does not count toward the seven decisive rounds.'}
                    </p>
                    <p role="status">
                      {state.waiting
                        ? 'Waiting for both players to reconnect…'
                        : state.message || `Next image in ${seconds(round?.next_starts_at)}s`}
                    </p>
                  </>
                )}
              </div>
            </div>
          )}
          {state.players
            .filter((p) => !p.connected)
            .map((p) => (
              <StatusMessage key={p.id}>
                {p.username} disconnected. {seconds(p.reconnect_until)}s to return. The current
                reveal continues.
              </StatusMessage>
            ))}
          {state.message && <StatusMessage error>{state.message}</StatusMessage>}
          {confirmLeave ? (
            <div className="panel leave-confirm">
              <p>Leave this duel? Your opponent wins and Elo changes immediately.</p>
              <button
                className="button secondary"
                disabled={pending}
                onClick={() => setConfirmLeave(false)}
              >
                Stay in duel
              </button>
              <button className="button danger" disabled={pending} onClick={() => void leave()}>
                Leave match
              </button>
            </div>
          ) : (
            <button
              className="button secondary"
              disabled={pending}
              onClick={() => setConfirmLeave(true)}
            >
              Leave duel
            </button>
          )}
        </>
      )}
      {error && <StatusMessage error>{error}</StatusMessage>}
    </section>
  );
}
