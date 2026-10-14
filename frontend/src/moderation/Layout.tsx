import { useEffect, useRef } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/context';
import { useData } from './useData';
import { Feedback, Loading } from './components';
import { root, type Overview } from './api';
import './moderation.css';

export function ModerationLayout() {
  const { user, loading } = useAuth();
  const { data, error, reload } = useData<Overview>(root);
  const { pathname } = useLocation();
  const main = useRef<HTMLElement>(null);
  useEffect(() => {
    main.current?.focus();
    window.scrollTo(0, 0);
  }, [pathname]);
  if (loading)
    return (
      <div className="mod-gate">
        <Loading error="" retry={reload} />
      </div>
    );
  if (!user?.moderation_access)
    return (
      <div className="mod-gate">
        <h1>Moderator access required</h1>
        <p>This workspace is available to authorized moderators and administrators.</p>
        <Link to={user ? '/' : '/login'}>{user ? 'Return to Game' : 'Sign in'}</Link>
      </div>
    );
  if (!data)
    return (
      <div className="mod-gate">
        <Loading error={error} retry={reload} />
        <Link to="/">Return to Game</Link>
      </div>
    );
  return (
    <div className="mod-shell">
      <a className="skip-link" href="#mod-main">
        Skip to workspace
      </a>
      <aside className="mod-sidebar">
        <Link className="mod-brand" to="/moderation">
          <span className="mod-brand-grid" aria-hidden="true">
            ▦
          </span>
          <span>
            pixelguessr<span className="brand-dot">.</span>
            <small>MODERATION</small>
          </span>
        </Link>
        <nav aria-label="Moderation navigation">
          {[
            ['', 'Home', '⌂'],
            ['/players', 'Players', '◎'],
            ['/reports', 'Reports', '▤'],
            ['/appeals', 'Appeals', '↶'],
          ].map(([path, title, icon]) => (
            <NavLink key={title} to={'/moderation' + path} end={!path}>
              <span aria-hidden="true">{icon}</span>
              {title}
            </NavLink>
          ))}
        </nav>
        <div className="mod-sidebar-footer">
          <p>
            @{user.username}
            <small>{data.administrator ? 'Administrator' : 'Moderator'}</small>
          </p>
          {data.administrator && <a href="/admin/">Django Admin ↗</a>}
          <Link className="mod-return" to="/">
            ← Return to Game
          </Link>
        </div>
      </aside>
      <main id="mod-main" className="mod-main" ref={main} tabIndex={-1}>
        <Feedback error={error} />
        <Outlet />
      </main>
    </div>
  );
}
