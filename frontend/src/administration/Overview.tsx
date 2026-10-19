import { Link, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/context';
import { Heading, Loading } from '../moderation/components';
import { useData } from '../moderation/useData';
import { adminRoot, type AdminOverview, type AuditEntry, type HealthCheck } from './api';
import './administration.css';

export function AdministratorGate() {
  const { user } = useAuth();
  return user?.administrator ? (
    <Outlet />
  ) : (
    <section className="mod-card">
      <h1>Administrator access required</h1>
      <p>These controls are available to active administrators.</p>
      <Link to="/moderation">Return to staff Home</Link>
    </section>
  );
}
export function HealthList({ checks }: { checks: HealthCheck[] }) {
  return (
    <ul className="admin-health">
      {checks.map((check) => (
        <li key={check.name}>
          <span>{check.name}</span>
          <strong className={`health-${check.state.toLowerCase().replaceAll(' ', '-')}`}>
            {check.state}
          </strong>
        </li>
      ))}
    </ul>
  );
}
export function ActivityList({ entries }: { entries: AuditEntry[] }) {
  return (
    <ol className="mod-timeline">
      {entries.map((row) => (
        <li key={row.id}>
          <strong>{row.action.replaceAll('_', ' ')}</strong>
          <p>
            @{row.actor} · {new Date(row.created_at).toLocaleString()}
          </p>
          <small>
            {row.target_type} · {row.target_id}
          </small>
          {row.reason && <p>{row.reason}</p>}
          <details>
            <summary>Before and after</summary>
            <pre>{JSON.stringify(row.changes, null, 2)}</pre>
          </details>
        </li>
      ))}
    </ol>
  );
}
export function AdministrationOverview() {
  const { data, error, reload } = useData<AdminOverview>(adminRoot);
  if (!data) return <Loading error={error} retry={reload} />;
  const warning = data.health.some((x) => ['Unavailable', 'Degraded'].includes(x.state));
  return (
    <div className="admin-overview">
      <Heading title="Administration" detail="The game, its people, and the pictures behind it." />
      <section className="admin-summary" aria-label="Summary metrics">
        <div className="admin-metrics">
          {[
            ['Registered players', data.players],
            ['Active games', data.active_games],
            ['Approved images', data.playable_images],
            ['Pending player review', data.pending_player_submissions],
            ['Pending', data.pending_images],
            ['Incomplete imports', data.incomplete_imports],
          ].map(([name, count]) => (
            <section className="mod-card" key={name}>
              <span className="mod-muted">{name}</span>
              <strong>{count}</strong>
            </section>
          ))}
        </div>
        <p className="mod-muted">
          Image count excludes retired images and entries without a hosted file.
        </p>
      </section>
      <section className="mod-card">
        <h2>Needs Attention</h2>
        <div className="admin-attention">
          <Link to="/moderation/administration/images?status=pending">
            {data.pending_images} pending import reviews →
          </Link>
          <Link to="/moderation/administration/images?tab=submissions">
            {data.pending_player_submissions} pending player reviews →
          </Link>
          <Link to="/moderation/administration/imports">
            {data.incomplete_imports} incomplete or failed imports →
          </Link>
          <Link to="/moderation/administration/health">
            {warning ? 'Service issues detected' : 'Review system health'} →
          </Link>
        </div>
        <p className="mod-muted">{data.import_tracking_note}</p>
      </section>
      <div className="admin-columns">
        <section className="mod-card">
          <h2>Recent staff activity</h2>
          {data.recent_activity.length ? (
            <ActivityList entries={data.recent_activity} />
          ) : (
            <p className="mod-empty">No recorded activity.</p>
          )}
          <Link to="/moderation/administration/audit">View audit log →</Link>
        </section>
        <section className="mod-card">
          <h2>System status</h2>
          <HealthList checks={data.health} />
          <button className="mod-button subtle" onClick={reload}>
            Refresh overview
          </button>
        </section>
      </div>
    </div>
  );
}
