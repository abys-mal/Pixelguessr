import { useEffect, useRef, useState } from 'react';
import { createRequestId } from '../requestId';

export function GameplayPreview({ url }: { url: string }) {
  const [run, setRun] = useState(createRequestId);
  const [reveal, setReveal] = useState(200);
  const [duration, setDuration] = useState(45);
  const [playing, setPlaying] = useState(false);
  const started = useRef(0);
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      const count = Math.min(
        400,
        Math.floor((400 * (performance.now() - started.current)) / (duration * 1000)),
      );
      setReveal(count);
      if (count === 400) setPlaying(false);
    }, 250);
    return () => clearInterval(timer);
  }, [playing, duration]);
  const restart = () => {
    setRun(createRequestId());
    setReveal(0);
    started.current = performance.now();
    setPlaying(true);
  };
  return (
    <section className="admin-gameplay-preview">
      <h3>Gameplay reveal preview</h3>
      <p className="mod-muted">
        Random scattered tiles, rendered by the actual server-side compositor.
      </p>
      <div className="mod-actions">
        <label>
          Preview duration
          <select
            value={duration}
            onChange={(event) => {
              setPlaying(false);
              setDuration(Number(event.target.value));
            }}
          >
            {[15, 30, 45, 60].map((seconds) => (
              <option key={seconds} value={seconds}>
                {seconds} seconds
              </option>
            ))}
          </select>
        </label>
        <button className="mod-button subtle" type="button" onClick={restart}>
          {playing || reveal === 400 ? 'Restart preview' : 'Play preview'}
        </button>
      </div>
      <label>
        Revealed tiles: {reveal} / 400
        <input
          type="range"
          min="0"
          max="400"
          step="20"
          value={reveal}
          onChange={(event) => {
            setPlaying(false);
            setReveal(Number(event.target.value));
          }}
        />
      </label>
      <img
        className="admin-large-preview"
        src={`${url}?reveal=${reveal}&run=${run}`}
        alt={`${reveal} of 400 tiles revealed`}
      />
    </section>
  );
}
