import { useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { type Category, type Page } from '../api';
import { Dialog, Feedback, Heading, Loading, Pager } from '../moderation/components';
import { useData } from '../moderation/useData';
import { adminRoot, send, type LibraryImage } from './api';
import { DeleteImage } from './DeleteImage';
import { PlayerSubmissions, ImageLibraryTabs } from './PlayerSubmissions';
import { GameplayPreview } from './GameplayPreview';

export function ImageEditor({
  image,
  close,
  saved,
}: {
  image: LibraryImage;
  close: () => void;
  saved: () => void;
}) {
  const {
    data: categories,
    error: categoryError,
    reload: reloadCategories,
  } = useData<Category[]>('/api/library/categories/');
  const [current, setCurrent] = useState(image);
  const [category, setCategory] = useState(image.category);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [revision, setRevision] = useState(0);
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError('');
    const form = new FormData(event.currentTarget);
    try {
      const next = await send<LibraryImage>(`images/${image.id}/`, {
        canonical_answer: form.get('answer'),
        accepted_synonyms: String(form.get('synonyms') ?? '')
          .split('\n')
          .map((x) => x.trim())
          .filter(Boolean),
        category: Number(form.get('category')),
        source: form.get('source'),
        source_url: form.get('source_url'),
        license: form.get('license'),
        attribution: form.get('attribution'),
        photographer: form.get('photographer'),
      });
      setCurrent(next);
      setCategory(next.category);
      setRevision((value) => value + 1);
      setMessage('Reviewed labels and source metadata saved.');
      saved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  };
  return (
    <Dialog title="Image detail" close={close} pending={pending}>
      <div className="admin-image-editor">
        <DeleteImage
          image={current}
          deleted={() => {
            close();
            saved();
          }}
        />
        <img
          className="admin-large-preview"
          src={current.preview_url}
          alt={`Private preview: ${current.canonical_answer}`}
        />
        <span className={`mod-chip ${current.status}`}>
          {current.status === 'pending' ? 'Pending' : current.status}
        </span>
        <form key={revision} className="mod-form" onSubmit={(e) => void save(e)}>
          <label>
            Canonical answer
            <input name="answer" required maxLength={120} defaultValue={current.canonical_answer} />
          </label>
          <label>
            Accepted synonyms <span>One per line; maximum 30</span>
            <textarea
              name="synonyms"
              rows={3}
              defaultValue={current.accepted_synonyms.join('\n')}
            />
          </label>
          <label>
            Category
            <select
              name="category"
              value={category}
              onChange={(e) => setCategory(Number(e.target.value))}
            >
              {categories?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Source type
            <select name="source" defaultValue={current.source || 'manual'}>
              <option value="manual">Manual upload</option>
              <option value="commons">Wikimedia Commons</option>
              <option value="licensed">Other licensed source</option>
              <option value="ai">AI-generated</option>
            </select>
          </label>
          <label>
            Creator / photographer
            <input
              name="photographer"
              maxLength={500}
              defaultValue={String(current.import_metadata.photographer ?? '')}
            />
          </label>
          <label>
            License / usage rights
            <input
              name="license"
              required
              maxLength={160}
              defaultValue={current.license}
              placeholder="CC0, Public Domain, or the specific license"
            />
          </label>
          <p className="mod-muted">
            Commons images have individual licenses. CC0 and Public Domain are distinct; verify the
            original file page.
          </p>
          <label>
            Attribution / credit
            <input name="attribution" required maxLength={500} defaultValue={current.attribution} />
          </label>
          <label>
            Original source URL
            <input
              name="source_url"
              type="url"
              maxLength={1000}
              defaultValue={current.source_url}
            />
          </label>
          <button className="mod-button" disabled={pending || !categories}>
            {pending ? 'Saving…' : 'Save reviewed labels'}
          </button>
        </form>
        {categoryError && (
          <div>
            <Feedback error={categoryError} />
            <button className="mod-button subtle" onClick={reloadCategories}>
              Retry categories
            </button>
          </div>
        )}
        <Feedback error={error} message={message} />
        <details>
          <summary>Source and import details</summary>
          <dl className="admin-details">
            <dt>Attribution</dt>
            <dd>{current.attribution}</dd>
            <dt>License</dt>
            <dd>{current.license}</dd>
            <dt>Source URL</dt>
            <dd>{current.source_url || 'Not supplied'}</dd>
            <dt>Review reason</dt>
            <dd>{current.review_reason || '—'}</dd>
          </dl>
          <pre>{JSON.stringify(current.import_metadata, null, 2)}</pre>
        </details>
        <GameplayPreview key={current.id} url={current.preview_url} />
      </div>
    </Dialog>
  );
}

export function ImageLibrary() {
  const [params] = useSearchParams();
  return params.get('tab') === 'submissions' ? <PlayerSubmissions /> : <GeneralImageLibrary />;
}
function GeneralImageLibrary() {
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const status = params.get('status') ?? '';
  const page = Number(params.get('page') ?? 1);
  const { data, error, reload } = useData<Page<LibraryImage>>(
    `${adminRoot}images/?${params.toString()}`,
  );
  const [selected, setSelected] = useState<string[]>([]);
  const [editing, setEditing] = useState<LibraryImage | null>(null);
  const [operation, setOperation] = useState('');
  const [pending, setPending] = useState(false);
  const [actionError, setActionError] = useState('');
  const [message, setMessage] = useState('');
  const [rejecting, setRejecting] = useState<string[]>([]);
  const rejectLocks = useRef(new Set<string>());
  const reject = async (image: LibraryImage) => {
    if (rejectLocks.current.has(image.id)) return;
    rejectLocks.current.add(image.id);
    setRejecting((ids) => [...ids, image.id]);
    setMessage('');
    setActionError('');
    try {
      const response = await send<{ results: { status: string; error?: string }[] }>(
        'images/review/',
        { ids: [image.id], operation: 'reject' },
      );
      if (response.results[0]?.status !== 'success')
        throw new Error(response.results[0]?.error || 'Unable to reject this pending image.');
      setSelected((ids) => ids.filter((id) => id !== image.id));
      setMessage('Pending image rejected.');
      reload();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      rejectLocks.current.delete(image.id);
      setRejecting((ids) => ids.filter((id) => id !== image.id));
    }
  };
  const [results, setResults] = useState<{ id: string; status: string; error?: string }[]>([]);
  const run = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setActionError('');
    const form = new FormData(event.currentTarget);
    try {
      const result = await send<{ results: typeof results }>('images/review/', {
        ids: selected,
        operation,
        reason: String(form.get('reason') ?? ''),
      });
      setResults(result.results);
      setSelected([]);
      setOperation('');
      reload();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setPending(false);
    }
  };
  return (
    <>
      <Heading
        title="Image Library"
        detail="Review the pictures. Keep every answer worth guessing."
      />
      <ImageLibraryTabs />
      <form
        className="admin-filters"
        onSubmit={(e) => {
          e.preventDefault();
          const form = new FormData(e.currentTarget);
          setParams({ q: String(form.get('q')), status: String(form.get('status')), page: '1' });
          setSelected([]);
        }}
      >
        <label>
          Search answer, ID or category
          <input name="q" defaultValue={q} />
        </label>
        <label>
          Status
          <select name="status" defaultValue={status}>
            <option value="">All images</option>
            {['pending', 'approved', 'rejected', 'retired'].map((s) => (
              <option key={s} value={s}>
                {s === 'pending' ? 'Pending' : s}
              </option>
            ))}
          </select>
        </label>
        <button className="mod-button">Search</button>
      </form>
      <div className="mod-actions admin-toolbar">
        <span>{selected.length} selected</span>
        {['approve', 'reject', 'retire', 'restore'].map((op) => (
          <button
            key={op}
            className="mod-button subtle"
            disabled={!selected.length}
            onClick={() => {
              setActionError('');
              setOperation(op);
            }}
          >
            {op[0].toUpperCase() + op.slice(1)}
          </button>
        ))}
      </div>
      <Feedback error={!operation ? actionError : ''} message={message} />
      {results.length > 0 && (
        <section className="mod-card" role="status">
          <h2>Action results</h2>
          <p>
            {results.filter((x) => x.status === 'success').length} successful ·{' '}
            {results.filter((x) => x.status === 'skipped').length} skipped ·{' '}
            {results.filter((x) => x.status === 'failed').length} failed
          </p>
          {results
            .filter((x) => x.status === 'failed')
            .map((x) => (
              <p key={x.id} className="mod-field-error">
                {x.id}: {x.error}
              </p>
            ))}
        </section>
      )}
      {!data ? (
        <Loading error={error} retry={reload} />
      ) : (
        <>
          <p className="mod-muted">{data.count} images</p>
          <div className="admin-image-grid">
            {data.results.map((image) => (
              <article className="admin-image-card" key={image.id}>
                <label className="admin-image-select">
                  <input
                    type="checkbox"
                    checked={selected.includes(image.id)}
                    aria-label={`Select ${image.canonical_answer}`}
                    onChange={(e) =>
                      setSelected(
                        e.target.checked
                          ? [...selected, image.id]
                          : selected.filter((id) => id !== image.id),
                      )
                    }
                  />
                  <span className={`mod-chip ${image.status}`}>
                    {image.status === 'pending' ? 'Pending' : image.status}
                  </span>
                </label>
                <button className="admin-image-open" onClick={() => setEditing(image)}>
                  <img loading="lazy" src={image.preview_url} alt={image.canonical_answer} />
                  <strong>{image.canonical_answer}</strong>
                  <small>
                    {image.category_name} · {image.attribution}
                  </small>
                </button>
                <div className="mod-actions">
                  <DeleteImage
                    image={image}
                    deleted={() => {
                      setSelected((ids) => ids.filter((id) => id !== image.id));
                      reload();
                    }}
                  />
                  <button className="mod-button subtle" onClick={() => setEditing(image)}>
                    Review image
                  </button>
                  <div className="mod-actions admin-review-decisions">
                    <button
                      className="mod-button subtle"
                      onClick={() => {
                        setSelected([image.id]);
                        setOperation(
                          image.status === 'retired'
                            ? 'restore'
                            : image.status === 'approved'
                              ? 'retire'
                              : 'approve',
                        );
                      }}
                    >
                      {image.status === 'retired'
                        ? 'Restore'
                        : image.status === 'approved'
                          ? 'Retire'
                          : 'Approve'}
                    </button>
                    {image.status === 'pending' && (
                      <button
                        type="button"
                        className="mod-button subtle"
                        aria-label="Reject pending image"
                        title={`Reject pending image: ${image.canonical_answer}`}
                        disabled={rejecting.includes(image.id) || pending}
                        onClick={() => void reject(image)}
                      >
                        Reject
                      </button>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
          {!data.count && <p className="mod-card mod-empty">No images match these filters.</p>}
          <Pager
            page={page}
            next={data.next}
            previous={data.previous}
            change={(value) => {
              setSelected([]);
              setParams({ q, status, page: String(value) });
            }}
          />
        </>
      )}
      {editing && <ImageEditor image={editing} close={() => setEditing(null)} saved={reload} />}{' '}
      {operation && (
        <Dialog
          title={`${operation[0].toUpperCase() + operation.slice(1)} ${selected.length} ${selected.length === 1 ? 'image' : 'images'}?`}
          close={() => setOperation('')}
          pending={pending}
        >
          <form className="mod-form" onSubmit={(e) => void run(e)}>
            <p>
              {selected.length === 1
                ? 'The selected image will be validated. The result will show whether it succeeded, failed or was skipped.'
                : 'Every selected image will be validated. The results will show successes, failures and skipped images.'}
            </p>
            <label>
              Reason (optional)
              <textarea name="reason" rows={3} maxLength={2000} />
            </label>
            <Feedback error={actionError} />
            <div className="mod-actions">
              <button
                className="mod-button subtle"
                type="button"
                disabled={pending}
                onClick={() => setOperation('')}
              >
                Cancel
              </button>
              <button className="mod-button" disabled={pending}>
                {pending ? 'Working…' : 'Confirm action'}
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </>
  );
}
