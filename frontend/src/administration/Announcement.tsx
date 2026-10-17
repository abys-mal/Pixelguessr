import { useState } from 'react';
import { useAuth } from '../auth/context';
import { Dialog, Feedback } from '../moderation/components';
import { useData } from '../moderation/useData';
import { adminRoot, send, type Announcement } from './api';

export function StaffAnnouncement() {
  const { user } = useAuth();
  const { data, error, reload } = useData<{ announcement: Announcement | null }>(
    adminRoot + 'announcement/',
  );
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState(false);
  const [actionError, setActionError] = useState('');
  const [message, setMessage] = useState('');
  const notice = data?.announcement;
  return (
    <section className="mod-card mod-announcements">
      <p className="mod-eyebrow">STAFF UPDATES</p>
      <div className="mod-section-title">
        <h2>{notice?.published ? notice.title : 'Announcements'}</h2>
        {user?.administrator && (
          <button className="mod-button subtle" onClick={() => setEditing(true)}>
            Edit announcement
          </button>
        )}
      </div>
      {notice?.published ? (
        <>
          <p className="admin-announcement-body">{notice.body}</p>
          <small className="mod-muted">
            Updated {notice.updated_at ? new Date(notice.updated_at).toLocaleString() : '—'} · @
            {notice.editor}
            {notice.expires_at ? ` · Expires ${new Date(notice.expires_at).toLocaleString()}` : ''}
          </small>
        </>
      ) : (
        <p className="mod-muted">No announcements at the moment.</p>
      )}
      <Feedback error={error} message={message} />
      {editing && (
        <Dialog title="Staff announcement" close={() => setEditing(false)} pending={pending}>
          <form
            className="mod-form"
            onSubmit={async (e) => {
              e.preventDefault();
              if (pending) return;
              setPending(true);
              setActionError('');
              const form = new FormData(e.currentTarget);
              try {
                await send('announcement/', {
                  title: form.get('title'),
                  body: form.get('body'),
                  published: form.get('published') === 'on',
                  expires_at: form.get('expires_at')
                    ? new Date(String(form.get('expires_at'))).toISOString()
                    : null,
                  version: notice?.version ?? 0,
                });
                setEditing(false);
                setMessage('Staff announcement saved.');
                reload();
              } catch (e) {
                setActionError((e as Error).message);
              } finally {
                setPending(false);
              }
            }}
          >
            <label>
              Title
              <input name="title" maxLength={160} defaultValue={notice?.title ?? ''} />
            </label>
            <label>
              Body <span>Plain text, visible only to staff</span>
              <textarea name="body" rows={7} maxLength={5000} defaultValue={notice?.body ?? ''} />
            </label>
            <label>
              Publication
              <select name="published" defaultValue={notice?.published ? 'on' : 'off'}>
                <option value="off">Unpublished draft</option>
                <option value="on">Published</option>
              </select>
            </label>
            <label>
              Expires at <span>Optional, your local time</span>
              <input
                name="expires_at"
                type="datetime-local"
                defaultValue={
                  notice?.expires_at
                    ? new Date(
                        new Date(notice.expires_at).getTime() -
                          new Date(notice.expires_at).getTimezoneOffset() * 60000,
                      )
                        .toISOString()
                        .slice(0, 16)
                    : ''
                }
              />
            </label>
            <Feedback error={actionError} />
            <div className="mod-actions">
              <button
                className="mod-button subtle"
                type="button"
                disabled={pending}
                onClick={() => setEditing(false)}
              >
                Cancel
              </button>
              <button className="mod-button" disabled={pending}>
                {pending ? 'Saving…' : 'Save announcement'}
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </section>
  );
}
