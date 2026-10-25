import { Link } from 'react-router-dom';
import { useAuth } from '../auth/context';
import { restrictedSanction, type SanctionFeature } from './sanctionAccess';
import './notices.css';

export function SanctionAccessNotice({ feature }: { feature: SanctionFeature }) {
  const { restrictions } = useAuth();
  const kind = restrictedSanction(restrictions, feature);
  if (!kind) return null;
  const title = {
    warning: 'Warning acknowledgment required',
    probation: 'On probation',
    suspension: 'Account suspended',
    closed: 'Account closed',
  }[kind];
  const activity = {
    ranked: 'New ranked duels are unavailable.',
    party: 'Hosting or joining a party is unavailable.',
    contributions:
      'New image submissions are unavailable. You can still review your contribution history.',
  }[feature];
  const expires = restrictions?.notice?.kind === kind ? restrictions.notice.expires_at : null;
  return (
    <aside
      className={`sanction-access-notice tone-${kind}`}
      role="alert"
      aria-label="Account restriction"
    >
      <span className="sanction-access-mark" aria-hidden="true">
        !
      </span>
      <div>
        <h3>{title}</h3>
        <p>{activity}</p>
        <p>
          {kind === 'warning'
            ? 'Acknowledge all active warnings to continue. Ongoing games can finish.'
            : 'Review the sanction details and available appeal options in Account Notices.'}
        </p>
        {kind !== 'warning' && !!restrictions?.unacknowledged_warnings.length && (
          <p>Your active warnings also need acknowledgment.</p>
        )}
        <small>
          {kind === 'warning'
            ? 'Expires 90 days after acknowledgment.'
            : expires
              ? `Expires ${new Date(expires).toLocaleString()}`
              : kind === 'closed'
                ? 'Permanent account closure.'
                : 'Indefinite — remains active until reversed.'}
        </small>
        <Link to="/account-notices">View account notices</Link>
      </div>
    </aside>
  );
}
