import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

export function Badge({ children, tone = '' }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function PageHeading({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      {children && <p className="lede">{children}</p>}
    </header>
  );
}
export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel empty-state">
      <div className="empty-icon" aria-hidden="true">
        ▦
      </div>
      <h2>{title}</h2>
      <p>{children}</p>
    </section>
  );
}
export function SignInPrompt({ feature }: { feature: string }) {
  return (
    <EmptyState title="Make yourself at home">
      Sign in to {feature}. <Link to="/login">Sign in</Link> or{' '}
      <Link to="/register">create an account</Link>.
    </EmptyState>
  );
}
export function StatusMessage({ error, children }: { error?: boolean; children: ReactNode }) {
  return (
    <p role={error ? 'alert' : 'status'} className={`message ${error ? 'error' : ''}`}>
      {children}
    </p>
  );
}
