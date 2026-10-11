import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from '../api';
import type { Session } from '../api';
import { AuthContext } from './context';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session>({ user: null, restrictions: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    try {
      setSession(await api<Session>('/api/auth/me/'));
      setError('');
    } catch {
      setError('Account service is unavailable. Please try again shortly.');
    } finally {
      setLoading(false);
    }
  }, []);
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
  const signOut = async () => {
    await api('/api/auth/logout/', { method: 'POST' });
    setSession({ user: null, restrictions: null });
  };
  return (
    <AuthContext.Provider value={{ ...session, loading, error, refresh, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}
