import { Link } from 'react-router-dom';
import { root, type Overview } from './api';
import { Heading, Loading } from './components';
import { useData } from './useData';

export function ModerationHome() {
  const { data, error, reload } = useData<Overview>(root);
  if (!data) return <Loading error={error} retry={reload} />;
  return (
    <>
      <Heading
        title="A clearer community."
        detail="Review what needs attention. Keep the game welcoming."
      />
      <div className="mod-home-grid">
        <Link className="mod-count-card" to="/moderation/reports">
          <span>Reports to review</span>
          <strong>{data.pending_reports}</strong>
          <small>
            Open report inbox <span aria-hidden="true">↗</span>
          </small>
        </Link>
        <Link className="mod-count-card" to="/moderation/appeals">
          <span>Appeals to review</span>
          <strong>{data.pending_appeals}</strong>
          <small>
            Open appeal inbox <span aria-hidden="true">↗</span>
          </small>
        </Link>
      </div>
      <section className="mod-card mod-announcements">
        <p className="mod-eyebrow">STAFF UPDATES</p>
        <h2>Announcements</h2>
        <p className="mod-muted">No announcements at the moment.</p>
      </section>
      <section className="mod-home-note">
        <h2>Start with a player.</h2>
        <p>
          You can issue or reverse a sanction directly from a player profile. No report is required.
        </p>
        <Link className="mod-button subtle" to="/moderation/players">
          Find a player →
        </Link>
      </section>
    </>
  );
}
