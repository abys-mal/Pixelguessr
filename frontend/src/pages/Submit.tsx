import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../api';
import type { Category, Page, Submission } from '../api';
import { useAuth } from '../auth/context';
import { Badge, PageHeading, SignInPrompt, StatusMessage } from '../components/ui';

export function Submit() {
  const { user, loading, restrictions } = useAuth();
  const [categories, setCategories] = useState<Category[]>([]);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [upload, setUpload] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [loaded, setLoaded] = useState(false);
  const restricted =
    restrictions?.blocked ||
    restrictions?.probation ||
    Boolean(restrictions?.unacknowledged_warnings.length);
  useEffect(() => {
    if (user && !restricted)
      void Promise.all([
        api<Category[]>('/api/library/categories/'),
        api<Page<Submission>>('/api/library/submissions/'),
      ])
        .then(([categories, page]) => {
          setCategories(categories);
          setSubmissions(page.results);
          setLoaded(true);
        })
        .catch((error: Error) => setError(error.message));
  }, [user, restricted]);
  if (loading) return <StatusMessage>Loading account…</StatusMessage>;
  if (!user) return <SignInPrompt feature="contribute an image" />;
  if (restricted)
    return (
      <StatusMessage error>
        Image submissions are unavailable for this account. Review your notices in Account settings.
      </StatusMessage>
    );
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const synonyms = String(data.get('accepted_synonyms') ?? '')
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean);
    data.set('accepted_synonyms', JSON.stringify(synonyms));
    setPending(true);
    setError('');
    setMessage('');
    try {
      const submission = await api<Submission>('/api/library/submissions/', {
        method: 'POST',
        body: data,
      });
      setSubmissions((items) => [submission, ...items].slice(0, 24));
      form.reset();
      setMessage('Image submitted. It will remain private until staff approve it.');
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setPending(false);
    }
  };
  return (
    <>
      <PageHeading eyebrow="ADD YOUR PERSPECTIVE" title="One image. A thousand aha moments.">
        Share a picture you have the right to use. Our staff will check the image, answers, license,
        and attribution.
      </PageHeading>
      <div className="submission-grid">
        <form className="panel form-stack" onSubmit={(event) => void submit(event)}>
          <div className="form-row">
            <label>
              Canonical answer
              <input name="canonical_answer" maxLength={120} required />
            </label>
            <label>
              Category
              <select name="category" required defaultValue="">
                <option value="" disabled>
                  Select category
                </option>
                {categories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label>
            Accepted synonyms <span className="muted">(optional)</span>
            <input name="accepted_synonyms" placeholder="Separate alternate answers with commas" />
            <span className="field-help">Up to 30 synonyms; 120 characters each.</span>
          </label>
          <div className="form-row">
            <label>
              Image source
              <select name="source" defaultValue="commons">
                <option value="commons">Wikimedia Commons</option>
                <option value="licensed">Other licensed source</option>
                <option value="ai">AI-generated</option>
                <option value="manual">Manual upload</option>
              </select>
            </label>
            <label>
              Storage
              <select
                value={upload ? 'upload' : 'external'}
                onChange={(event) => setUpload(event.target.value === 'upload')}
              >
                <option value="external">External HTTPS reference</option>
                <option value="upload">Upload a private image</option>
              </select>
            </label>
          </div>
          {upload ? (
            <label>
              Image file
              <input
                type="file"
                name="image_file"
                accept="image/jpeg,image/png,image/webp"
                required
              />
              <span className="field-help">
                Still JPEG, PNG, or WebP; up to 8 MB, 64–4096 px, 12 megapixels.
              </span>
            </label>
          ) : (
            <label>
              External image URL
              <input
                type="url"
                name="external_image_url"
                placeholder="https://…"
                maxLength={1000}
                required
              />
            </label>
          )}
          <label>
            Source / provenance URL
            <input type="url" name="source_url" placeholder="https://…" maxLength={1000} />
            <span className="field-help">
              Required for Wikimedia Commons and other licensed sources.
            </span>
          </label>
          <div className="form-row">
            <label>
              License / usage rights
              <input name="license" placeholder="e.g. CC BY-SA 4.0" maxLength={160} required />
            </label>
            <label>
              Attribution
              <input
                name="attribution"
                placeholder="Creator and required credit"
                maxLength={500}
                required
              />
            </label>
          </div>
          {error && <StatusMessage error>{error}</StatusMessage>}
          {message && <StatusMessage>{message}</StatusMessage>}
          <button className="button" disabled={pending || !loaded}>
            {pending ? 'Submitting…' : 'Submit for review ↗'}
          </button>
          <p className="field-help">
            Answers and storage references are private. Submission does not publish an image.
          </p>
        </form>
        <aside className="panel submission-history">
          <h2>Your recent submissions</h2>
          <p className="field-help">Showing up to 24 newest submissions.</p>
          {!loaded ? (
            <p className="muted">Loading submissions…</p>
          ) : submissions.length === 0 ? (
            <p className="muted">Your first contribution belongs here.</p>
          ) : (
            <ul>
              {submissions.map((submission) => (
                <li key={submission.id}>
                  <strong>{submission.canonical_answer}</strong>
                  <Badge>{submission.status}</Badge>
                  <small>{new Date(submission.created_at).toLocaleDateString()}</small>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </>
  );
}
