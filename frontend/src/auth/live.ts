import type { Session } from '../api';

export function connectAccount(
  receive: (session: Session) => void,
  connected: (value: boolean) => void,
) {
  let socket: WebSocket | null = null;
  let stopped = false;
  let retry: ReturnType<typeof setTimeout>;
  const open = () => {
    if (stopped) return;
    const active = new WebSocket(
      `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/account/`,
    );
    socket = active;
    const current = () => !stopped && socket === active;
    active.onopen = () => {
      if (current()) connected(true);
    };
    active.onmessage = (event) => {
      if (!current()) return;
      try {
        const message = JSON.parse(event.data);
        if (message.type === 'state') receive(message.state);
      } catch {
        /* Ignore malformed transport data. */
      }
    };
    active.onclose = (event) => {
      if (!current()) return;
      socket = null;
      connected(false);
      if (event.code !== 4403) retry = setTimeout(open, 2000);
    };
    active.onerror = () => {
      if (current()) active.close();
    };
  };
  retry = setTimeout(open, 0);
  return () => {
    stopped = true;
    clearTimeout(retry);
    if (socket) {
      const active = socket;
      socket = null;
      active.onmessage = active.onclose = active.onerror = null;
      if (active.readyState === WebSocket.OPEN) active.close();
      else if (active.readyState === WebSocket.CONNECTING) active.onopen = () => active.close();
    }
  };
}
