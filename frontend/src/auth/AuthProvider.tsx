import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from '../api';
import type { Session } from '../api';
import { AuthContext } from './context';
import { connectAccount } from './live';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session>({ user: null, restrictions: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const userId = session.user?.id;
  const generation = useRef(0);
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
  };
  return (
    <AuthContext.Provider value={{ ...session, loading, error, refresh, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}
