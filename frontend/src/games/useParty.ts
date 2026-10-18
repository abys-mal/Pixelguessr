import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../api';
import { connectParty, partyApi, type PartyConnection, type PartyState } from './parties';

export function useParty(code: string) {
  const [state, setState] = useState<PartyState | null>(null);
  const [loading, setLoading] = useState(true);
  const [joinNeeded, setJoinNeeded] = useState(false);
  const [error, setError] = useState('');
  const [accessCode, setAccessCode] = useState('');
  const terminated = useRef(false);
  const [connection, setConnection] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const connectedOnce = useRef(false);
  const automaticJoinAttempted = useRef(false);
  const [transportVersion, setTransportVersion] = useState(0);
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
    if (!alive.current || terminated.current) return;
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
    if (next.status === 'aborted' || next.status === 'closed') {
      terminated.current = true;
      stream.current?.close();
      stream.current = null;
    }
  }, []);
  const denyAccess = useCallback((err: ApiError) => {
    if (!alive.current) return;
    terminated.current = true;
    stream.current?.close();
    stream.current = null;
    latest.current = null;
    setState(null);
    setJoinNeeded(false);
    setLoading(false);
    setError(err.message);
    setAccessCode(err.code || 'party_access_denied');
  }, []);
  useEffect(() => {
    alive.current = true;
    let disposed = false;
    let reading = false;
    let online = false;
    const startStream = () => {
      if (!stream.current && !terminated.current)
        stream.current = connectParty(
          code,
          accept,
          (connected) => {
            if (disposed) return;
            online = connected;
            setConnection(connected);
            setReconnecting(!connected && connectedOnce.current);
            if (connected) connectedOnce.current = true;
          },
          denyAccess,
        );
    };
    const read = async () => {
      if (disposed || reading || terminated.current) return;
      reading = true;
      try {
        const next = await partyApi.current(code);
        if (disposed) return;
        accept(next);
        setError('');
        startStream();
      } catch (err) {
        if (disposed) return;
        if (
          err instanceof ApiError &&
          err.code === 'membership_expired' &&
          !latest.current &&
          !automaticJoinAttempted.current
        ) {
          automaticJoinAttempted.current = true;
          try {
            const next = await partyApi.join(code, true);
            if (disposed) return;
            terminated.current = false;
            accept(next);
            setError('');
            startStream();
          } catch (joinError) {
            if (disposed) return;
            denyAccess(
              joinError instanceof ApiError
                ? joinError
                : new ApiError(
                    'Unable to rejoin this party. Check your connection and try again.',
                    503,
                    'membership_expired',
                  ),
            );
          }
          return;
        }
        if (err instanceof ApiError && (err.status === 403 || err.status === 410)) denyAccess(err);
        else if (err instanceof ApiError && err.status === 404) setJoinNeeded(true);
        else {
          setError(err instanceof Error ? err.message : 'Unable to load this party.');
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
  }, [code, accept, denyAccess, transportVersion]);
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
      if (
        err instanceof ApiError &&
        ['party_removed', 'party_banned', 'membership_expired'].includes(err.code || '')
      )
        denyAccess(err);
      else if (alive.current) setError(err instanceof Error ? err.message : 'Try again.');
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
    reconnecting,
    accessCode,
    busy,
    feedback,
    now,
    async join() {
      const joined = await perform('join', async () => {
        const next = await partyApi.join(code);
        terminated.current = false;
        setAccessCode('');
        connectedOnce.current = false;
        setReconnecting(false);
        return next;
      });
      if (joined) setTransportVersion((version) => version + 1);
      return joined;
    },
    kick: (target: string, ban: boolean) =>
      perform(`kick:${target}:${ban}`, (id) => partyApi.kick(code, target, ban, id)),
    settings: (settings: PartyState['settings']) =>
      perform('settings', () => partyApi.settings(code, settings)),
    action: (action: 'start' | 'lobby') =>
      perform(`${action}:${state?.match_id}`, (id) => partyApi.action(code, action, id)),
    next: () => {
      const round = latest.current?.round;
      return round
        ? perform(`next:${round.id}`, (id) => partyApi.next(code, round.id, id))
        : Promise.resolve(false);
    },
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
