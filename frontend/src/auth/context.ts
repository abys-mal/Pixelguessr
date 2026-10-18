import { createContext, useContext } from 'react';
import type { Session } from '../api';

export interface AuthState extends Session {
  loading: boolean;
  error: string;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
  dismissClosure?: () => void;
}
export const AuthContext = createContext<AuthState | null>(null);
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('AuthProvider is required.');
  return context;
}
