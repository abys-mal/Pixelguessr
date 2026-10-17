import { useState, type FormEvent } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../api';
import { useAuth } from '../auth/context';
import { moderationCategories } from '../moderation/categories';
import { Dialog, Feedback } from '../moderation/components';
import { ActionIcon } from './ActionIcon';

export function ReportPlayer({ id, username }: { id: string; username: string }) {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  if (!user || user.id === id) return null;
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError('');
    try {
      await api('/api/moderation/reports/', {
        method: 'POST',
        body: JSON.stringify({
          subject: id,
          category: form.get('category'),
          details: form.get('details'),
        }),
      });
      setOpen(false);
      setMessage('Report submitted. The moderation team will review it.');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  };
  return (
    <>
      <button
        className="button compact secondary profile-report-button"
        type="button"
        onClick={() => {
          setError('');
          setMessage('');
          setOpen(true);
        }}
      >
        <ActionIcon name="triangle-alert" /> Report
      </button>
      {message && (
        <span className="profile-report-feedback" role="status">
          {message}
        </span>
      )}
      {open &&
        createPortal(
          <Dialog title={`Report @${username}`} close={() => setOpen(false)} pending={pending}>
            <p>Your report is shared with staff, not the reported player.</p>
            <form className="mod-form" onSubmit={(e) => void submit(e)}>
              <label>
                Category
                <select name="category" defaultValue="fair_play">
                  {moderationCategories.map(([value, text]) => (
                    <option key={value} value={value}>
                      {text}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Reason for reporting
                <textarea name="details" required rows={5} maxLength={2000} />
              </label>
              <Feedback error={error} />
              <div className="mod-actions">
                <button
                  className="mod-button subtle"
                  type="button"
                  disabled={pending}
                  onClick={() => setOpen(false)}
                >
                  Cancel
                </button>
                <button className="mod-button" disabled={pending}>
                  {pending ? 'Submitting…' : 'Submit Report'}
                </button>
              </div>
            </form>
          </Dialog>,
          document.body,
        )}
    </>
  );
}
