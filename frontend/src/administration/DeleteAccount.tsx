import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/context';
import { Dialog, Feedback } from '../moderation/components';
import type { Player } from '../moderation/api';
import { send } from './api';

export function DeleteAccount({ player }: { player: Player }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  if (
    !user?.administrator ||
    user.id === player.id ||
    player.protected ||
    !player.deletion_eligible
  )
    return null;
  return (
    <>
      <button
        className="mod-button danger"
        onClick={() => {
          setError('');
          setOpen(true);
        }}
      >
        Permanently Delete Account
      </button>
      {open && (
        <Dialog title="Permanently delete account?" close={() => setOpen(false)} pending={pending}>
          <p>
            This irreversibly removes most account-associated data for{' '}
            <strong>@{player.username}</strong>. Closing and permanent deletion are different
            operations.
          </p>
          <p>
            Approved images and shared results remain anonymously. Licensed attribution and
            provenance are retained. Infrastructure backups follow their separate retention policy.
          </p>
          <form
            className="mod-form"
            onSubmit={async (event) => {
              event.preventDefault();
              if (pending) return;
              const form = event.currentTarget;
              const data = Object.fromEntries(new FormData(form));
              setPending(true);
              setError('');
              try {
                await send(`players/${player.id}/delete/`, data);
                navigate('/moderation/players', { replace: true, state: { accountDeleted: true } });
              } catch (e) {
                setError((e as Error).message);
              } finally {
                const input = form.querySelector<HTMLInputElement>('input[type="password"]');
                if (input) input.value = '';
                setPending(false);
              }
            }}
          >
            <label>
              Your current administrator password
              <input
                name="current_password"
                type="password"
                autoComplete="current-password"
                required
                maxLength={128}
                disabled={pending}
              />
            </label>
            <label>
              Deletion reason (required)
              <textarea name="reason" rows={3} required maxLength={2000} disabled={pending} />
            </label>
            <label>
              Type the exact username: {player.username}
              <input
                name="confirmation"
                required
                autoComplete="off"
                maxLength={150}
                disabled={pending}
              />
            </label>
            <Feedback error={error} />
            <div className="mod-actions">
              <button
                type="button"
                className="mod-button subtle"
                disabled={pending}
                onClick={() => setOpen(false)}
              >
                Cancel
              </button>
              <button className="mod-button danger" disabled={pending}>
                {pending ? 'Deleting…' : 'Delete Permanently'}
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </>
  );
}
