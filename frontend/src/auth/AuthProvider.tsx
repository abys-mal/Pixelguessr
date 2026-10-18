import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from '../api';
import type { Session } from '../api';
import { AuthContext } from './context';
import { useLocation, useNavigate } from 'react-router-dom';
import { connectAccount } from './live';

export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [session, setSession] = useState<Session>({ user: null, restrictions: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const userId = session.user?.id;
  const generation = useRef(0);
  const [noticeRoute, setNoticeRoute] = useState(location.key);
  const dismissClosure = useCallback(() => {
    setSession((current) => ({ ...current, account_closed: false, closure_message: undefined }));
  }, []);
  // A closure notice belongs only to the navigation entry where it was received.
  if (noticeRoute !== location.key) {
    setNoticeRoute(location.key);
    if (session.account_closed) dismissClosure();
  }
  useEffect(() => {
    if (!session.account_closed) return;
    const timer = setTimeout(dismissClosure, 10000);
    return () => clearTimeout(timer);
  }, [session.account_closed, dismissClosure]);
  const receive = useCallback((next: Session) => {
    generation.current += 1;
    setSession(next);
    setError('');
  }, []);
  const refresh = useCallback(async () => {
    const before = generation.current;
    try {
      const next = await api<Session>('/api/auth/me/');
      if (before === generation.current) receive(next);
    } catch {
      setError('Account service is unavailable. Please try again shortly.');
    } finally {
      setLoading(false);
    }
  }, [receive]);
  useEffect(() => {
    let active = true;
    void api<Session>('/api/auth/me/')
      .then((session) => {
        if (active) {
          setSession(session);
          setError('');
        }
      })
      .catch(() => {
        if (active) setError('Account service is unavailable. Please try again shortly.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    if (!userId) return;
    let live = true;
    let connected = false;
    const stop = connectAccount(
      (next) => {
        if (live) receive(next);
      },
      (value) => {
        connected = value;
      },
    );
    const timer = setInterval(() => {
      if (!connected) void refresh();
    }, 5000);
    const onFocus = () => void refresh();
    window.addEventListener('focus', onFocus);
    window.addEventListener('online', onFocus);
    return () => {
      live = false;
      stop();
      clearInterval(timer);
      window.removeEventListener('focus', onFocus);
      window.removeEventListener('online', onFocus);
    };
  }, [userId, receive, refresh]);
  const signOut = async () => {
    await api('/api/auth/logout/', { method: 'POST' });
    receive({ user: null, restrictions: null });
    navigate('/', { replace: true });
  };
  return (
    <AuthContext.Provider value={{ ...session, loading, error, refresh, signOut, dismissClosure }}>
      {children}
    </AuthContext.Provider>
  );
}
