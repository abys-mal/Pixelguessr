import { Link } from 'react-router-dom';
import { PageHeading } from '../components/ui';

export function About() {
  return (
    <>
      <PageHeading eyebrow="FIND THE BIGGER PICTURE" title="A game of seeing what’s there.">
        Pixelguessr is a curated image-guessing game. Singleplayer and private parties are ready to
        play.
      </PageHeading>
      <section className="panel prose">
        <h2>From pixels to perspective</h2>
        <p>
          Singleplayer has five rounds. Each image is revealed over 45 seconds. Correct guesses earn
          up to 1,000 points per round. After full reveal, keep guessing or forfeit for zero points.
        </p>
        <h2>Play your way</h2>
        <p>
          Play <Link to="/singleplayer">singleplayer</Link> with unlimited guesses and no penalties.
          Create a <Link to="/party/new">party</Link> to play with friends. Wrong guesses cost 50
          points and have a two-second cooldown. The host chooses the reveal duration and number of
          rounds. Play a <Link to="/ranked">ranked duel</Link>: one guess each, first to four
          decisive wins. <Link to="/">Explore the modes.</Link>
        </p>
        <h2>A thoughtfully curated library</h2>
        <p>
          Images may come from Wikimedia Commons, appropriately licensed sources, AI generation, or
          manual uploads. Every submission requires staff approval.
        </p>
        <h2>A fair place to play</h2>
        <p>
          Moderation covers Fair Play, Sportsmanship and Community Guidelines, and Platform
          Integrity. Warnings require acknowledgment before new multiplayer games or image
          contributions and expire 90 days after acknowledgment, or earlier after a successful
          appeal. Probation disables ranked duels and image submissions. Probation and suspensions
          may be temporary or indefinite. Account closure is permanent unless reversed by an
          administrator. Sanctions do not require escalation; a full appeals workflow is planned for
          a later phase.
        </p>
      </section>
    </>
  );
}
export function NotFound() {
  return (
    <>
      <PageHeading eyebrow="404" title="This tile is missing.">
        The page you’re looking for isn’t here.
      </PageHeading>
      <Link className="button" to="/">
        Back to the picture ↗
      </Link>
    </>
  );
}
