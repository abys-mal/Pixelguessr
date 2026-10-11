import { Link } from 'react-router-dom';
import { Badge, EmptyState, PageHeading } from '../components/ui';

export function Leaderboards() {
  return (
    <>
      <PageHeading eyebrow="A PLACE TO RISE" title="Leaderboards">
        A future home for the sharpest eyes in Pixelguessr.
      </PageHeading>
      <EmptyState title="The first duel is still ahead.">
        Ranked gameplay and standings arrive in Phase 2. No rankings have been generated yet.
      </EmptyState>
      <section className="panel tier-panel">
        <h2>The ranked journey</h2>
        <div className="category-list">
          {['Unranked', 'Bronze', 'Silver', 'Gold', 'Diamond'].map((tier) => (
            <Badge key={tier}>{tier}</Badge>
          ))}
        </div>
        <p className="muted">
          Elo thresholds are still to be decided. Pro, Master, and Legend are separate,
          staff-verified titles that persist until revoked or superseded.
        </p>
      </section>
    </>
  );
}
export function About() {
  return (
    <>
      <PageHeading eyebrow="FIND THE BIGGER PICTURE" title="A game of seeing what’s there.">
        Pixelguessr is a multiplayer image-guessing game in development.
      </PageHeading>
      <section className="panel prose">
        <h2>From pixels to perspective</h2>
        <p>
          Each image begins completely covered by tiles. Random tiles disappear over 30 seconds,
          eventually revealing the whole picture. Guess the subject as the clues emerge.
        </p>
        <h2>Play your way</h2>
        <p>
          Practice in singleplayer, share a round with friends in parties, or compete in ranked
          duels. <Link to="/">Explore each mode’s rules.</Link> Gameplay is scheduled for Phase 2.
        </p>
        <h2>A thoughtfully curated library</h2>
        <p>
          Images may come from Wikimedia Commons, appropriately licensed sources, AI generation, or
          manual uploads. Every submission requires staff approval.
        </p>
        <h2>A fair place to play</h2>
        <p>
          Moderation covers Fair Play, Sportsmanship and Community Guidelines, and Platform
          Integrity. Warnings require acknowledgment and expire after 90 days, or earlier after a
          successful appeal. Probation disables ranked duels and image submissions. Probation and
          suspensions may be temporary or indefinite. Account closure is permanent unless reversed
          by an administrator. Sanctions do not require escalation; a full appeals workflow is
          planned for a later phase.
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
