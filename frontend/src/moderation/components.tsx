import { useEffect, useId, useRef } from 'react';
import type { ReactNode } from 'react';

export function Feedback({ error, message }: { error?: string; message?: string }) {
  return (
    <>
      {error && (
        <p className="mod-feedback error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="mod-feedback" role="status">
          {message}
        </p>
      )}
    </>
  );
}

export function Loading({ error, retry }: { error: string; retry: () => void }) {
  return error ? (
    <div className="mod-card">
      <Feedback error={error} />
      <button className="mod-button subtle" onClick={retry}>
        Try again
      </button>
    </div>
  ) : (
    <p className="mod-loading" role="status">
      Loading workspace…
    </p>
  );
}

export function Heading({
  title,
  detail,
  children,
}: {
  title: string;
  detail: string;
  children?: ReactNode;
}) {
  return (
    <header className="mod-heading">
      <div>
        <p className="mod-eyebrow">MODERATION WORKSPACE</p>
        <h1>{title}</h1>
        <p>{detail}</p>
      </div>
      {children}
    </header>
  );
}

export function Dialog({
  title,
  children,
  close,
  pending = false,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
  pending?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog?.showModal();
    return () => {
      dialog?.close();
      if (opener?.isConnected) opener.focus();
    };
  }, []);
  return (
    <dialog
      className="mod-dialog"
      ref={ref}
      aria-labelledby={id}
      onCancel={(event) => {
        // A file input's native picker cancellation bubbles too; it is not a
        // request to close the containing dialog. Dialog Escape targets itself.
        if (event.target !== event.currentTarget) return;
        event.preventDefault();
        if (!pending) close();
      }}
    >
      <div className="mod-dialog-heading">
        <h2 id={id}>{title}</h2>
        <button
          className="mod-icon-button"
          type="button"
          aria-label="Close dialog"
          disabled={pending}
          onClick={close}
        >
          ×
        </button>
      </div>
      {children}
    </dialog>
  );
}

export function Pager({
  page,
  next,
  previous,
  change,
}: {
  page: number;
  next: string | null;
  previous: string | null;
  change: (page: number) => void;
}) {
  return (
    <nav className="mod-pager" aria-label="Pagination">
      <button className="mod-button subtle" disabled={!previous} onClick={() => change(page - 1)}>
        Previous
      </button>
      <span>Page {page}</span>
      <button className="mod-button subtle" disabled={!next} onClick={() => change(page + 1)}>
        Next
      </button>
    </nav>
  );
}
