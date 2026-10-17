import { Link } from 'react-router-dom';
import { SanctionBanner } from '../components/SanctionBanner';
import { modes } from '../modes';

export function Home() {
  return (
    <>
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
            Every tile hides a clue. Watch the picture unfold,
            <br className="desktop-break" /> connect the dots, and find the bigger picture.
          </p>
          <div className="hero-note">
            <span>Singleplayer is here. A fresh picture is waiting.</span>
          </div>
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
        <div className="mode-grid">
          {modes.map((mode, index) => (
            <article key={mode.id} className={`mode-card ${mode.className}`}>
              <div className="mode-card-top">
                <span className="mode-icon" aria-hidden="true">
                  {mode.icon}
                </span>
              </div>
              <p className="eyebrow">{mode.eyebrow}</p>
              <h3>{mode.label}</h3>
              <p className="card-description">{mode.description}</p>
              <p className="card-meta">{mode.meta}</p>
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
              <span className="card-number" aria-hidden="true">
                0{index + 1}
              </span>
            </article>
          ))}
        </div>
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
        <Link className="button secondary" to="/submit">
          Contribute an image <span aria-hidden="true">↗</span>
        </Link>
      </section>
    </>
  );
}
