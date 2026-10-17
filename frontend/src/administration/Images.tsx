import { useState } from 'react';
import type { FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { type Category, type Page } from '../api';
import { Dialog, Feedback, Heading, Loading, Pager } from '../moderation/components';
import { useData } from '../moderation/useData';
import { adminRoot, send, type LibraryImage } from './api';

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
  const [reveal, setReveal] = useState(200);
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
      });
      setCurrent(next);
      setMessage('Reviewed labels saved.');
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
        <img
          className="admin-large-preview"
          src={current.preview_url}
          alt={`Private preview: ${current.canonical_answer}`}
        />
        <span className={`mod-chip ${current.status}`}>{current.status}</span>
        <form className="mod-form" onSubmit={(e) => void save(e)}>
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
          <p className="mod-muted">
            Saving confirms you reviewed these labels. Existing round snapshots stay unchanged.
          </p>
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
        <section>
          <h3>Gameplay reveal preview</h3>
          <p className="mod-muted">Rendered by the actual server-side tile compositor.</p>
          <label>
            Revealed tiles: {reveal} / 400
            <input
              type="range"
              min="0"
              max="400"
              step="20"
              value={reveal}
              onChange={(e) => setReveal(Number(e.target.value))}
            />
          </label>
          <img
            className="admin-large-preview"
            src={`${current.preview_url}?reveal=${reveal}`}
            alt={`${reveal} of 400 tiles revealed`}
          />
        </section>
      </div>
    </Dialog>
  );
}

export function ImageLibrary() {
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
              <option key={s}>{s}</option>
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
                  <span className={`mod-chip ${image.status}`}>{image.status}</span>
                </label>
                <button className="admin-image-open" onClick={() => setEditing(image)}>
                  <img loading="lazy" src={image.preview_url} alt={image.canonical_answer} />
                  <strong>{image.canonical_answer}</strong>
                  <small>
                    {image.category_name} · {image.attribution}
                  </small>
                </button>
                <div className="mod-actions">
                  <button className="mod-button subtle" onClick={() => setEditing(image)}>
                    Review image
                  </button>
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
          title={`${operation[0].toUpperCase() + operation.slice(1)} ${selected.length} images?`}
          close={() => setOperation('')}
          pending={pending}
        >
          <form className="mod-form" onSubmit={(e) => void run(e)}>
            <p>
              Every selected image will be validated. The results will show successes, failures and
              skipped images.
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
