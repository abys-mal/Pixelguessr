import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, type Page } from '../api';
import { Feedback, Heading, Loading, Pager } from '../moderation/components';
import { usePageData } from '../moderation/usePageData';
import { adminRoot, send, type Batch, type ImportItem, type LibraryImage } from './api';
import { ImageEditor } from './Images';

function SelectedPreview({ file }: { file: File }) {
  const ref = useRef<HTMLImageElement>(null);
  useEffect(() => {
    if (!file.type.startsWith('image/') || !URL.createObjectURL) return;
    const url = URL.createObjectURL(file);
    if (ref.current) ref.current.src = url;
    return () => URL.revokeObjectURL(url);
  }, [file]);
  return (
    <img
      ref={ref}
      alt=""
      onError={(e) => {
        e.currentTarget.hidden = true;
      }}
    />
  );
}

export function ImageImports() {
  const navigate = useNavigate();
  const { id } = useParams();
  const [page, setPage] = useState(1);
  const [error, setError] = useState('');
  const [files, setFiles] = useState<{ id: string; file: File }[]>([]);
  const metadataForm = useRef<HTMLFormElement>(null);
  const addFiles = (incoming: File[]) =>
    setFiles((previous) => [
      ...previous,
      ...incoming.map((file) => ({ id: crypto.randomUUID(), file })),
    ]);
  const [busy, setBusy] = useState(false);
  const saving = useRef(false);
  const [progress, setProgress] = useState('');
  const [editing, setEditing] = useState<LibraryImage | null>(null);
  const {
    data,
    error: loadError,
    reload,
  } = usePageData<Page<Batch> | Page<ImportItem>>(
    `${adminRoot}imports/${id ? `${id}/` : ''}?page=${page}`,
    setPage,
  );
  const upload = async () => {
    if (!id || saving.current || !files.length) return;
    saving.current = true;
    setBusy(true);
    setError('');
    const metadata = new FormData(metadataForm.current!);
    try {
      for (let index = 0; index < files.length; index++) {
        setProgress(`Uploading ${index + 1} of ${files.length}: ${files[index].file.name}`);
        const body = new FormData();
        body.append('request_id', crypto.randomUUID());
        body.append('file', files[index].file);
        for (const [key, value] of metadata) {
          if (typeof value === 'string' && value.trim()) body.set(key, value);
        }
        try {
          await api(`${adminRoot}imports/${id}/`, { method: 'POST', body });
        } catch (e) {
          setError((previous) => `${previous}\n${files[index].file.name}: ${(e as Error).message}`);
        }
      }
      setFiles([]);
      setProgress('Upload complete. Review each pending image before approval.');
      reload();
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };
  return (
    <div className="admin-import-page">
      <Heading
        title="Image Imports"
        detail="Private uploads, persistent batches, and deliberate review."
      />
      {!id ? (
        <>
          <form
            className="mod-card admin-filters"
            onSubmit={async (e) => {
              e.preventDefault();
              if (busy) return;
              setBusy(true);
              setError('');
              const form = new FormData(e.currentTarget);
              try {
                const batch = await send<Batch>('imports/', { name: form.get('name') });
                navigate(`/moderation/administration/imports/${batch.id}`);
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              New batch name
              <input name="name" required maxLength={120} placeholder="A new perspective" />
            </label>
            <button className="mod-button" disabled={busy}>
              Create preparation batch
            </button>
          </form>
          <p className="mod-muted">
            Batches remain saved when you leave. Historical command-line imports stay in Image
            Library; private CSV files are not exposed here.
          </p>
        </>
      ) : (
        <>
          <Link className="mod-back" to="/moderation/administration/imports">
            ← All import batches
          </Link>
          <section
            className="mod-card admin-upload"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (!busy) addFiles(Array.from(e.dataTransfer.files));
            }}
          >
            <h2>Add images to this batch</h2>
            <p>
              Drop multiple images here, or choose files. JPG, PNG and WebP · maximum 8 MiB each.
            </p>
            <label className="mod-form">
              Choose images
              <input
                type="file"
                multiple
                accept="image/jpeg,image/png,image/webp"
                disabled={busy}
                onChange={(e) => {
                  addFiles(Array.from(e.target.files ?? []));
                  e.target.value = '';
                }}
              />
            </label>
            <p>{files.length} files selected</p>
            {files.length > 0 && (
              <ul className="admin-selected-files" aria-label="Selected files">
                {files.map(({ id: selectionId, file }) => (
                  <li key={selectionId}>
                    <SelectedPreview file={file} />
                    <span>
                      {file.name}
                      <small>{Math.ceil(file.size / 1024)} KiB</small>
                    </span>
                    <button
                      type="button"
                      className="admin-dismiss"
                      aria-label={`Remove ${file.name}`}
                      title="Remove selected file"
                      disabled={busy}
                      onClick={() =>
                        setFiles((previous) => previous.filter((entry) => entry.id !== selectionId))
                      }
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {files.length > 1 && (
              <button
                type="button"
                className="mod-button subtle"
                disabled={busy}
                onClick={() => setFiles([])}
              >
                Clear all
              </button>
            )}
            <details className="admin-import-source">
              <summary>Source metadata for these uploads (optional)</summary>
              <form
                ref={metadataForm}
                className="mod-form admin-import-metadata"
                onSubmit={(e) => e.preventDefault()}
              >
                <p className="mod-muted">
                  Supply what you know. Unspecified credits and licenses stay unverified until
                  review; filenames never determine the source.
                </p>
                <label>
                  Source type
                  <select name="source" disabled={busy} defaultValue="manual">
                    <option value="manual">Manual / source not yet specified</option>
                    <option value="commons">Wikimedia Commons</option>
                    <option value="licensed">Other licensed source</option>
                    <option value="ai">AI-generated</option>
                  </select>
                </label>
                <label>
                  Creator / photographer (optional)
                  <input name="photographer" maxLength={500} disabled={busy} />
                </label>
                <label>
                  License / usage rights
                  <input
                    name="license"
                    maxLength={160}
                    placeholder="e.g. CC BY-SA 4.0, CC0, or Public Domain"
                    disabled={busy}
                  />
                </label>
                <label>
                  Attribution / credit
                  <input name="attribution" maxLength={500} disabled={busy} />
                </label>
                <label>
                  Original source URL
                  <input name="source_url" type="url" maxLength={1000} disabled={busy} />
                </label>
              </form>
            </details>
            <button
              className="mod-button"
              disabled={busy || !files.length}
              onClick={() => void upload()}
            >
              {busy ? 'Uploading…' : 'Upload selected images'}
            </button>
            <p role="status">{progress}</p>
            <p className="mod-muted">
              Images remain pending until their labels are reviewed and approval is confirmed.
            </p>
          </section>
        </>
      )}
      <Feedback error={error} />
      {!data ? (
        <Loading error={loadError} retry={reload} />
      ) : (
        <>
          {id ? (
            <div className="admin-image-grid">
              {(data as Page<ImportItem>).results.map((item) => (
                <article className="mod-card admin-import-result" key={item.id}>
                  <h3>{item.filename}</h3>
                  <span className="mod-chip">{item.status}</span>
                  {item.error && <p className="mod-field-error">{item.error}</p>}
                  {item.image && (
                    <>
                      <img
                        className="admin-large-preview"
                        src={item.image.preview_url}
                        alt={item.image.canonical_answer}
                      />
                      <p>
                        {item.image.canonical_answer} · {item.image.status}
                      </p>
                      <div className="admin-import-actions">
                        <button className="mod-button" onClick={() => setEditing(item.image)}>
                          Prepare labels
                        </button>
                        <Link to={`/moderation/administration/images?q=${item.image.id}`}>
                          Review in Image Library →
                        </Link>
                      </div>
                    </>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <div className="admin-batch-list">
              {(data as Page<Batch>).results.map((batch) => (
                <Link
                  className="mod-card"
                  key={batch.id}
                  to={`/moderation/administration/imports/${batch.id}`}
                >
                  <h2>{batch.name}</h2>
                  <p>
                    {batch.items} uploads · {batch.pending} pending · {batch.failed} failed
                  </p>
                  <small>{new Date(batch.created_at).toLocaleString()}</small>
                </Link>
              ))}
            </div>
          )}
          {!data.count && (
            <p className="mod-card mod-empty">
              {id ? 'No uploads yet. This batch is saved.' : 'No browser import batches yet.'}
            </p>
          )}
          <Pager pagination={data} change={setPage} />
        </>
      )}
      {editing && <ImageEditor image={editing} close={() => setEditing(null)} saved={reload} />}
    </div>
  );
}
