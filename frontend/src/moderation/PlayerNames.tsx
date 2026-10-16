import { useEffect, useId, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError } from '../api';
import { post, root, type Player } from './api';
import { Dialog, Feedback } from './components';

export function PlayerNames({
  player,
  close,
  saved,
}: {
  player: Player;
  close: () => void;
  saved: () => void;
}) {
  const id = useId();
  const saving = useRef(false);
  const [username, setUsername] = useState(player.username);
  const [displayName, setDisplayName] = useState(player.display_name);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [fields, setFields] = useState<Record<string, string[]>>({});
  const usernameInput = useRef<HTMLInputElement>(null);
  const displayInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (pending) return;
    if (fields.username) usernameInput.current?.focus();
    else if (fields.display_name) displayInput.current?.focus();
  }, [fields, pending]);
  const changed = username !== player.username || displayName !== player.display_name;
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving.current || !changed) return;
    saving.current = true;
    setPending(true);
    setError('');
    setFields({});
    try {
      await post(`${root}players/${player.id}/names/`, {
        ...(username !== player.username ? { username } : {}),
        ...(displayName !== player.display_name ? { display_name: displayName } : {}),
      });
      saved();
      close();
    } catch (error) {
      const errors = error instanceof ApiError ? (error.fields ?? {}) : {};
      setFields(errors);
      if (!errors.username && !errors.display_name) setError((error as Error).message);
    } finally {
      saving.current = false;
      setPending(false);
    }
  };
  return (
    <Dialog title="Edit player names" close={close} pending={pending}>
      <form className="mod-form" onSubmit={(event) => void submit(event)}>
        <label htmlFor={`${id}-username`}>Username</label>
        <input
          ref={usernameInput}
          id={`${id}-username`}
          name="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          required
          maxLength={150}
          autoCapitalize="none"
          spellCheck={false}
          disabled={pending}
          aria-invalid={!!fields.username}
          aria-describedby={fields.username ? `${id}-username-error` : undefined}
        />
        {fields.username && (
          <p className="mod-field-error" id={`${id}-username-error`} role="alert">
            {fields.username.join(' ')}
          </p>
        )}
        <label htmlFor={`${id}-display`}>Display name</label>
        <input
          ref={displayInput}
          id={`${id}-display`}
          name="display_name"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          maxLength={40}
          disabled={pending}
          aria-invalid={!!fields.display_name}
          aria-describedby={fields.display_name ? `${id}-display-error` : `${id}-display-help`}
        />
        {fields.display_name && (
          <p className="mod-field-error" id={`${id}-display-error`} role="alert">
            {fields.display_name.join(' ')}
          </p>
        )}
        <p className="mod-muted" id={`${id}-display-help`}>
          Up to 40 characters. Leave blank to use the username.
        </p>
        <Feedback error={error} />
        <div className="mod-actions">
          <button className="mod-button subtle" type="button" disabled={pending} onClick={close}>
            Cancel
          </button>
          <button className="mod-button" disabled={pending || !changed}>
            {pending ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
