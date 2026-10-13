import { useEffect, useRef, useState, type CSSProperties } from 'react';
import type { DuelRound } from './ranked';

type DecodedFrame = {
  url: string;
  id: string;
  tiles: Set<number>;
  retirePrevious: () => void;
  release: () => void;
};

// Only authorized masked frames enter the queue. Slow decodes finish; retries
// load the latest snapshot, with backoff shared across a transient outage.
export function RankedReveal({ round }: { round: DuelRound | null }) {
  const [frame, setFrame] = useState<DecodedFrame | null>(null);
  const [failedRound, setFailedRound] = useState<string | null>(null);
  const enqueue = useRef<((next: DuelRound, force?: boolean) => void) | null>(null);
  const roundId = round?.id;
  useEffect(() => {
    let disposed = false;
    let busy = false;
    let latest: DuelRound | null = null;
    let loadedKey = '';
    let blocked = false;
    let failures = 0;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const urls = new Set<string>();
    const release = (url: string) => {
      if (urls.delete(url)) URL.revokeObjectURL(url);
    };
    const load = async () => {
      if (disposed || busy || retry !== undefined || blocked || !latest) return;
      if (latest.image_url === loadedKey) return;
      busy = true;
      const target = latest;
      let url: string | undefined;
      let committed = false;
      let transient = true;
      try {
        const response = await fetch(target.image_url, {
          credentials: 'same-origin',
          signal: controller.signal,
        });
        if (!response.ok) {
          // Retry network/server failures, timeouts and rate limits. Other client
          // errors need an explicit reload or a new round, even if snapshots arrive.
          transient = response.status >= 500 || [408, 429].includes(response.status);
          throw new Error('Unable to load this reveal.');
        }
        const count = response.headers.get('X-Revealed-Tiles');
        if (count !== null && Number(count) !== target.revealed_tiles.length)
          throw new Error('Reveal frame does not match its snapshot.');
        const blob = await response.blob();
        if (disposed) return;
        url = URL.createObjectURL(blob);
        urls.add(url);
        const image = new Image();
        image.src = url;
        await image.decode();
        if (disposed) return;
        const decodedUrl = url;
        const previous = [...urls].filter((value) => value !== decodedUrl);
        committed = true;
        loadedKey = target.image_url;
        failures = 0;
        setFrame({
          url: decodedUrl,
          id: target.id,
          tiles: new Set(target.revealed_tiles),
          retirePrevious: () => previous.forEach(release),
          release: () => release(decodedUrl),
        });
        setFailedRound(null);
      } catch {
        if (!disposed) {
          setFailedRound(target.id);
          blocked = !transient;
          if (transient) {
            const delay = Math.min(8000, 500 * 2 ** failures);
            failures = Math.min(failures + 1, 4);
            retry = setTimeout(() => {
              retry = undefined;
              void load();
            }, delay);
          }
        }
      } finally {
        if (url && !committed) release(url);
        busy = false;
      }
      // A successful slow frame may have been superseded during decoding.
      if (!disposed && latest?.image_url !== loadedKey) void load();
    };
    enqueue.current = (next, force = false) => {
      latest = next;
      if (force) {
        clearTimeout(retry);
        retry = undefined;
        failures = 0;
        blocked = false;
        loadedKey = '';
      }
      void load();
    };
    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(retry);
      for (const url of urls) release(url);
      enqueue.current = null;
    };
  }, [roundId]);
  useEffect(() => {
    if (round) enqueue.current?.(round);
  }, [round]);
  useEffect(() => {
    // Covers decoded frames React skipped while batching, without retiring an
    // image that is still on screen or another frame currently being decoded.
    frame?.retirePrevious();
    return () => frame?.release();
  }, [frame]);
  const current = frame?.id === roundId ? frame : null;
  const grid = round?.grid_size ?? 20;
  return (
    <div className="reveal-stage ranked-reveal" style={{ '--grid': grid } as CSSProperties}>
      {current && (
        <img
          className="game-image"
          src={current.url}
          alt={round?.completion?.answer ?? 'Partially revealed mystery image'}
        />
      )}
      <div className="game-tiles" aria-hidden="true">
        {Array.from({ length: grid * grid }, (_, i) => (
          <i key={`${roundId}-${i}`} className={current?.tiles.has(i) ? 'is-revealed' : ''} />
        ))}
      </div>
      {failedRound === roundId && (
        <div className="image-retry" role="alert">
          Picture interrupted.{' '}
          <button
            onClick={() => {
              if (round) enqueue.current?.(round, true);
            }}
          >
            Reload picture
          </button>
        </div>
      )}
    </div>
  );
}
