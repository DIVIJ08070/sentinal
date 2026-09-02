import { useEffect, useRef, useState } from 'react';

/**
 * Live alerts socket hook. Connects to `/ws/alerts` (the Vite dev proxy
 * forwards it to the backend with ws:true), parses each JSON frame and hands
 * it to `onMessage`. Reconnects automatically with exponential backoff
 * starting at 1s and capped at 10s; the backoff resets after any successful
 * connection. Returns `{ connected }` for a connection indicator.
 */
export function useAlertsSocket(onMessage) {
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let socket = null;
    let timer = null;
    let disposed = false;
    let delay = 1000;

    const connect = () => {
      if (disposed) return;
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
      socket = new WebSocket(`${proto}://${window.location.host}/ws/alerts`);

      socket.onopen = () => {
        delay = 1000;
        setConnected(true);
      };

      socket.onmessage = (event) => {
        let msg;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return; // ignore malformed frames
        }
        if (handlerRef.current) handlerRef.current(msg);
      };

      socket.onclose = () => {
        setConnected(false);
        if (disposed) return;
        timer = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 10000);
      };

      socket.onerror = () => {
        // onclose fires afterwards; closing here guarantees the reconnect path.
        try {
          socket.close();
        } catch {
          // already closed
        }
      };
    };

    connect();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      if (socket) {
        socket.onclose = null;
        try {
          socket.close();
        } catch {
          // already closed
        }
      }
    };
  }, []);

  return { connected };
}
