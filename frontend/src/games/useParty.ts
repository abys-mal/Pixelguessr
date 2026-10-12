import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../api';
import { connectParty, partyApi, type PartyConnection, type PartyState } from './parties';

export function useParty(code: string) {
  const [state, setState] = useState<PartyState | null>(null);
  const [loading, setLoading] = useState(true);
  const [joinNeeded, setJoinNeeded] = useState(false);
  const [error, setError] = useState('');
  const [connection, setConnection] = useState(false);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [now, setNow] = useState(0);
  const latest = useRef<PartyState | null>(null);
  const anchor = useRef({ server: 0, local: 0 });
  const stream = useRef<PartyConnection | null>(null);
  const lock = useRef(false);
  const alive = useRef(true);
  const requests = useRef(new Map<string, string>());
  const accept = useCallback((next: PartyState) => {
    if (!alive.current) return;
    const previous = latest.current;
    if (
      previous &&
      (next.revision < previous.revision ||
        (next.revision === previous.revision && next.server_now < previous.server_now))
    )
      return;
    if (previous?.round?.id !== next.round?.id || previous?.round?.status !== next.round?.status)
      setFeedback('');
    latest.current = next;
    anchor.current = { server: Date.parse(next.server_now), local: performance.now() };
    setNow(anchor.current.server);
    setState(next);
    setJoinNeeded(false);
    setLoading(false);
  }, []);
  useEffect(() => {
    alive.current = true;
    let disposed = false;
    let reading = false;
    let online = false;
    const read = async () => {
      if (disposed || reading) return;
      reading = true;
      try {
        const next = await partyApi.current(code);
        if (disposed) return;
        accept(next);
        setError('');
        if (!stream.current)
          stream.current = connectParty(code, accept, (connected) => {
            online = connected;
            if (!disposed) setConnection(connected);
          });
      } catch (err) {
        if (disposed) return;
        if (err instanceof ApiError && err.status === 404) setJoinNeeded(true);
        else {
          setError(err instanceof Error ? err.message : 'Unable to load this party.');
          if (err instanceof ApiError && err.status === 410) {
            setState(null);
            latest.current = null;
            stream.current?.close();
            stream.current = null;
          }
        }
        setLoading(false);
      } finally {
        reading = false;
      }
    };
    void read();
    const poll = setInterval(() => {
      if (!online && !document.hidden) void read();
    }, 3000);
    const refresh = () => {
      if (!document.hidden) void read();
    };
    const timer = setInterval(
      () => setNow(anchor.current.server + performance.now() - anchor.current.local),
      100,
    );
    window.addEventListener('online', refresh);
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      disposed = true;
      alive.current = false;
      clearInterval(poll);
      clearInterval(timer);
      stream.current?.close();
      stream.current = null;
      window.removeEventListener('online', refresh);
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [code, accept]);
  const perform = async (key: string, action: (requestId: string) => Promise<PartyState>) => {
    if (lock.current) return false;
    lock.current = true;
    setBusy(true);
    setError('');
    const requestId = requests.current.get(key) ?? crypto.randomUUID();
    requests.current.set(key, requestId);
    try {
      accept(await action(requestId));
      requests.current.delete(key);
      return true;
    } catch (err) {
      if (alive.current) setError(err instanceof Error ? err.message : 'Try again.');
      if (err instanceof ApiError && err.status < 500) requests.current.delete(key);
      return false;
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  };
  return {
    state,
    loading,
    joinNeeded,
    error,
    connection,
    busy,
    feedback,
    now,
    join: (name: string) => perform('join', () => partyApi.join(code, name)),
    settings: (settings: PartyState['settings']) =>
      perform('settings', () => partyApi.settings(code, settings)),
    action: (action: 'start' | 'lobby') =>
      perform(`${action}:${state?.match_id}`, (id) => partyApi.action(code, action, id)),
    async guess(text: string) {
      const round = latest.current?.round;
      if (
        !round ||
        round.status !== 'active' ||
        round.me.solved ||
        (round.me.cooldown_until && now < Date.parse(round.me.cooldown_until))
      )
        return false;
      return perform(`guess:${round.id}:${text}`, async (request_id) => {
        const data = { round_id: round.id, guess: text, request_id };
        const reply = await (stream.current
          ? stream.current.guess(data)
          : partyApi.guess(code, data));
        if (
          alive.current &&
          latest.current?.round?.id === round.id &&
          reply.state.round?.id === round.id
        )
          setFeedback(reply.result === 'incorrect' ? 'Incorrect. −50 points.' : 'Correct');
        return reply.state;
      });
    },
    async leave() {
      if (lock.current) return false;
      lock.current = true;
      setBusy(true);
      try {
        await partyApi.leave(code);
        return true;
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unable to leave.');
        return false;
      } finally {
        lock.current = false;
        if (alive.current) setBusy(false);
      }
    },
  };
}
