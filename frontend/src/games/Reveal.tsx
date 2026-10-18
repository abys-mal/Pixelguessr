import { useEffect, useState, type CSSProperties } from 'react';
import type { GameRound } from './singleplayer';

// The image is already masked by Django. This overlay only animates confirmed tiles.
type RevealRound = Pick<GameRound, 'id' | 'image_url' | 'grid_size' | 'revealed_tiles'> & {
  completion: { answer: string } | null;
};
export function Reveal({
  round,
  onFullReveal,
}: {
  round: RevealRound | null;
  onFullReveal?: (roundId: string) => void;
}) {
  const [frame, setFrame] = useState<{ url: string; roundId: string; tiles: Set<number> } | null>(
    null,
  );
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const imageUrl = round?.image_url;
  const roundId = round?.id;
  const tilesKey = round?.revealed_tiles.join(',') ?? '';
  useEffect(() => {
    if (!imageUrl || !roundId) return;
    const controller = new AbortController();
    let objectUrl: string | undefined;
    let disposed = false;
    let committed = false;
    const load = async () => {
      try {
        const response = await fetch(imageUrl, {
          credentials: 'same-origin',
          signal: controller.signal,
        });
        if (!response.ok) throw new Error('Unable to load this reveal.');
        const blob = await response.blob();
        if (disposed) return;
        objectUrl = URL.createObjectURL(blob);
        const image = new Image();
        image.src = objectUrl;
        await image.decode();
        if (disposed) return;
        committed = true;
        setFrame({
          url: objectUrl,
          roundId,
          tiles: new Set(tilesKey ? tilesKey.split(',').map(Number) : []),
        });
        setFailed(false);
      } catch {
        if (!disposed) setFailed(true);
      }
    };
    void load();
    return () => {
      disposed = true;
      controller.abort();
      if (objectUrl && !committed) URL.revokeObjectURL(objectUrl);
    };
  }, [imageUrl, roundId, tilesKey, retry]);
  useEffect(() => {
    const url = frame?.url;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [frame?.url]);
  const current = frame?.roundId === round?.id ? frame : null;
  const grid = round?.grid_size ?? 20;
  const completed = !!round?.completion;
  useEffect(() => {
    if (!onFullReveal || !completed || !current || current.tiles.size !== grid * grid) return;
    // The decoded, server-authorized full frame must paint before Parties changes layout.
    // Two animation frames leave a paint opportunity between committing the image and results.
    let painted = 0;
    const ready = requestAnimationFrame(() => {
      painted = requestAnimationFrame(() => onFullReveal(current.roundId));
    });
    return () => {
      cancelAnimationFrame(ready);
      cancelAnimationFrame(painted);
    };
  }, [current, grid, onFullReveal, completed]);
  return (
    <div
      className={`reveal-stage${onFullReveal && round?.completion ? ' party-final-frame' : ''}`}
      style={{ '--grid': grid } as CSSProperties}
    >
      {current && (
        <img
          className="game-image"
          src={current.url}
          alt={round?.completion ? round.completion.answer : 'Partially revealed mystery image'}
        />
      )}
      <div className="game-tiles" aria-hidden="true">
        {Array.from({ length: grid * grid }, (_, i) => (
          <i
            key={`${round?.id ?? 'ready'}-${i}`}
            className={current?.tiles.has(i) ? 'is-revealed' : ''}
            style={{ '--tile-delay': `${(i % 7) * 18}ms` } as CSSProperties}
          />
        ))}
      </div>
      {!round && (
        <div className="stage-intro">
          <span aria-hidden="true">▦</span>
          <p>The image appears when the game starts.</p>
        </div>
      )}
      {failed && (
        <div className="image-retry" role="alert">
          Picture interrupted.{' '}
          <button onClick={() => setRetry((v) => v + 1)}>Reload picture</button>
        </div>
      )}
    </div>
  );
}
