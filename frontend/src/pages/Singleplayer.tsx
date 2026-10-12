import { useCallback, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/context';
import { Reveal } from '../games/Reveal';
import { useSingleplayer } from '../games/useSingleplayer';

export function Singleplayer() {
  const game = useSingleplayer();
  const { user } = useAuth();
  const [text, setText] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const focusResult = useCallback((node: HTMLHeadingElement | null) => {
    node?.focus();
  }, []);
  const { round, session } = game;
  const full = !!round && round.revealed_count === round.total_tiles;
  const final = session?.status === 'complete';
  const expired = session?.status === 'expired';
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (text.trim() && (await game.guess(text.trim()))) setText('');
    input.current?.focus();
  };
  const begin = async (next = false) => {
    if (await (next ? game.next() : game.start())) setText('');
    input.current?.focus();
  };
  return (
    <section className="singleplayer-page" aria-labelledby="game-title">
      <header className="game-heading">
        <div>
          <h1 id="game-title">Singleplayer</h1>
          <p className="game-subtitle">
            {session
              ? `Round ${session.current_round_number} of ${session.total_rounds}`
              : '5 rounds · 45-second reveals'}
          </p>
        </div>
        <div className="session-heading-stats">
          <span className="muted">{user ? user.display_name || user.username : 'Guest'}</span>
          {!final && (
            <dl>
              <dt>Total Score</dt>
              <dd>
                {session?.total_score ?? 0} <span>/ 5,000</span>
              </dd>
            </dl>
          )}
        </div>
      </header>
      {game.connection && (
        <div className="service-banner" role="status">
          {game.connection} Progress is saved.{' '}
          <button onClick={() => void game.reconnect()}>Reconnect</button>
        </div>
      )}
      {final && session ? (
        <section className="panel final-results" aria-labelledby="final-title">
          <h2 id="final-title" ref={focusResult} tabIndex={-1}>
            Final Results
          </h2>
          <p className="final-score" aria-label="Final score">
            {session.total_score.toLocaleString()} <span>/ 5,000</span>
          </p>
          <p className="muted">Solved {session.solved_rounds} of 5 rounds</p>
          <table className="results-table">
            <caption className="sr-only">Round results</caption>
            <thead>
              <tr>
                <th>Round</th>
                <th>Result</th>
                <th>Answer</th>
                <th>Points</th>
              </tr>
            </thead>
            <tbody>
              {session.rounds.map((item) => (
                <tr key={item.number}>
                  <td>{item.number}</td>
                  <td>{item.outcome === 'solved' ? 'Solved' : 'Forfeited'}</td>
                  <td>{item.answer}</td>
                  <td>{item.score}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="final-actions">
            <button className="button" disabled={game.busy} onClick={() => void begin()}>
              {game.busy ? 'Starting…' : 'Play Again'}
            </button>
            <Link className="button secondary" to="/">
              Return Home
            </Link>
          </div>
        </section>
      ) : (
        <>
          {session && (
            <ol className="session-progress" aria-label="Session progress">
              {session.rounds.map((item) => (
                <li
                  key={item.number}
                  className={`step-${item.outcome}`}
                  aria-current={item.number === session.current_round_number ? 'step' : undefined}
                >
                  <span>{item.number}</span>
                  <span>
                    {item.outcome === 'solved'
                      ? `${item.score} pts`
                      : item.outcome === 'forfeited'
                        ? 'Forfeited'
                        : item.number === session.current_round_number
                          ? 'Current'
                          : 'Pending'}
                  </span>
                </li>
              ))}
            </ol>
          )}
          <div className="game-layout">
            <div className="picture-panel">
              <div className="picture-toolbar">
                <span>
                  {round?.completion ? 'Round complete' : full ? 'Fully revealed' : 'Image reveal'}
                </span>
                <span className="timer-label">
                  Time Remaining{' '}
                  <strong
                    className={`game-clock ${game.seconds <= 5 && round?.status === 'active' ? 'last-seconds' : ''}`}
                    aria-label="Time Remaining"
                  >
                    {round?.status === 'active' ? game.seconds : round?.completion ? 0 : 45}s
                  </strong>
                </span>
              </div>
              <Reveal round={expired ? null : round} />
              <div
                className="reveal-progress"
                role="progressbar"
                aria-label="Image revealed"
                aria-valuemin={0}
                aria-valuemax={round?.total_tiles ?? 400}
                aria-valuenow={round?.revealed_count ?? 0}
              >
                <span
                  style={{
                    width: `${round ? (round.revealed_count / round.total_tiles) * 100 : 0}%`,
                  }}
                />
              </div>
              <div className="picture-caption">
                <span>
                  {round && !expired
                    ? `${round.revealed_count} / ${round.total_tiles} tiles`
                    : '20 × 20 tiles'}
                </span>
                <span>Unlimited guesses</span>
              </div>
            </div>
            <aside className="guess-panel">
              {game.loading ? (
                <div role="status">
                  <h2>Loading game…</h2>
                </div>
              ) : expired ? (
                <>
                  <h2>Game expired</h2>
                  <p>Your completed round scores are saved. Start a new five-round game.</p>
                  <button
                    className="button game-button"
                    disabled={game.busy}
                    onClick={() => void begin()}
                  >
                    Start Game
                  </button>
                </>
              ) : round?.completion && session ? (
                <div role="status" className="round-result">
                  <p className="eyebrow">Round {round.number} of 5</p>
                  <h2 tabIndex={-1} ref={focusResult}>
                    {round.status === 'forfeited' ? 'Forfeited' : 'Correct'}
                  </h2>
                  <p className="result-answer">{round.completion.answer}</p>
                  <dl className="round-stats">
                    <div>
                      <dt>Points earned</dt>
                      <dd>{round.score}</dd>
                    </div>
                    <div>
                      <dt>Total Score</dt>
                      <dd>{session.total_score}</dd>
                    </div>
                  </dl>
                  <button
                    className="button game-button"
                    disabled={game.busy}
                    onClick={() => void begin(true)}
                  >
                    {game.busy ? 'Starting…' : 'Next Round'}
                  </button>
                  <details className="image-credit">
                    <summary>Image credit</summary>
                    <p>
                      {round.completion.category} · {round.completion.license}
                    </p>
                    <p>{round.completion.attribution}</p>
                  </details>
                </div>
              ) : round?.status === 'active' ? (
                <>
                  <form className="guess-form" onSubmit={(event) => void submit(event)}>
                    <label htmlFor="guess">Your Guess</label>
                    <input
                      ref={input}
                      id="guess"
                      name="guess"
                      value={text}
                      onChange={(event) => setText(event.target.value)}
                      placeholder="Enter a guess"
                      maxLength={120}
                      autoComplete="off"
                      autoFocus
                      aria-describedby="guess-help guess-feedback"
                    />
                    <button className="button game-button" disabled={game.busy || !text.trim()}>
                      {game.busy ? 'Checking…' : 'Submit Guess'}
                    </button>
                  </form>
                  <p id="guess-help" className="guess-help">
                    No penalty or cooldown for incorrect guesses.
                  </p>
                  <p id="guess-feedback" className="guess-feedback concise-feedback" role="status">
                    {game.feedback ||
                      (full
                        ? 'Fully revealed. Correct guesses now earn 0 points.'
                        : 'Points decrease as tiles are revealed.')}
                  </p>
                  {round.can_forfeit && (
                    <button
                      className="button secondary forfeit-button"
                      disabled={game.busy}
                      onClick={() => void game.forfeit()}
                    >
                      Forfeit Round
                    </button>
                  )}
                  <div className="guess-tally">
                    <span>Guesses</span>
                    <strong>{round.guess_count}</strong>
                  </div>
                </>
              ) : (
                <>
                  <h2>{game.empty ? 'No images available' : 'Start a game'}</h2>
                  <p>
                    {game.empty
                      ? 'No approved hosted images are ready. Images must be reviewed before play.'
                      : 'Five rounds. Up to 1,000 points per round. Guess sooner to score more.'}
                  </p>
                  <button
                    className="button game-button"
                    disabled={game.busy}
                    onClick={() => void begin()}
                  >
                    {game.busy ? 'Starting…' : game.empty ? 'Check Again' : 'Start Game'}
                  </button>
                  {game.empty && (
                    <Link className="back-link" to="/submit">
                      Contribute an image
                    </Link>
                  )}
                  <p className="guess-help">Guest play is available without an account.</p>
                </>
              )}
              {game.error && !game.empty && (
                <p className="message error" role="alert">
                  {game.error}
                </p>
              )}
            </aside>
          </div>
        </>
      )}
      {final && game.error && (
        <p className="message error" role="alert">
          {game.error}
        </p>
      )}
      <div className="game-bottom">
        {!final && (
          <Link className="back-link" to="/">
            Return Home
          </Link>
        )}
        <p>Progress is saved in this browser session.</p>
      </div>
    </section>
  );
}
