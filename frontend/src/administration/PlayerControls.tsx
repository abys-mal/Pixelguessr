import { useState } from 'react';
import { useAuth } from '../auth/context';
import { Dialog, Feedback } from '../moderation/components';
import type { PlayerDetail } from '../moderation/api';
import { send } from './api';

export function AdministratorPlayerControls({
  detail,
  saved,
}: {
  detail: PlayerDetail;
  saved: () => void;
}) {
  const { user, refresh } = useAuth();
  const [operation, setOperation] = useState('');
  const [rating, setRating] = useState(String(detail.player.rating));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  if (!user?.administrator) return null;
  const closures = detail.sanctions.filter((s) => s.active && s.kind === 'closed');
  return (
    <section className="mod-card">
      <h2>Administrator controls</h2>
      <p className="mod-muted">
        Elo changes affect future matchmaking; historical matches stay unchanged.
      </p>
      <div className="mod-actions">
        {[
          ['rating', 'Override Elo'],
          ['title', 'Honorary title'],
          ...(closures.length ? [['reopen', 'Reopen closed account']] : []),
        ].map(([key, label]) => (
          <button
            className="mod-button subtle"
            key={key}
            onClick={() => {
              setError('');
              setRating(String(detail.player.rating));
              setOperation(key);
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <Feedback message={message} />
      {operation && (
        <Dialog
          title={
            operation === 'rating'
              ? 'Override Elo'
              : operation === 'title'
                ? 'Honorary title'
                : 'Reopen closed account?'
          }
          close={() => setOperation('')}
          pending={pending}
        >
          <form
            className="mod-form"
            onSubmit={async (e) => {
              e.preventDefault();
              if (pending) return;
              setPending(true);
              setError('');
              const form = new FormData(e.currentTarget);
              try {
                await send(`players/${detail.player.id}/`, {
                  operation,
                  ...(operation === 'rating'
                    ? { rating: Number(rating) }
                    : operation === 'title'
                      ? { title: form.get('title') }
                      : {}),
                  reason: String(form.get('reason') ?? ''),
                });
                setMessage('Administrator changes saved.');
                setOperation('');
                saved();
                if (user.id === detail.player.id) void refresh();
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setPending(false);
              }
            }}
          >
            <p>
              Player: <strong>@{detail.player.username}</strong>
            </p>
            {operation === 'rating' && (
              <>
                <p>
                  Current Elo: {detail.player.rating} · Proposed Elo: {rating || '—'}
                </p>
                <label>
                  New Elo
                  <input
                    name="rating"
                    type="number"
                    min="0"
                    max="2147483647"
                    step="1"
                    required
                    value={rating}
                    onChange={(e) => setRating(e.target.value)}
                  />
                </label>
              </>
            )}
            {operation === 'title' && (
              <>
                <p>
                  At most one honorary title. Choosing another replaces the current title; this does
                  not change Elo or staff roles.
                </p>
                <label>
                  Honorary title
                  <select name="title" defaultValue={detail.player.title ?? ''}>
                    <option value="">No honorary title</option>
                    <option value="pro">PRO</option>
                    <option value="master">MASTER</option>
                    <option value="legend">LEGEND</option>
                  </select>
                </label>
              </>
            )}
            {operation === 'reopen' && (
              <>
                <p>
                  Reverse the closure and restore account access. Other active sanctions remain in
                  effect.
                </p>
                {closures.map((s) => (
                  <blockquote key={s.id}>{s.reason || 'No closure reason provided.'}</blockquote>
                ))}
              </>
            )}
            {operation !== 'title' && (
              <label>
                Reason (required)
                <textarea name="reason" rows={3} required maxLength={2000} />
              </label>
            )}
            <Feedback error={error} />
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
                {pending ? 'Saving…' : 'Confirm change'}
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </section>
  );
}
