import { Link } from 'react-router-dom';
import { useAuth } from '../auth/context';

export function SanctionBanner() {
  const { restrictions } = useAuth();
  const notice = restrictions?.notice;
  if (!notice) return null;
  return (
    <aside className={`sanction-banner ${notice.kind}`} aria-label="Account notice" role="status">
      <span className="sanction-banner-mark" aria-hidden="true">
        !
      </span>
      <div>
        <h2>
          {notice.kind === 'suspension'
            ? 'Multiplayer suspension'
            : notice.kind === 'probation'
              ? 'Account probation'
              : 'Account warning'}
        </h2>
        <p>{notice.message}</p>
        {notice.expires_at && <small>Expires {new Date(notice.expires_at).toLocaleString()}</small>}
      </div>
      <Link to="/account-notices">View details →</Link>
    </aside>
  );
}
