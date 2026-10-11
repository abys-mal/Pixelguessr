import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../api';
import { gameApi, type GameRound } from './singleplayer';

export function useSingleplayer() {
  const [round, setRound] = useState<GameRound | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [empty, setEmpty] = useState(false);
  const [connection, setConnection] = useState('');
  const [feedback, setFeedback] = useState('');
  const [seconds, setSeconds] = useState(30);
  const latest = useRef<GameRound | null>(null);
  const anchor = useRef({ server: 0, local: 0 });
  const starting = useRef<string | null>(null);
  const guessing = useRef<{ text: string; id: string } | null>(null);
  const actionLock = useRef(false);
  const alive = useRef(true);
  const readLock = useRef(false);

  const accept = useCallback((next: GameRound | null, newRound = false) => {
    if (!alive.current) return;
    const previous = latest.current;
    // A delayed poll must never undo a correct guess or replace a newly started round.
    if (
      !newRound &&
      previous &&
      next &&
      (previous.id !== next.id ||
        (previous.status === 'solved' && next.status !== 'solved') ||
        Date.parse(previous.server_now) > Date.parse(next.server_now))
    )
      return;
    latest.current = next;
    if (next) {
      anchor.current = { server: Date.parse(next.server_now), local: performance.now() };
      setSeconds(
        next.status === 'solved'
          ? 0
          : Math.max(
              0,
              Math.ceil((Date.parse(next.reveal_finishes_at) - anchor.current.server) / 1000),
            ),
      );
    }
    setRound(next);
  }, []);

  const reconnect = useCallback(async () => {
    if (readLock.current || actionLock.current) return;
    readLock.current = true;
    const requestedId = latest.current?.id;
    try {
      const result = await gameApi.current();
      if (latest.current?.id !== requestedId) return;
      accept(result.round, !!result.round && result.round.id !== requestedId);
      if (alive.current) setConnection('');
    } catch (cause) {
      if (alive.current)
        setConnection(cause instanceof Error ? cause.message : 'Connection interrupted. Retrying…');
    } finally {
      readLock.current = false;
      if (alive.current) setLoading(false);
    }
  }, [accept]);

  useEffect(() => {
    alive.current = true;
    const initial = window.setTimeout(() => {
      void reconnect();
    }, 0);
    const interval = window.setInterval(() => {
      void reconnect();
    }, 1000);
    const sync = () => {
      if (document.visibilityState !== 'hidden') void reconnect();
    };
    window.addEventListener('online', sync);
    window.addEventListener('focus', sync);
    document.addEventListener('visibilitychange', sync);
    return () => {
      alive.current = false;
      window.clearTimeout(initial);
      window.clearInterval(interval);
      window.removeEventListener('online', sync);
      window.removeEventListener('focus', sync);
      document.removeEventListener('visibilitychange', sync);
    };
  }, [reconnect]);

  useEffect(() => {
    if (round?.status !== 'active') return;
    const timer = window.setInterval(() => {
      const now = anchor.current.server + performance.now() - anchor.current.local;
      setSeconds(Math.max(0, Math.ceil((Date.parse(round.reveal_finishes_at) - now) / 1000)));
    }, 100);
    return () => window.clearInterval(timer);
  }, [round?.status, round?.reveal_finishes_at]);

  const start = async () => {
    if (actionLock.current) return;
    actionLock.current = true;
    setBusy(true);
    setError('');
    setEmpty(false);
    setFeedback('');
    starting.current ??= crypto.randomUUID();
    try {
      const result = await gameApi.start(starting.current);
      accept(result.round, true);
      starting.current = null;
      guessing.current = null;
      setConnection('');
    } catch (cause) {
      setEmpty(cause instanceof ApiError && cause.code === 'library_empty');
      setError(cause instanceof Error ? cause.message : 'Unable to start. Please try again.');
      if (cause instanceof ApiError && cause.status < 500) starting.current = null;
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  };

  const guess = async (text: string) => {
    if (!latest.current || latest.current.status !== 'active' || actionLock.current) return false;
    actionLock.current = true;
    setBusy(true);
    setError('');
    if (!guessing.current || guessing.current.text !== text)
      guessing.current = { text, id: crypto.randomUUID() };
    try {
      const result = await gameApi.guess(latest.current.id, text, guessing.current.id);
      accept(result.round);
      guessing.current = null;
      setFeedback(
        result.result === 'incorrect' ? `“${text}” isn't it yet. Take another look!` : '',
      );
      setConnection('');
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to send. Try again.');
      if (cause instanceof ApiError && cause.status < 500) guessing.current = null;
      if (cause instanceof ApiError && [404, 410].includes(cause.status)) {
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
    round,
    loading,
    busy,
    error,
    empty,
    connection,
    feedback,
    seconds,
    start,
    guess,
    reconnect,
  };
}
