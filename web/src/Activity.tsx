import { useEffect, useRef, useState } from 'react';
import { Progress } from './Progress';
import type { LibraryStatus, Scan, SearchStatus } from './types';
import { megabytes } from './types';

/** One piece of background work: what it is, how far along in words, and how far as a fraction when known. */
interface Work { key: string; label: string; detail: string; value: number | null; error?: boolean }

// How long "Visual search is ready" stays after setting up finishes.
const DONE_FOR = 6000;

function scanWork(scan: Scan): Work | null {
  if (scan.state !== 'scanning' || !scan.changed) return null;
  return { key: 'scan', label: 'Reading images', detail: `${(scan.done ?? 0).toLocaleString()} of ${scan.changed.toLocaleString()}`, value: (scan.done ?? 0) / scan.changed };
}

/** Visual search's work, named the same in the status line, Library and the map. */
export function searchWork(search: SearchStatus): Work | null {
  if (search.state === 'downloading') return { key: 'download', label: 'Downloading visual search', detail: `${megabytes(search.received ?? 0)} of ${megabytes(search.size ?? 0)} MB`, value: search.size ? (search.received ?? 0) / search.size : null };
  if (search.state === 'loading') return { key: 'load', label: 'Starting visual search', detail: '', value: null };
  if (search.state === 'indexing' && search.total) return { key: 'index', label: 'Preparing visual search', detail: `${search.indexed.toLocaleString()} of ${search.total.toLocaleString()}`, value: search.indexed / search.total };
  if (search.state === 'error' && !search.indexed) return { key: 'error', label: search.downloaded ? 'Visual search couldn’t start' : 'Visual search couldn’t download', detail: '', value: null, error: true };
  return null;
}

const workLabel = (work: Work) => work.detail ? `${work.label} · ${work.detail}` : work.label;

/** Background work, in the line under the search bar. Each item opens Library, where the details are. A first scan
 *  shows its own progress in the grid, so `gathering` leaves it out here; `hideError` drops a failure already seen. */
export function Activity({ library, gathering, hideError, onOpen }: { library: LibraryStatus; gathering: boolean; hideError: boolean; onOpen: () => void }) {
  const search = searchWork(library.search);
  const jobs = [gathering ? null : scanWork(library.scan), search?.error && hideError ? null : search].filter((job): job is Work => !!job);
  // Setting up visual search ends with a word that it worked; routine preparing of new images ends quietly.
  const [done, setDone] = useState(false);
  const setup = useRef(false);
  const { state, indexed } = library.search;
  useEffect(() => {
    if (state === 'downloading' || state === 'loading' || (state === 'indexing' && !indexed)) setup.current = true;
    if (state === 'ready' && setup.current) { setup.current = false; setDone(true); }
  }, [state, indexed]);
  useEffect(() => { if (!done) return; const timer = setTimeout(() => setDone(false), DONE_FOR); return () => clearTimeout(timer); }, [done]);
  const ready = done && !jobs.length;
  return <div className="activity">
    {/* Announces what is happening when that changes, not every tick of the numbers. */}
    <span className="sr-only" aria-live="polite">{ready ? 'Visual search is ready' : jobs.map(job => job.label).join(', ')}</span>
    {jobs.map(job => <button key={job.key} className={job.error ? 'activity-item error-copy' : 'activity-item'} aria-label={workLabel(job)} title="Show in Library" onClick={onOpen}>
      {!job.error && <Progress value={job.value} label={job.label} />}<span>{job.label}{job.detail && <span className="numbers"> · {job.detail}</span>}</span>
    </button>)}
    {ready && <button className="activity-item" onClick={onOpen}><span>Visual search is ready</span></button>}
  </div>;
}
