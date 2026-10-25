import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../api';
import { createRequestId } from '../requestId';
import { gameApi, type GameState } from './singleplayer';

const initial: GameState = { round: null, session: null };
export function useSingleplayer() {
  const [state, setState] = useState<GameState>(initial);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [empty, setEmpty] = useState(false);
  const [connection, setConnection] = useState('');
  const [feedback, setFeedback] = useState('');
  const [seconds, setSeconds] = useState(45);
  const latest = useRef<GameState>(initial);
  const anchor = useRef({ server: 0, local: 0 });
  const requests = useRef<Record<string, string>>({});
  const actionLock = useRef(false);
  const alive = useRef(true);
  const readLock = useRef(false);

  const accept = useCallback((next: GameState, allowNew = false) => {
    if (!alive.current) return;
    const previous = latest.current;
    if (previous.session && next.session) {
      if (previous.session.id !== next.session.id && !allowNew) return;
      if (
        previous.session.id === next.session.id &&
        (previous.session.revision > next.session.revision ||
          (previous.session.revision === next.session.revision &&
            Date.parse(previous.session.server_now) > Date.parse(next.session.server_now)))
      )
        return;
    }
    const changed = previous.round?.id !== next.round?.id;
    latest.current = next;
    if (changed) setFeedback('');
    if (next.round) {
      anchor.current = { server: Date.parse(next.round.server_now), local: performance.now() };
      setSeconds(
        next.round.status === 'active' && next.round.reveal_finishes_at
          ? Math.max(
              0,
              Math.ceil((Date.parse(next.round.reveal_finishes_at) - anchor.current.server) / 1000),
            )
          : 0,
      );
    }
    setState(next);
  }, []);

  const reconnect = useCallback(async () => {
    if (readLock.current || actionLock.current) return;
    readLock.current = true;
    const requestedSession = latest.current.session?.id;
    try {
      const next = await gameApi.current();
      if (latest.current.session?.id !== requestedSession) return;
      accept(next, next.session?.id !== requestedSession);
      if (alive.current) setConnection('');
    } catch (cause) {
      if (alive.current)
        setConnection(cause instanceof Error ? cause.message : 'Connection interrupted.');
    } finally {
      readLock.current = false;
      if (alive.current) setLoading(false);
    }
  }, [accept]);

  useEffect(() => {
    alive.current = true;
    const initialRead = window.setTimeout(() => {
      void reconnect();
    }, 0);
    const interval = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') void reconnect();
    }, 1000);
    const sync = () => {
      if (document.visibilityState !== 'hidden') void reconnect();
    };
    window.addEventListener('online', sync);
    window.addEventListener('focus', sync);
    document.addEventListener('visibilitychange', sync);
    return () => {
      alive.current = false;
      window.clearTimeout(initialRead);
      window.clearInterval(interval);
      window.removeEventListener('online', sync);
      window.removeEventListener('focus', sync);
      document.removeEventListener('visibilitychange', sync);
    };
  }, [reconnect]);

  const { round } = state;
  useEffect(() => {
    if (round?.status !== 'active' || !round.reveal_finishes_at) return;
    const finish = Date.parse(round.reveal_finishes_at);
    const timer = window.setInterval(() => {
      const now = anchor.current.server + performance.now() - anchor.current.local;
      setSeconds(Math.max(0, Math.ceil((finish - now) / 1000)));
    }, 100);
    return () => window.clearInterval(timer);
  }, [round?.status, round?.reveal_finishes_at]);

  const perform = async (action: 'start' | 'guess' | 'next' | 'forfeit', text = '') => {
    if (actionLock.current || (action !== 'start' && !latest.current.round)) return false;
    actionLock.current = true;
    setBusy(true);
    setError('');
    setEmpty(false);
    const id = latest.current.round?.id ?? '';
    const key = `${action}:${id}:${text}`;
    requests.current[key] ??= createRequestId();
    try {
      const next =
        action === 'start'
          ? await gameApi.start(requests.current[key])
          : action === 'next'
            ? await gameApi.next(id, requests.current[key])
            : action === 'forfeit'
              ? await gameApi.forfeit(id)
              : await gameApi.guess(id, text, requests.current[key]);
      accept(next, action === 'start');
      delete requests.current[key];
      setFeedback(next.result === 'incorrect' ? 'Incorrect' : '');
      setConnection('');
      return true;
    } catch (cause) {
      setEmpty(action === 'start' && cause instanceof ApiError && cause.code === 'library_empty');
      setError(cause instanceof Error ? cause.message : 'Request failed. Please retry.');
      if (cause instanceof ApiError && cause.status < 500) delete requests.current[key];
      if (cause instanceof ApiError && [404, 409, 410].includes(cause.status)) {
        actionLock.current = false;
        await reconnect();
      }
      return false;
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  };
  return {
    ...state,
    loading,
    busy,
    error,
    empty,
    connection,
    feedback,
    seconds,
    start: () => perform('start'),
    guess: (text: string) => perform('guess', text),
    next: () => perform('next'),
    forfeit: () => perform('forfeit'),
    reconnect,
  };
}
