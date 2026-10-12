import { Link, Navigate, useParams } from 'react-router-dom';
import { Badge, PageHeading } from '../components/ui';
import { modes } from '../modes';

export function Mode() {
  const { modeId } = useParams();
  const mode = modes.find((item) => item.id === modeId);
  if (!mode)
    return (
      <PageHeading eyebrow="NOT FOUND" title="That mode is off the grid.">
        <Link to="/">Back to the homepage</Link>
      </PageHeading>
    );
  if (mode.id === 'party') return <Navigate to="/party/new" replace />;
  if (mode.id === 'singleplayer') return <Navigate to="/singleplayer" replace />;
  return (
    <>
      <PageHeading eyebrow={mode.eyebrow} title={mode.label}>
        {mode.description}
      </PageHeading>
      <section className={`panel mode-detail ${mode.className}`}>
        <Badge>Coming later</Badge>
        <h2>How it will work</h2>
        <ul className="rules-list">
          {mode.rules.map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
        </ul>
        <p className="muted">
          Every image starts fully covered. Random tiles disappear over 30 seconds. Multiplayer
          results will be decided by the server.
        </p>
        <button className="button" disabled>
          Gameplay is not available yet
        </button>
      </section>
      <Link className="back-link" to="/">
        ← Explore all modes
      </Link>
    </>
  );
}
