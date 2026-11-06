import { useEffect, useRef, useState } from 'react';

/** A thin bar for work that takes a while. Omit `value` when the amount done is unknown. */
export function Progress({ value, label }: { value?: number | null; label: string }) {
  const known = typeof value === 'number';
  return <div className="progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={known ? Math.round(value * 100) : undefined} data-indeterminate={known ? undefined : ''}>
    <span style={known ? { width: `${Math.max(0, Math.min(1, value)) * 100}%` } : undefined} />
  </div>;
}

/** How far along a job is, as a fraction or null when unknown, and roughly how long it has left. */
export interface Estimate { value: number | null; left: string }

// The rate is measured over about this long, so a burst or a stall moves the estimate gently.
const WINDOW = 30_000;
// No estimate until the work has been watched this long: the first seconds include starting up.
const SETTLE = 5_000;
// The estimate moves on this often, between the server's reports, which come a batch at a time.
const TICK = 1_000;
// The furthest the estimate runs ahead of the last report, so a stall holds the bar instead of filling it.
const AHEAD = 15_000;

function remaining(seconds: number) {
  if (seconds < 60) return 'Less than a minute left';
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return minutes === 1 ? 'About a minute left' : `About ${minutes} minutes left`;
  return `About ${Math.round(minutes / 60)} hours left`;
}

/** How far `done` has got towards `total`, carried on every second at the rate it has been moving, and the time left
 *  at that rate, like "About 3 minutes left". The bar and the time left come from the same estimate, so they move
 *  together, and the bar only goes back when more work arrives. Until there is enough to go on, the bar shows `done` and the time left is
 *  empty. `key` names the job, so a new job starts a fresh measurement; an empty key means none is running. */
export function useEstimate(key: string, done: number, total: number): Estimate {
  const samples = useRef<{ key: string; points: [number, number][]; shown: number }>({ key: '', points: [], shown: 0 });
  const [, tick] = useState(0);
  useEffect(() => {
    if (!key) return;
    const timer = setInterval(() => tick(n => n + 1), TICK);
    return () => clearInterval(timer);
  }, [key]);
  const now = Date.now();
  const track = samples.current;
  if (!key || track.key !== key || (track.points.length && done < track.points[track.points.length - 1][1])) { track.key = key; track.points = []; track.shown = 0; }
  if (!total) return { value: null, left: '' };
  if (!track.points.length || track.points[track.points.length - 1][1] !== done) track.points.push([now, done]);
  while (track.points.length > 2 && now - track.points[1][0] > WINDOW) track.points.shift();
  const [start, moved] = track.points[0];
  const [reported] = track.points[track.points.length - 1];
  let left = '';
  if (key && done < total && done > moved && now - start >= SETTLE) {
    // Once the work has stalled past AHEAD, the stall counts against the rate, so the time left grows while it lasts.
    const rate = (done - moved) / ((now - reported > AHEAD ? now : reported) - start);
    track.shown = Math.max(track.shown, Math.min(total, done + rate * Math.min(now - reported, AHEAD)));
    left = remaining((total - track.shown) / rate / 1000);
  }
  track.shown = Math.max(track.shown, done);
  return { value: track.shown / total, left };
}
