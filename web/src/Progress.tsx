import { useRef } from 'react';

/** A thin bar for work that takes a while. Omit `value` when the amount done is unknown. */
export function Progress({ value, label }: { value?: number | null; label: string }) {
  const known = typeof value === 'number';
  return <div className="progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={known ? Math.round(value * 100) : undefined} data-indeterminate={known ? undefined : ''}>
    <span style={known ? { width: `${Math.max(0, Math.min(1, value)) * 100}%` } : undefined} />
  </div>;
}

// The rate is measured over about this long, so a burst or a stall moves the estimate gently.
const WINDOW = 30_000;
// No estimate until the work has been watched this long: the first seconds include starting up.
const SETTLE = 5_000;

/** Roughly how long until `done` reaches `total`, from how fast it has been moving, like "About 3 minutes left".
 *  Empty until there is enough to go on. `key` names the job, so a new job starts a fresh measurement. */
export function useRemaining(key: string, done: number, total: number) {
  const samples = useRef<{ key: string; points: [number, number][] }>({ key: '', points: [] });
  const now = Date.now();
  const track = samples.current;
  if (track.key !== key || (track.points.length && done < track.points[track.points.length - 1][1])) { track.key = key; track.points = []; }
  if (!track.points.length || track.points[track.points.length - 1][1] !== done) track.points.push([now, done]);
  while (track.points.length > 2 && now - track.points[1][0] > WINDOW) track.points.shift();
  const [start, moved] = track.points[0];
  const elapsed = now - start;
  if (!key || done >= total || done <= moved || now - start < SETTLE) return '';
  const seconds = (total - done) / ((done - moved) / elapsed) / 1000;
  if (seconds < 60) return 'Less than a minute left';
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return minutes === 1 ? 'About a minute left' : `About ${minutes} minutes left`;
  return `About ${Math.round(minutes / 60)} hours left`;
}
