import { useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, type Page } from '../api';
import { Feedback, Heading, Loading, Pager } from '../moderation/components';
import { useData } from '../moderation/useData';
import { adminRoot, send, type Batch, type ImportItem, type LibraryImage } from './api';
import { ImageEditor } from './Images';

export function ImageImports() {
  const navigate = useNavigate();
  const { id } = useParams();
  const [page, setPage] = useState(1);
  const [error, setError] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const saving = useRef(false);
  const [progress, setProgress] = useState('');
  const [editing, setEditing] = useState<LibraryImage | null>(null);
  const {
    data,
    error: loadError,
    reload,
  } = useData<Page<Batch> | Page<ImportItem>>(
    `${adminRoot}imports/${id ? `${id}/` : ''}?page=${page}`,
  );
  const upload = async () => {
    if (!id || saving.current || !files.length) return;
    saving.current = true;
    setBusy(true);
    setError('');
    try {
      for (let index = 0; index < files.length; index++) {
        setProgress(`Uploading ${index + 1} of ${files.length}: ${files[index].name}`);
        const body = new FormData();
        body.append('request_id', crypto.randomUUID());
        body.append('file', files[index]);
        try {
          await api(`${adminRoot}imports/${id}/`, { method: 'POST', body });
        } catch (e) {
          setError((previous) => `${previous}\n${files[index].name}: ${(e as Error).message}`);
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
    <>
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
              if (!busy) setFiles(Array.from(e.dataTransfer.files));
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
                onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              />
            </label>
            <p>{files.length} files selected</p>
            <button
              className="mod-button"
              disabled={busy || !files.length}
              onClick={() => void upload()}
            >
              {busy ? 'Uploading…' : 'Upload selected images'}
            </button>
            <p role="status">{progress}</p>
            <p className="mod-muted">
              Uploads are pending and labels are unreviewed. Incomplete batches never make images
              playable.
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
                <article className="mod-card" key={item.id}>
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
                      <button className="mod-button subtle" onClick={() => setEditing(item.image)}>
                        Prepare labels
                      </button>
                      <Link to={`/moderation/administration/images?q=${item.image.id}`}>
                        Review in Image Library →
                      </Link>
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
              {id
                ? 'No uploads yet. This batch is saved and ready when you are.'
                : 'No browser import batches yet.'}
            </p>
          )}
          <Pager page={page} next={data.next} previous={data.previous} change={setPage} />
        </>
      )}
      {editing && <ImageEditor image={editing} close={() => setEditing(null)} saved={reload} />}
    </>
  );
}
