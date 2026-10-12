import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../api';
import { connectRanked, rankedApi, type ConnectionStatus, type DuelState } from './ranked';
export function useRanked(id: string) {
  const [state, setState] = useState<DuelState | null>(null);
  const [connection, setConnection] = useState<ConnectionStatus>('Connecting');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const current = useRef<DuelState | null>(null);
  const locked = useRef(false);
  const receive = useCallback(
    (next: DuelState) => {
      const old = current.current;
      if (
        next.id !== id ||
        (old &&
          (next.revision < old.revision ||
            (next.revision === old.revision && next.server_now < old.server_now)))
      )
        return;
      if (!old || old.round?.id !== next.round?.id || next.status === 'complete') setError('');
      current.current = next;
      setState(next);
    },
    [id],
  );
  useEffect(() => {
    let disposed = false;
    const safeReceive = (next: DuelState) => {
      if (!disposed) receive(next);
    };
    void rankedApi
      .state(id)
      .then(safeReceive)
      .catch((err: Error) => {
        if (!disposed) setError(err.message);
      });
    return () => {
      disposed = true;
    };
  }, [id, receive]);
  const complete = state?.status === 'complete';
  useEffect(() => {
    if (complete) return;
    return connectRanked<DuelState>(`/ws/matches/${id}/`, receive, setConnection, (err) =>
      setError(err.message),
    );
  }, [id, receive, complete]);
  useEffect(() => {
    if (complete || connection === 'Connected') return;
    let disposed = false;
    // Read-only recovery never renews presence. It can deliver a final No Contest
    // even when an expired socket is denied during the other player's grace window.
    const timer = setInterval(() => {
      void rankedApi
        .state(id)
        .then((next) => {
          if (!disposed) receive(next);
        })
        .catch((err: Error) => {
          if (!disposed && err instanceof ApiError && (err.status === 403 || err.status === 404)) {
            setError(err.message);
            clearInterval(timer);
          }
        });
    }, 3000);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  }, [id, receive, connection, complete]);
  const guess = async (text: string) => {
    const round = current.current?.round;
    if (
      locked.current ||
      !round ||
      round.status !== 'active' ||
      current.current?.status !== 'active' ||
      round.guessed_ids.includes(current.current.me_id)
    )
      return;
    locked.current = true;
    setPending(true);
    setError('');
    try {
      receive((await rankedApi.guess(id, round.id, text, crypto.randomUUID())).state);
    } catch (err) {
      setError((err as Error).message);
      try {
        receive(await rankedApi.state(id));
      } catch {
        /* Keep the actionable original error. */
      }
    } finally {
      locked.current = false;
      setPending(false);
    }
  };
  const leave = async () => {
    if (locked.current) return;
    locked.current = true;
    setPending(true);
    setError('');
    try {
      receive(await rankedApi.leave(id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      locked.current = false;
      setPending(false);
    }
  };
  return { state, connection, error, pending, guess, leave };
}
// Countdown display uses a local monotonic interval anchored to each server snapshot.
export function useServerTime(serverNow?: string) {
  const [tick, setTick] = useState({ server: serverNow, offset: 0 });
  useEffect(() => {
    if (!serverNow) return;
    const started = performance.now();
    const timer = setInterval(
      () => setTick({ server: serverNow, offset: performance.now() - started }),
      100,
    );
    return () => clearInterval(timer);
  }, [serverNow]);
  return (serverNow ? Date.parse(serverNow) : 0) + (tick.server === serverNow ? tick.offset : 0);
}
