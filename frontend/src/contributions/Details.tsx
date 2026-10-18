import { Dialog } from '../moderation/components';
import { useData } from '../moderation/useData';
import { StatusMessage } from '../components/ui';
import { contributionRoot, statusLabel, sourceLabel, type Contribution } from './api';

export function ContributionDetails({ id, close }: { id: string; close: () => void }) {
  const { data, error, reload } = useData<Contribution>(`${contributionRoot}${id}/`);
  return (
    <Dialog title="Contribution details" close={close}>
      {!data ? (
        <>
          <StatusMessage error={!!error}>{error || 'Loading contribution…'}</StatusMessage>
          {error && (
            <button className="button secondary" onClick={reload}>
              Try again
            </button>
          )}
        </>
      ) : (
        <div className="contribution-details">
          <span className={`contribution-status ${data.status}`}>{statusLabel(data.status)}</span>
          {data.status === 'removed' ? (
            <>
              <div className="contribution-removed-placeholder" aria-hidden="true">
                ◇
              </div>
              <p>This contribution was removed by an administrator.</p>
              <p className="muted">Submitted {new Date(data.created_at).toLocaleString()}</p>
            </>
          ) : (
            <>
              {data.preview_url ? (
                <img src={data.preview_url} alt="Your private contribution" />
              ) : (
                <p className="muted">
                  No retained upload preview is available for this historical reference.
                </p>
              )}
              <h3>{data.canonical_answer}</h3>
              <p>
                {data.status === 'pending'
                  ? 'Your contribution is awaiting review.'
                  : data.status === 'approved'
                    ? data.retired
                      ? 'Accepted into the library; currently retired from gameplay.'
                      : data.preview_url
                        ? 'Accepted into the playable image library.'
                        : 'Approved historical reference; no hosted image is available for gameplay.'
                    : 'This contribution was not accepted into the game.'}
              </p>
              <dl>
                <dt>Category</dt>
                <dd>{data.category_name}</dd>
                <dt>Accepted synonyms</dt>
                <dd>{data.accepted_synonyms?.join(', ') || 'None supplied'}</dd>
                <dt>Submitted</dt>
                <dd>{new Date(data.created_at).toLocaleString()}</dd>
                <dt>Source</dt>
                <dd>{sourceLabel(data.source)}</dd>
                <dt>Provenance</dt>
                <dd>{data.source_url || 'Not supplied'}</dd>
                <dt>License / usage rights</dt>
                <dd>{data.license}</dd>
                <dt>Attribution</dt>
                <dd>{data.attribution}</dd>
              </dl>
              {data.explanation && (
                <section className="contribution-explanation">
                  <h3>Review explanation</h3>
                  <p>{data.explanation}</p>
                </section>
              )}
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}
