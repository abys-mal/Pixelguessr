import { useEffect, useRef } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/context';

export function Layout() {
  const { user, error, refresh, restrictions } = useAuth();
  const { pathname } = useLocation();
  const main = useRef<HTMLElement>(null);
  useEffect(() => {
    main.current?.focus();
    window.scrollTo(0, 0);
  }, [pathname]);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <Link className="brand" to="/" aria-label="Pixelguessr home">
          <span className="brand-mark" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
          </span>
          pixelguessr<span className="brand-dot">.</span>
        </Link>
        <nav aria-label="Main navigation">
          <NavLink to="/" end>
            Play
          </NavLink>
          <NavLink to="/library">Image library</NavLink>
          <NavLink to="/leaderboards">Leaderboards</NavLink>
        </nav>
        <div className="account-nav">
          {user ? (
            <Link className="button compact secondary" to="/profile">
              {user.display_name || user.username} <span aria-hidden="true">↗</span>
            </Link>
          ) : (
            <Link className="button compact secondary" to="/login">
              Sign in <span aria-hidden="true">↗</span>
            </Link>
          )}
        </div>
      </header>
      {error && (
        <div className="service-banner" role="alert">
          {error}
          <button onClick={() => void refresh()}>Retry</button>
        </div>
      )}
      {restrictions &&
        (restrictions.probation || restrictions.unacknowledged_warnings.length > 0) && (
          <div className="service-banner">
            Your account has a moderation notice. <Link to="/settings">Review account notices</Link>
          </div>
        )}
      <main id="main" ref={main} tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="site-footer">
        <span>Find the bigger picture.</span>
        <span>Pixelguessr · Singleplayer</span>
        <Link to="/about">About & rules</Link>
      </footer>
    </div>
  );
}
