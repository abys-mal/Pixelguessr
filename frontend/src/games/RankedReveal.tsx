import { useEffect, useRef, useState, type CSSProperties } from 'react';
import type { DuelRound } from './ranked';

// Only authorized masked frames enter the queue. Slow loads finish instead of being
// repeatedly aborted by snapshots; pending intermediate frames are skipped.
export function RankedReveal({ round }: { round: DuelRound | null }) {
  const [frame, setFrame] = useState<{ url: string; id: string; tiles: Set<number> } | null>(null);
  const [failed, setFailed] = useState(false);
  const enqueue = useRef<((next: DuelRound, force?: boolean) => void) | null>(null);
  const roundId = round?.id;
  useEffect(() => {
    let disposed = false;
    let busy = false;
    let latest: DuelRound | null = null;
    let lastKey = '';
    const controller = new AbortController();
    const urls = new Set<string>();
    const load = async () => {
      if (busy) return;
      busy = true;
      while (!disposed && latest && latest.image_url !== lastKey) {
        const target = latest;
        lastKey = target.image_url;
        let url: string | undefined;
        let committed = false;
        try {
          const response = await fetch(target.image_url, {
            credentials: 'same-origin',
            signal: controller.signal,
          });
          if (!response.ok) throw new Error('Unable to load this reveal.');
          const count = response.headers.get('X-Revealed-Tiles');
          if (count !== null && Number(count) !== target.revealed_tiles.length)
            throw new Error('Reveal frame does not match its snapshot.');
          const blob = await response.blob();
          if (disposed) break;
          url = URL.createObjectURL(blob);
          urls.add(url);
          const image = new Image();
          image.src = url;
          await image.decode();
          if (disposed) break;
          committed = true;
          setFrame({ url, id: target.id, tiles: new Set(target.revealed_tiles) });
          setFailed(false);
        } catch {
          if (!disposed) setFailed(true);
        } finally {
          if (url && !committed) URL.revokeObjectURL(url);
        }
      }
      busy = false;
    };
    enqueue.current = (next, force = false) => {
      latest = next;
      if (force) lastKey = '';
      void load();
    };
    return () => {
      disposed = true;
      controller.abort();
      // Also release frames React may have skipped while batching rapid decodes.
      for (const url of urls) URL.revokeObjectURL(url);
      enqueue.current = null;
    };
  }, [roundId]);
  useEffect(() => {
    if (round) enqueue.current?.(round);
  }, [round]);
  useEffect(() => {
    const url = frame?.url;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [frame?.url]);
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
      {failed && (
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
