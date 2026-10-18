import { useId, useState, type FormEvent, type SyntheticEvent } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../api';
import { useAuth } from '../auth/context';
import { moderationCategories } from '../moderation/categories';
import { Dialog, Feedback } from '../moderation/components';
import { ActionIcon } from './ActionIcon';

export function ReportPlayer({ id, username }: { id: string; username: string }) {
  const { user, restrictions } = useAuth();
  const suspensionHelp = useId();
  const suspended = !!restrictions?.suspension;
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [tooltipLeft, setTooltipLeft] = useState<number | null>(null);
  if (suspended && open) setOpen(false);
  if (!user || user.id === id) return null;
  const showSuspensionHelp = (event: SyntheticEvent<HTMLSpanElement>) => {
    if (!suspended) return;
    const { left } = event.currentTarget.getBoundingClientRect();
    // Keep the overlay inside the viewport even beside a long username.
    setTooltipLeft(
      Math.max(12 - left, Math.min(0, document.documentElement.clientWidth - left - 272)),
    );
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending || suspended) return;
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
      <span
        className="profile-report-action"
        role={suspended ? 'group' : undefined}
        tabIndex={suspended ? 0 : undefined}
        aria-label={suspended ? 'Report unavailable' : undefined}
        aria-describedby={suspended ? suspensionHelp : undefined}
        onMouseEnter={showSuspensionHelp}
        onMouseLeave={(event) => {
          if (!event.currentTarget.contains(document.activeElement)) setTooltipLeft(null);
        }}
        onFocus={showSuspensionHelp}
        onBlur={() => setTooltipLeft(null)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setTooltipLeft(null);
        }}
      >
        <button
          className="button compact secondary profile-report-button"
          type="button"
          disabled={suspended}
          aria-describedby={suspended ? suspensionHelp : undefined}
          onClick={() => {
            setError('');
            setMessage('');
            setOpen(true);
          }}
        >
          <ActionIcon name="triangle-alert" /> Report
        </button>
        {suspended && (
          <span
            id={suspensionHelp}
            className="profile-report-tooltip"
            role="tooltip"
            hidden={tooltipLeft === null}
            style={{ left: tooltipLeft ?? 0 }}
          >
            Reporting is unavailable while your account is suspended.
          </span>
        )}
      </span>
      {message && (
        <span className="profile-report-feedback" role="status">
          {message}
        </span>
      )}
      {open &&
        !suspended &&
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
