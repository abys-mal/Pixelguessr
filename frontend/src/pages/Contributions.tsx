import { useState } from 'react';
import type { Category } from '../api';
import { useAuth } from '../auth/context';
import { PageHeading, SignInPrompt, StatusMessage } from '../components/ui';
import { useData } from '../moderation/useData';
import { usePageData } from '../moderation/usePageData';
import { PageNavigation } from '../components/Pagination';
import {
  contributionRoot,
  contributionStatuses,
  statusLabel,
  type ContributionPage,
} from '../contributions/api';
import { ContributionDetails } from '../contributions/Details';
import { NewSubmission } from '../contributions/NewSubmission';
import { SanctionAccessNotice } from '../components/SanctionAccessNotice';
import { restrictedSanction } from '../components/sanctionAccess';
import '../contributions/contributions.css';

export function Contributions() {
  const { user, loading } = useAuth();
  if (loading) return <StatusMessage>Loading account…</StatusMessage>;
  if (!user) return <SignInPrompt feature="view your image contributions" />;
  return <ContributionDashboard key={user.id} />;
}
function ContributionDashboard() {
  const { restrictions } = useAuth();
  const [status, setStatus] = useState('all');
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState('');
  const [message, setMessage] = useState('');
  const { data, error, reload } = usePageData<ContributionPage>(
    `${contributionRoot}?status=${status}&page=${page}`,
    setPage,
  );
  const {
    data: categories,
    error: categoryError,
    reload: reloadCategories,
  } = useData<Category[]>('/api/library/categories/');
  const restricted = !!restrictedSanction(restrictions, 'contributions');
  return (
    <div className="contributions-page">
      <div className="contribution-heading">
        <PageHeading eyebrow="ADD YOUR PERSPECTIVE" title="Image Contributions">
          Share images with the community and track your contributions.
        </PageHeading>
        <button
          className="button"
          disabled={restricted || !categories}
          onClick={() => setCreating(true)}
        >
          + New Submission
        </button>
      </div>
      <SanctionAccessNotice feature="contributions" />
      {categoryError && (
        <StatusMessage error>
          {categoryError}{' '}
          <button className="button secondary" onClick={reloadCategories}>
            Retry categories
          </button>
        </StatusMessage>
      )}
      {message && <StatusMessage>{message}</StatusMessage>}
      <dl className="contribution-stats">
        {[
          ['Total contributions', data?.stats?.total],
          ['Pending', data?.stats?.pending],
          ['Approved', data?.stats?.approved],
        ].map(([label, value]) => (
          <div className="panel" key={String(label)}>
            <dt>{label}</dt>
            <dd>{value ?? '—'}</dd>
          </div>
        ))}
      </dl>
      <div className="contribution-filters" role="group" aria-label="Contribution status">
        {contributionStatuses.map((s) => (
          <button
            key={s}
            className={s === status ? 'selected' : ''}
            aria-pressed={s === status}
            onClick={() => {
              setStatus(s);
              setPage(1);
            }}
          >
            {statusLabel(s)}
          </button>
        ))}
      </div>
      {!data ? (
        <div className="panel">
          <StatusMessage error={!!error}>{error || 'Loading contributions…'}</StatusMessage>
          {error && (
            <button className="button secondary" onClick={reload}>
              Try again
            </button>
          )}
        </div>
      ) : (
        <>
          {data.results.length ? (
            <ul className="contribution-list">
              {data.results.map((item) => (
                <li key={item.id}>
                  <button className="contribution-row" onClick={() => setSelected(item.id)}>
                    {item.status === 'removed' ? (
                      <span className="contribution-thumb placeholder" aria-hidden="true">
                        ◇
                      </span>
                    ) : item.preview_url ? (
                      <img
                        className="contribution-thumb"
                        loading="lazy"
                        src={item.preview_url}
                        alt="Your private contribution"
                      />
                    ) : (
                      <span className="contribution-thumb placeholder" aria-hidden="true">
                        ▧
                      </span>
                    )}
                    <span className="contribution-row-title">
                      <strong>
                        {item.status === 'removed' ? 'Removed contribution' : item.canonical_answer}
                      </strong>
                      <small>
                        {item.status === 'removed'
                          ? 'This contribution was removed by an administrator.'
                          : item.category_name}
                      </small>
                    </span>
                    <time dateTime={item.created_at}>
                      {new Date(item.created_at).toLocaleDateString()}
                    </time>
                    <span className={`contribution-status ${item.status}`}>
                      {statusLabel(item.status)}
                    </span>
                    <span className="contribution-open" aria-hidden="true">
                      ↗
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <section className="panel contribution-empty">
              <span aria-hidden="true">◇</span>
              <h2>
                {status === 'all'
                  ? 'Your next perspective starts here.'
                  : `No ${status} contributions.`}
              </h2>
              <p>
                {status === 'all'
                  ? 'Share a picture worth guessing. Your contributions and their reviews will appear here.'
                  : 'Try another filter to see more of your contribution history.'}
              </p>
            </section>
          )}
          <PageNavigation
            pagination={data}
            onPage={setPage}
            className="contribution-pagination"
            label="Contribution pages"
          />
        </>
      )}
      {creating && categories && (
        <NewSubmission
          categories={categories}
          close={() => setCreating(false)}
          saved={() => {
            setCreating(false);
            setStatus('all');
            setPage(1);
            setMessage('Image submitted. It will remain private while awaiting review.');
            reload();
          }}
        />
      )}
      {selected && <ContributionDetails id={selected} close={() => setSelected('')} />}
    </div>
  );
}
