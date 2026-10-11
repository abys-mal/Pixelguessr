import { useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/context';
import { Badge } from '../components/ui';
import { Reveal } from '../games/Reveal';
import { useSingleplayer } from '../games/useSingleplayer';

export function Singleplayer() {
  const game = useSingleplayer();
  const { user } = useAuth();
  const [text, setText] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const { round } = game;
  const full = !!round && round.revealed_count === round.total_tiles;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!text.trim()) return;
    if (await game.guess(text.trim())) setText('');
    input.current?.focus();
  };
  const start = async () => {
    await game.start();
    setText('');
    input.current?.focus();
  };
  return (
    <section className="singleplayer-page" aria-labelledby="game-title">
      <header className="game-heading">
        <div>
          <p className="eyebrow">SOLO DISCOVERY</p>
          <h1 id="game-title">
            Find the bigger picture<span className="brand-dot">.</span>
          </h1>
        </div>
        <Badge tone="mint">{user ? user.display_name || user.username : 'Guest play'}</Badge>
      </header>
      {game.connection && (
        <div className="service-banner" role="status">
          {game.connection} Your round stays saved.{' '}
          <button onClick={() => void game.reconnect()}>Reconnect</button>
        </div>
      )}
      <div className="game-layout">
        <div className="picture-panel">
          <div className="picture-toolbar">
            <span>
              <span className="mint-dot" />{' '}
              {round?.status === 'solved'
                ? 'Picture found'
                : full
                  ? 'Fully revealed'
                  : 'One tile at a time'}
            </span>
            <span
              className={`game-clock ${game.seconds <= 5 ? 'last-seconds' : ''}`}
              aria-label="Reveal countdown"
            >
              {round?.status === 'active' ? `${game.seconds}s` : '30s reveal'}
            </span>
          </div>
          <Reveal round={round?.status === 'expired' ? null : round} />
          <div
            className="reveal-progress"
            role="progressbar"
            aria-label="Image revealed"
            aria-valuemin={0}
            aria-valuemax={round?.total_tiles ?? 400}
            aria-valuenow={round?.revealed_count ?? 0}
          >
            <span
              style={{ width: `${round ? (round.revealed_count / round.total_tiles) * 100 : 0}%` }}
            />
          </div>
          <div className="picture-caption">
            <span>
              {round
                ? `${round.revealed_count} / ${round.total_tiles} tiles`
                : 'A fresh perspective awaits.'}
            </span>
            <span>Curated images · unlimited guesses</span>
          </div>
        </div>
        <aside className={`guess-panel ${round?.status === 'solved' ? 'solved-panel' : ''}`}>
          {game.loading ? (
            <div role="status">
              <p className="eyebrow">GETTING READY</p>
              <h2>Finding your perspective…</h2>
              <p>Checking for your saved round.</p>
            </div>
          ) : round?.status === 'solved' && round.completion ? (
            <div className="celebration" role="status">
              <div className="success-mark" aria-hidden="true">
                ✦
              </div>
              <p className="eyebrow">YOU FOUND IT</p>
              <h2>{round.completion.answer}</h2>
              <p>A little instinct goes a long way.</p>
              <dl className="round-stats">
                <div>
                  <dt>Time to solve</dt>
                  <dd>{round.completion.solved_in_seconds.toFixed(1)}s</dd>
                </div>
                <div>
                  <dt>Guesses</dt>
                  <dd>{round.completion.guesses}</dd>
                </div>
              </dl>
              <button
                className="button game-button"
                onClick={() => void start()}
                disabled={game.busy}
              >
                {game.busy ? 'Preparing…' : 'Play Again'} <span aria-hidden="true">↗</span>
              </button>
              <details className="image-credit">
                <summary>About this picture</summary>
                <p>
                  {round.completion.category} · {round.completion.license}
                </p>
                <p>{round.completion.attribution}</p>
              </details>
            </div>
          ) : round?.status === 'active' ? (
            <>
              <p className="eyebrow">TRUST YOUR INSTINCT</p>
              <h2>What do you see?</h2>
              <p>
                {full
                  ? 'The whole picture is yours. Keep guessing until you find it.'
                  : 'Watch the clues unfold. You can guess as often as you like.'}
              </p>
              <form onSubmit={(event) => void submit(event)} className="guess-form">
                <label htmlFor="guess">Your guess</label>
                <input
                  ref={input}
                  id="guess"
                  name="guess"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Name the picture…"
                  maxLength={120}
                  autoComplete="off"
                  autoFocus
                  aria-describedby="guess-help guess-feedback"
                />
                <button className="button game-button" disabled={game.busy || !text.trim()}>
                  {game.busy ? 'Checking…' : 'Submit guess'} <span aria-hidden="true">↗</span>
                </button>
              </form>
              <p id="guess-help" className="guess-help">
                Enter to submit. No penalties. No cooldown.
              </p>
              <div id="guess-feedback" className="guess-feedback" role="status" aria-live="polite">
                {game.feedback ||
                  (full
                    ? 'All tiles revealed. Take your time.'
                    : 'Your next guess could be the one.')}
              </div>
              <div className="guess-tally">
                <span>Guesses made</span>
                <strong>{round.guess_count}</strong>
              </div>
            </>
          ) : (
            <>
              <p className="eyebrow">
                {game.empty
                  ? 'MORE PICTURES SOON'
                  : round?.status === 'expired'
                    ? 'A FRESH START'
                    : 'A MOMENT OF DISCOVERY'}
              </p>
              <h2>
                {game.empty
                  ? 'The library is waiting.'
                  : round?.status === 'expired'
                    ? 'This round has expired.'
                    : 'Ready to see it?'}
              </h2>
              <p>
                {game.empty
                  ? 'There are no approved images ready to play. Every picture needs a review before joining the game.'
                  : round?.status === 'expired'
                    ? 'Start another picture and find a new perspective.'
                    : 'A hidden image. Thirty seconds of clues. All the guesses you need.'}
              </p>
              <button
                className="button game-button"
                disabled={game.busy}
                onClick={() => void start()}
              >
                {game.busy ? 'Preparing…' : game.empty ? 'Check again' : 'Start a round'}{' '}
                <span aria-hidden="true">↗</span>
              </button>
              <div className="game-instructions">
                <span>01</span>
                <p>Tiles disappear in a random order.</p>
                <span>02</span>
                <p>Guess the picture. Spelling alternatives are welcome.</p>
                <span>03</span>
                <p>Keep guessing after the full reveal.</p>
              </div>
              {game.empty && (
                <Link className="back-link" to="/submit">
                  Contribute an image ↗
                </Link>
              )}
            </>
          )}
          {game.error && !game.empty && (
            <p className="message error" role="alert">
              {game.error}
            </p>
          )}
        </aside>
      </div>
      <div className="game-bottom">
        <Link to="/" className="back-link">
          ← All modes
        </Link>
        <p>
          {user
            ? 'Your round is saved in this browser session.'
            : 'No account needed. Your round is saved in this browser session.'}
        </p>
      </div>
    </section>
  );
}
