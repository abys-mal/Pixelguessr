import { Link } from 'react-router-dom';
import { SanctionBanner } from '../components/SanctionBanner';
import { modes } from '../modes';
import { useAuth } from '../auth/context';
import { RankIcon } from '../components/RankIcon';
import { StatusMessage } from '../components/ui';
import './home.css';

export function Home() {
  const { user, loading } = useAuth();
  if (loading) return <StatusMessage>Loading your game dashboard…</StatusMessage>;
  if (user)
    return (
      <div className="home-dashboard">
        <SanctionBanner />
        <header className="home-dashboard-heading">
          <p className="eyebrow">CHOOSE YOUR NEXT GAME</p>
          <h1>Play Pixelguessr</h1>
        </header>
        <section aria-label="Game modes">
          <ModeCards dashboard />
        </section>
        <section className="home-standing" aria-label="Your ranked standing">
          <div>
            <p className="eyebrow">RANKED STANDING</p>
            <p className="home-rating">
              <strong>{user.rating} Elo</strong>
              <RankIcon tier={user.ranked_tier} decorative />
              <span>{user.ranked_tier || 'Unranked'}</span>
            </p>
            <p className="field-help">
              {user.ranked_matches
                ? `${user.ranked_matches} rated duels played`
                : 'No rated duels yet. Your first match starts your history.'}
            </p>
          </div>
          <Link to="/leaderboards">View standings →</Link>
        </section>
      </div>
    );
  return (
    <div className="home-landing">
      <SanctionBanner />
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">
            <span className="tiny-grid" aria-hidden="true">
              ▦
            </span>{' '}
            A NEW PERSPECTIVE ON GUESSING
          </p>
          <h1>
            A little less pixel.
            <br />A little more <em>instinct.</em>
          </h1>
          <p className="lede">
            Identify images as scattered tiles reveal the bigger picture.
            <br className="desktop-break" /> Play at your own pace or race other players.
          </p>
          <div className="hero-actions">
            <Link className="button" to="/register">
              Create an account
            </Link>
            <Link className="button secondary" to="/singleplayer">
              Try singleplayer
            </Link>
          </div>
          <p className="field-help">
            Already playing? <Link to="/login">Sign in to your account</Link>
          </p>
        </div>
        <figure className="reveal-art">
          <div className="art-label">
            <span>THE BIGGER PICTURE</span>
            <span aria-hidden="true">↗</span>
          </div>
          <div className="pixel-scene" aria-hidden="true">
            <div className="sun" />
            <div className="hill far" />
            <div className="hill near" />
            <div className="tile-cover">
              {Array.from({ length: 48 }, (_, i) => (
                <i
                  key={i}
                  className={
                    [
                      2, 3, 9, 10, 16, 17, 22, 23, 24, 25, 29, 30, 31, 32, 36, 37, 38, 44, 45,
                    ].includes(i)
                      ? 'revealed'
                      : ''
                  }
                />
              ))}
            </div>
          </div>
          <figcaption>
            <span>
              <span className="mint-dot" /> A picture, one tile at a time.
            </span>
            <span>Visual concept</span>
          </figcaption>
        </figure>
      </section>
      <section aria-labelledby="modes-title" className="mode-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">CHOOSE YOUR PERSPECTIVE</p>
            <h2 id="modes-title">Three ways to see it.</h2>
          </div>
          <span className="muted">Same reveal. Different kind of thrill.</span>
        </div>
        <ModeCards />
      </section>
      <section className="foundation-strip">
        <div className="foundation-symbol" aria-hidden="true">
          ▦
        </div>
        <div>
          <p className="eyebrow">GOOD PICTURES START WITH GOOD PEOPLE</p>
          <h2>A library with a human touch.</h2>
          <p>
            Curated images. Thoughtful answers. Every submission reviewed before it joins the game.
          </p>
        </div>
        <Link className="button secondary" to="/contributions">
          Contribute an image <span aria-hidden="true">↗</span>
        </Link>
      </section>
    </div>
  );
}

function ModeCards({ dashboard = false }: { dashboard?: boolean }) {
  const Title = dashboard ? 'h2' : 'h3';
  return (
    <div className="mode-grid">
      {modes.map((mode, index) => (
        <article key={mode.id} className={`mode-card ${mode.className}`}>
          <div className="mode-card-top">
            <span className="mode-icon" aria-hidden="true">
              {mode.icon}
            </span>
          </div>
          <p className="eyebrow">{mode.eyebrow}</p>
          <Title>{mode.id === 'ranked' ? 'Ranked Duels' : mode.label}</Title>
          <p className="card-description">
            {dashboard
              ? {
                  singleplayer: 'Identify five images as their tiles reveal the picture.',
                  party: 'Create a room or join friends for a shared guessing game.',
                  ranked: 'Find an opponent and compete in a rated head-to-head match.',
                }[mode.id]
              : mode.description}
          </p>
          <p className="card-meta">
            {dashboard
              ? {
                  singleplayer: 'Five rounds · Up to 5,000 points',
                  party: 'A room for you and your friends',
                  ranked: 'One guess · First to 4 wins',
                }[mode.id]
              : mode.meta}
          </p>
          <Link
            className="mode-link"
            to={
              mode.id === 'singleplayer'
                ? '/singleplayer'
                : mode.id === 'party'
                  ? '/party/new'
                  : '/ranked'
            }
          >
            {mode.id === 'singleplayer'
              ? 'Play singleplayer'
              : mode.id === 'party'
                ? 'Create Party'
                : 'Play Ranked Duel'}{' '}
            <span aria-hidden="true">↗</span>
          </Link>
          {mode.id === 'party' && (
            <Link className="home-join-party" to="/party/join">
              Join a Party
            </Link>
          )}
          <span className="card-number" aria-hidden="true">
            0{index + 1}
          </span>
        </article>
      ))}
    </div>
  );
}
