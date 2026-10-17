import { useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../auth/context';
import { PageHeading, SignInPrompt, StatusMessage } from '../components/ui';

export function UserRoundXIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="9" cy="7" r="4" />
      <path d="M2 21v-2a7 7 0 0 1 14 0v2M17 7l5 5m0-5-5 5" />
    </svg>
  );
}

export function AccountClosure() {
  const { user, loading, refresh } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const password = useRef('');
  const leave = () => {
    password.current = '';
    setError('');
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    const form = event.currentTarget;
    setPending(true);
    setError('');
    try {
      if (step === 2) {
        const value = String(new FormData(form).get('current_password') ?? '');
        form.reset();
        await api('/api/auth/verify-closure-password/', {
          method: 'POST',
          body: JSON.stringify({ current_password: value }),
        });
        password.current = value;
        setStep(3);
      } else {
        await api('/api/auth/close-account/', {
          method: 'POST',
          body: JSON.stringify({
            current_password: password.current,
            confirmation: new FormData(form).get('confirmation'),
          }),
        });
        leave();
        await refresh();
        navigate('/account-closed', { replace: true });
      }
    } catch (e) {
      leave();
      setStep(2);
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  };
  if (loading) return <StatusMessage>Loading account…</StatusMessage>;
  if (!user && !pending) return <SignInPrompt feature="close your account" />;
  return (
    <div className="account-closure-page">
      <PageHeading eyebrow="YOUR ACCOUNT" title="Close account">
        A voluntary closure keeps your data and can be reviewed by an administrator.
      </PageHeading>
      <ol className="account-closure-steps" aria-label="Account closure steps">
        {['Understand', 'Verify', 'Confirm'].map((name, index) => (
          <li key={name} aria-current={step === index + 1 ? 'step' : undefined}>
            {index + 1}. {name}
          </li>
        ))}
      </ol>
      <section className="panel form-stack" aria-labelledby="closure-step-title">
        <h2 id="closure-step-title" tabIndex={-1}>
          {step === 1
            ? 'Understand account closure'
            : step === 2
              ? 'Verify your password'
              : 'Confirm closure'}
        </h2>
        {step === 1 ? (
          <>
            <p>Closing prevents normal account access and all gameplay while you are signed out.</p>
            <p>
              Your account data, game history, and approved images are preserved. This is not
              permanent deletion.
            </p>
            <p>
              An administrator may reopen your account. Contact an administrator if you want to
              request permanent deletion.
            </p>
            <p>
              Existing disciplinary sanctions and their history remain in place. Closure does not
              remove suspension or probation.
            </p>
            <button className="button" onClick={() => setStep(2)}>
              Continue to verification
            </button>
          </>
        ) : (
          <form className="form-stack" onSubmit={(e) => void submit(e)}>
            {step === 2 ? (
              <label>
                Current password
                <input
                  key="password"
                  name="current_password"
                  type="password"
                  autoComplete="current-password"
                  maxLength={128}
                  required
                  autoFocus
                  disabled={pending}
                />
              </label>
            ) : (
              <>
                <p>
                  Type <strong>CLOSE MY ACCOUNT</strong> to confirm. Your password will be checked
                  again when you submit.
                </p>
                <label>
                  Confirmation phrase
                  <input
                    key="phrase"
                    name="confirmation"
                    autoComplete="off"
                    maxLength={32}
                    required
                    autoFocus
                    disabled={pending}
                  />
                </label>
              </>
            )}
            {error && <StatusMessage error>{error}</StatusMessage>}
            <div className="account-change-actions">
              <button
                className={step === 3 ? 'button closure-confirm' : 'button'}
                disabled={pending}
              >
                {pending ? 'Please wait…' : step === 2 ? 'Verify password' : 'Close My Account'}
              </button>
              <button
                className="button secondary"
                type="button"
                disabled={pending}
                onClick={() => {
                  leave();
                  setStep(step - 1);
                }}
              >
                Back
              </button>
            </div>
          </form>
        )}
        <Link
          className="account-close-cancel"
          to="/settings/account"
          onClick={(e) => {
            if (pending) e.preventDefault();
            else leave();
          }}
          aria-disabled={pending}
          tabIndex={pending ? -1 : undefined}
        >
          Cancel and return to settings
        </Link>
      </section>
    </div>
  );
}

export function AccountClosed() {
  return (
    <div className="account-closure-page">
      <PageHeading eyebrow="YOUR ACCOUNT" title="Account closed">
        Your account has been voluntarily closed and you are signed out.
      </PageHeading>
      <section className="panel form-stack">
        <p>
          Your account data and game history remain preserved. Existing sanctions remain effective.
        </p>
        <p>Contact an administrator to request reopening or permanent deletion.</p>
        <Link className="button secondary" to="/">
          Return home
        </Link>
      </section>
    </div>
  );
}
