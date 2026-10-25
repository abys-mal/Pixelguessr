import { Link } from 'react-router-dom';
import { useAuth } from '../auth/context';
import { noticeDate } from './notices';
import './notices.css';

export function AccountNoticeStatus({
  compact = false,
  activeCount,
}: {
  compact?: boolean;
  activeCount?: number;
}) {
  const { restrictions } = useAuth();
  // The backend already selects the most significant attention notice.
  const notice = restrictions?.notice;
  const kind = notice?.kind ?? 'good';
  const warnings = restrictions?.unacknowledged_warnings.length || 1;
  const titles = {
    suspension: 'Suspended',
    probation: 'On probation',
    warning: `${warnings || 1} warning${warnings === 1 ? '' : 's'} need${warnings === 1 ? 's' : ''} acknowledgment`,
    good: 'Your account is in good standing.',
  };
  const descriptions = {
    suspension: 'Multiplayer and image submissions are restricted. Singleplayer remains available.',
    probation: restrictions?.unacknowledged_warnings.length
      ? 'Ranked duels and image submissions are restricted. Acknowledge active warnings before hosting or joining parties. Singleplayer remains available.'
      : 'Ranked duels and image submissions are restricted. Parties and singleplayer remain available.',
    warning:
      'Acknowledge active warnings before entering ranked duels, hosting or joining parties, or contributing images. Singleplayer remains available.',
    good: 'No active restrictions require your attention.',
  };
  return (
    <section
      className={`notice-status tone-${kind}${compact ? ' notice-summary' : ''}`}
      aria-label={compact ? 'Account notices summary' : 'Current account status'}
    >
      <span className="notice-status-icon" aria-hidden="true">
        {kind === 'good' ? '✓' : '!'}
      </span>
      <div className="notice-status-copy">
        {compact ? (
          <h2>Account notices</h2>
        ) : (
          <p className="notice-eyebrow">Current account status</p>
        )}
        {compact ? <p className="notice-status-title">{titles[kind]}</p> : <h2>{titles[kind]}</h2>}
        <p className="notice-status-description">{descriptions[kind]}</p>
        {notice && (
          <p className="notice-status-meta">
            {notice.expires_at ? (
              <>
                Expires <time dateTime={notice.expires_at}>{noticeDate(notice.expires_at)}</time>
              </>
            ) : (
              'Indefinite'
            )}
            {activeCount !== undefined && activeCount > 1 && (
              <span>
                {' '}
                · {activeCount - 1} additional active sanction{activeCount === 2 ? '' : 's'}
              </span>
            )}
          </p>
        )}
      </div>
      {compact && (
        <Link className="button secondary compact notice-summary-link" to="/account-notices">
          View account notices →
        </Link>
      )}
    </section>
  );
}
