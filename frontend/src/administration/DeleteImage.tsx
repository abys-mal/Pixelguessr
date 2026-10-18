import { useState } from 'react';
import { useAuth } from '../auth/context';
import { ActionIcon } from '../components/ActionIcon';
import { Dialog, Feedback } from '../moderation/components';
import { send, type LibraryImage } from './api';

export function DeleteImage({
  image,
  deleted,
}: {
  image: Pick<LibraryImage, 'id' | 'canonical_answer' | 'status'>;
  deleted: () => void;
}) {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  if (!user?.administrator || !['rejected', 'retired'].includes(image.status)) return null;
  return (
    <>
      <button
        className="mod-icon-button admin-delete-image"
        type="button"
        aria-label={`Permanently delete image: ${image.canonical_answer}`}
        title="Permanently delete image"
        onClick={() => {
          setError('');
          setOpen(true);
        }}
      >
        <ActionIcon name="trash-2" />
      </button>
      {open && (
        <Dialog title="Permanently delete image?" close={() => setOpen(false)} pending={pending}>
          <p>
            <strong>{image.canonical_answer}</strong> · {image.id}
          </p>
          <p>
            This irreversibly removes the library record and its private image file. Historical
            matches and scores remain. Removed player image content is redacted and a generic
            contribution receipt remains. A file shared by another image is retained.
          </p>
          <Feedback error={error} />
          <div className="mod-actions">
            <button className="mod-button subtle" disabled={pending} onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button
              className="mod-button danger"
              disabled={pending}
              onClick={async () => {
                if (pending) return;
                setPending(true);
                setError('');
                try {
                  await send(`images/${image.id}/delete/`, { confirm: true });
                  setOpen(false);
                  deleted();
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setPending(false);
                }
              }}
            >
              {pending ? 'Deleting…' : 'Delete Permanently'}
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
