import { useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import type { Category, Page } from '../api';
import {
  type Contribution,
  contributionStatuses,
  statusLabel,
  sourceLabel,
} from '../contributions/api';
import { useData } from '../moderation/useData';
import { Dialog, Feedback, Heading, Loading, Pager } from '../moderation/components';
import { adminRoot, send } from './api';
import { DeleteImage } from './DeleteImage';
import '../contributions/contributions.css';

export function ImageLibraryTabs({ submissions = false }: { submissions?: boolean }) {
  return (
    <nav className="mod-filter" aria-label="Image Library sections">
      <Link
        className={!submissions ? 'selected' : ''}
        aria-current={!submissions ? 'page' : undefined}
        to="/moderation/administration/images"
      >
        Image Library
      </Link>
      <Link
        className={submissions ? 'selected' : ''}
        aria-current={submissions ? 'page' : undefined}
        to="/moderation/administration/images?tab=submissions"
      >
        Player Submissions
      </Link>
    </nav>
  );
}
function ReviewContribution({
  item,
  close,
  saved,
}: {
  item: Contribution;
  close: () => void;
  saved: () => void;
}) {
  const {
    data: categories,
    error: categoryError,
    reload,
  } = useData<Category[]>('/api/library/categories/');
  const formRef = useRef<HTMLFormElement>(null);
  const [category, setCategory] = useState(item.category);
  const [pending, setPending] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState('');
  const run = async (operation: string) => {
    if (pending) return;
    const form = formRef.current ? new FormData(formRef.current) : new FormData();
    const corrections =
      operation === 'approve'
        ? {
            canonical_answer: form.get('canonical_answer'),
            accepted_synonyms: String(form.get('accepted_synonyms') ?? '')
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean),
            category: Number(form.get('category')),
            license: form.get('license'),
            attribution: form.get('attribution'),
            source: form.get('source'),
            source_url: form.get('source_url'),
          }
        : undefined;
    setPending(true);
    setError('');
    try {
      await send(`player-submissions/${item.id}/review/`, {
        operation,
        ...(corrections ? { corrections } : {}),
        explanation: String(form.get('explanation') ?? ''),
        visible_to_player: form.get('visible_to_player') === 'on',
        confirm: operation === 'remove',
      });
      saved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  };
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void run('approve');
  };
  return (
    <>
      <Dialog
        title={item.status === 'removed' ? 'Removed contribution' : 'Review player submission'}
        close={close}
        pending={pending}
      >
        {item.status === 'removed' ? (
          <>
            <div className="contribution-removed-placeholder" aria-hidden="true">
              ◇
            </div>
            <p>This contribution was removed by an administrator.</p>
            <p>{new Date(item.created_at).toLocaleString()}</p>
          </>
        ) : (
          <div className="admin-contribution-review">
            <p className="mod-muted">
              @{item.submitter} · {item.submitter_id || 'Account deleted'}
              <br />
              Submitted {new Date(item.created_at).toLocaleString()}
              <br />
              {item.rights_acknowledged_at
                ? `Usage permission acknowledged ${new Date(item.rights_acknowledged_at).toLocaleString()}`
                : 'Historical submission; no permission acknowledgment was recorded.'}
            </p>
            {item.preview_url ? (
              <img
                className="admin-large-preview"
                src={item.preview_url}
                alt="Full private submission preview"
              />
            ) : (
              <p className="mod-muted">
                Historical external reference; no retained upload preview.
              </p>
            )}
            <span className={`contribution-status ${item.status}`}>
              {item.status === 'pending' ? 'Pending player review' : statusLabel(item.status)}
            </span>
            {item.status === 'pending' ? (
              <form className="mod-form" ref={formRef} onSubmit={submit}>
                <label>
                  Canonical answer
                  <input
                    name="canonical_answer"
                    defaultValue={item.canonical_answer}
                    maxLength={120}
                    required
                    disabled={pending}
                  />
                </label>
                <label>
                  Accepted synonyms
                  <textarea
                    name="accepted_synonyms"
                    defaultValue={item.accepted_synonyms?.join(', ')}
                    rows={2}
                    disabled={pending}
                  />
                  <small>Separate alternate answers with commas.</small>
                </label>
                <label>
                  Category
                  <select
                    name="category"
                    value={category}
                    onChange={(event) => setCategory(Number(event.target.value))}
                    required
                    disabled={pending}
                  >
                    {categories?.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Source
                  <select name="source" defaultValue={item.source} disabled={pending}>
                    <option value="manual">Created or owned by submitter</option>
                    <option value="licensed">Licensed third-party image</option>
                    <option value="commons">Wikimedia Commons</option>
                    <option value="ai">AI-generated</option>
                  </select>
                </label>
                <label>
                  Source / provenance URL
                  <input
                    name="source_url"
                    defaultValue={item.source_url}
                    type="url"
                    maxLength={1000}
                    disabled={pending}
                  />
                </label>
                <label>
                  License / usage rights
                  <input
                    name="license"
                    defaultValue={item.license}
                    maxLength={160}
                    required
                    disabled={pending}
                  />
                </label>
                <label>
                  Attribution
                  <input
                    name="attribution"
                    defaultValue={item.attribution}
                    maxLength={500}
                    required
                    disabled={pending}
                  />
                </label>
                <p className="mod-muted">
                  Corrections are saved when you approve. Approval accepts this image into the game.
                </p>
                <label>
                  Review explanation (optional)
                  <textarea name="explanation" rows={3} maxLength={2000} disabled={pending} />
                </label>
                <label className="admin-review-visibility">
                  <input type="checkbox" name="visible_to_player" disabled={pending} /> Visible to
                  player
                </label>
                <small className="mod-muted">
                  Only explanations explicitly marked visible will appear in the player’s history.
                </small>
                {categoryError && (
                  <>
                    <Feedback error={categoryError} />
                    <button type="button" className="mod-button subtle" onClick={reload}>
                      Retry categories
                    </button>
                  </>
                )}
                <Feedback error={error} />
                <div className="mod-actions">
                  <button className="mod-button" disabled={pending || !categories}>
                    {pending ? 'Saving…' : 'Approve'}
                  </button>
                  <button
                    type="button"
                    className="mod-button subtle"
                    disabled={pending}
                    onClick={() => void run('reject')}
                  >
                    Reject
                  </button>
                  <button
                    type="button"
                    className="mod-button danger"
                    disabled={pending}
                    onClick={() => setRemoving(true)}
                  >
                    Remove
                  </button>
                </div>
              </form>
            ) : (
              <>
                <dl className="admin-details">
                  <dt>Canonical answer</dt>
                  <dd>{item.canonical_answer}</dd>
                  <dt>Category</dt>
                  <dd>{item.category_name}</dd>
                  <dt>Accepted synonyms</dt>
                  <dd>{item.accepted_synonyms?.join(', ') || 'None'}</dd>
                  <dt>Source</dt>
                  <dd>{sourceLabel(item.source)}</dd>
                  <dt>Source URL</dt>
                  <dd>{item.source_url || 'Not supplied'}</dd>
                  <dt>License</dt>
                  <dd>{item.license}</dd>
                  <dt>Attribution</dt>
                  <dd>{item.attribution}</dd>
                </dl>
                {item.status === 'approved' ? (
                  <>
                    <p>Use the Image Library for editing, retirement, restoration or deletion.</p>
                    <Link
                      className="mod-button subtle"
                      to={`/moderation/administration/images?q=${item.id}`}
                    >
                      Open in Image Library
                    </Link>
                  </>
                ) : (
                  <>
                    <p>Rejected contributions remain here and are excluded from Image Library.</p>
                    <DeleteImage
                      image={{
                        id: item.id,
                        canonical_answer: item.canonical_answer ?? '',
                        status: item.status,
                      }}
                      deleted={saved}
                    />
                  </>
                )}
              </>
            )}
          </div>
        )}
      </Dialog>
      {removing && (
        <Dialog
          title="Remove this contribution?"
          close={() => setRemoving(false)}
          pending={pending}
        >
          <p>
            <strong>{item.canonical_answer}</strong> · {item.id}
          </p>
          <p>
            This permanently removes the image and its content. The player will see only a generic
            Removed receipt. Historical scores and game outcomes remain.
          </p>
          <Feedback error={error} />
          <div className="mod-actions">
            <button
              className="mod-button subtle"
              disabled={pending}
              onClick={() => setRemoving(false)}
            >
              Cancel
            </button>
            <button
              className="mod-button danger"
              disabled={pending}
              onClick={() => void run('remove')}
            >
              {pending ? 'Removing…' : 'Remove Permanently'}
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
export function PlayerSubmissions() {
  const [status, setStatus] = useState('pending');
  const [page, setPage] = useState(1);
  const [q, setQ] = useState('');
  const [selected, setSelected] = useState<Contribution | null>(null);
  const [message, setMessage] = useState('');
  const { data, error, reload } = useData<Page<Contribution>>(
    `${adminRoot}player-submissions/?status=${status}&page=${page}&q=${encodeURIComponent(q)}`,
  );
  return (
    <>
      <Heading
        title="Player Submissions"
        detail="Review community contributions and choose what joins the game."
      />
      <ImageLibraryTabs submissions />
      <form
        className="admin-filters"
        onSubmit={(e) => {
          e.preventDefault();
          setQ(String(new FormData(e.currentTarget).get('q') ?? ''));
          setPage(1);
        }}
      >
        <label>
          Search answer, player or UUID
          <input name="q" />
        </label>
        <button className="mod-button">Search</button>
      </form>
      <div className="mod-filter" role="group" aria-label="Player submission status">
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
            {s === 'pending' ? 'Pending player review' : statusLabel(s)}
          </button>
        ))}
      </div>
      <Feedback message={message} />
      {!data ? (
        <Loading error={error} retry={reload} />
      ) : (
        <>
          {!data.count ? (
            <p className="mod-card mod-empty">
              No {status === 'all' ? 'player' : status} submissions match this view.
            </p>
          ) : (
            <ul className="admin-contribution-list">
              {data.results.map((item) => (
                <li key={item.id}>
                  <button className="contribution-row" onClick={() => setSelected(item)}>
                    {item.status !== 'removed' && item.preview_url ? (
                      <img
                        className="contribution-thumb"
                        loading="lazy"
                        src={item.preview_url}
                        alt="Private player contribution"
                      />
                    ) : (
                      <span className="contribution-thumb placeholder" aria-hidden="true">
                        ◇
                      </span>
                    )}
                    <span className="contribution-row-title">
                      <strong>
                        {item.status === 'removed' ? 'Removed contribution' : item.canonical_answer}
                      </strong>
                      <small>
                        @{item.submitter} · {item.submitter_id || 'Account deleted'}
                      </small>
                      <small>
                        {item.status !== 'removed' && item.category_name} ·{' '}
                        {new Date(item.created_at).toLocaleString()}
                      </small>
                    </span>
                    <span className={`contribution-status ${item.status}`}>
                      {item.status === 'pending'
                        ? 'Pending player review'
                        : statusLabel(item.status)}
                    </span>
                    <span className="contribution-open" aria-hidden="true">
                      ↗
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <Pager page={page} next={data.next} previous={data.previous} change={setPage} />
        </>
      )}
      {selected && (
        <ReviewContribution
          item={selected}
          close={() => setSelected(null)}
          saved={() => {
            setSelected(null);
            setMessage('Review saved.');
            reload();
          }}
        />
      )}
    </>
  );
}
