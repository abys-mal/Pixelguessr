import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, type Category } from '../api';
import { Dialog } from '../moderation/components';
import { StatusMessage } from '../components/ui';
import { contributionRoot } from './api';

export function NewSubmission({
  categories,
  close,
  saved,
}: {
  categories: Category[];
  close: () => void;
  saved: () => void;
}) {
  const [source, setSource] = useState('manual');
  const [preview, setPreview] = useState('');
  const previewRef = useRef('');
  const [dirty, setDirty] = useState(false);
  const [discard, setDiscard] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  useEffect(
    () => () => {
      if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    },
    [],
  );
  const attemptClose = () => {
    if (!pending) {
      if (dirty) setDiscard(true);
      else close();
    }
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    const data = new FormData(event.currentTarget);
    data.set(
      'accepted_synonyms',
      JSON.stringify(
        String(data.get('accepted_synonyms') ?? '')
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
      ),
    );
    setPending(true);
    setError('');
    try {
      await api(contributionRoot, { method: 'POST', body: data });
      saved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  };
  return (
    <>
      <Dialog title="New Submission" close={attemptClose} pending={pending}>
        <p className="muted">
          Share a clear image and a thoughtful answer. Every contribution is reviewed before it
          joins the game.
        </p>
        <form
          className="form-stack contribution-form"
          onChange={() => setDirty(true)}
          onSubmit={(e) => void submit(e)}
        >
          <label className="contribution-upload">
            Image upload
            <input
              name="image_file"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              required
              disabled={pending}
              onChange={(e) => {
                if (previewRef.current) URL.revokeObjectURL(previewRef.current);
                const file = e.target.files?.[0];
                const url = file ? URL.createObjectURL(file) : '';
                previewRef.current = url;
                setPreview(url);
              }}
            />
            {preview ? (
              <img src={preview} alt="Local image preview" />
            ) : (
              <span className="contribution-upload-prompt">
                Choose a picture to preview it here
              </span>
            )}
            <span className="field-help">
              Still JPEG, PNG or WebP · Up to 8 MB · 64–4096 px · Maximum 12 megapixels
            </span>
          </label>
          <label>
            Canonical answer
            <input name="canonical_answer" maxLength={120} required disabled={pending} />
          </label>
          <label>
            Category
            <select name="category" defaultValue="" required disabled={pending}>
              <option value="" disabled>
                Select category
              </option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Accepted synonyms (optional)
            <input
              name="accepted_synonyms"
              placeholder="Separate alternate answers with commas"
              disabled={pending}
            />
            <span className="field-help">Up to 30 synonyms; 120 characters each.</span>
          </label>
          <label>
            Image source / rights
            <select
              name="source"
              value={source}
              disabled={pending}
              onChange={(e) => setSource(e.target.value)}
            >
              <option value="manual">Created or owned by me</option>
              <option value="licensed">Licensed third-party image</option>
              <option value="ai">AI-generated image</option>
            </select>
          </label>
          <p className="field-help">
            {source === 'manual'
              ? 'Describe the license or permission you are offering for use in the game, and how you should be credited.'
              : source === 'licensed'
                ? 'Provide the original source and a license that permits this use, including required creator credit.'
                : 'Check your generation tool’s usage terms. Supply the tool or creator credit and applicable usage rights.'}
          </p>
          <label>
            Source / provenance URL {source === 'licensed' ? '(required)' : '(optional)'}
            <input
              name="source_url"
              type="url"
              maxLength={1000}
              required={source === 'licensed'}
              placeholder="https://…"
              disabled={pending}
            />
          </label>
          <label>
            License / usage rights
            <input
              name="license"
              required
              maxLength={160}
              placeholder="e.g. CC BY 4.0 or permission for in-game use"
              disabled={pending}
            />
          </label>
          <label>
            Attribution
            <input
              name="attribution"
              required
              maxLength={500}
              placeholder="Creator and required credit"
              disabled={pending}
            />
          </label>
          <label className="contribution-rights">
            <input
              type="checkbox"
              name="rights_acknowledged"
              value="true"
              required
              disabled={pending}
            />
            <span>
              I have permission to submit this image for use in Pixelguessr. Uploading does not
              transfer ownership or grant unlimited usage rights.
            </span>
          </label>
          {error && <StatusMessage error>{error}</StatusMessage>}
          <div className="contribution-actions">
            <button
              type="button"
              className="button secondary"
              disabled={pending}
              onClick={attemptClose}
            >
              Cancel
            </button>
            <button className="button" disabled={pending}>
              {pending ? 'Submitting…' : 'Submit for review'}
            </button>
          </div>
        </form>
      </Dialog>
      {discard && (
        <Dialog title="Discard this draft?" close={() => setDiscard(false)}>
          <p>Your entered details and selected image have not been submitted.</p>
          <div className="contribution-actions">
            <button className="button secondary" onClick={() => setDiscard(false)}>
              Keep editing
            </button>
            <button className="button contribution-danger" onClick={close}>
              Discard draft
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
