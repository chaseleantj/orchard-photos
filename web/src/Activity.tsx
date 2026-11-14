import { useEffect, useRef, useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import type { Estimate } from './Progress';
import type { LibraryStatus, SearchCondition, Scan, SearchStatus } from './types';
import { SET_UP, megabytes, preparing } from './types';

/** One piece of background work: what it is, how far along in words, and how far as a fraction when known. */
interface Work { key: string; label: string; detail: string; value: number | null; error?: boolean }

// How long the tip that visual search is ready stays after setting up finishes.
const DONE_FOR = 10000;
const READY = 'Visual search is ready. Describe or drop an image above.';

function scanWork(scan: Scan): Work | null {
  if (scan.state !== 'scanning' || !scan.changed) return null;
  return { key: 'scan', label: 'Reading images', detail: `${(scan.done ?? 0).toLocaleString()} of ${scan.changed.toLocaleString()}`, value: (scan.done ?? 0) / scan.changed };
}

/** Visual search's work, named the same in the status line, the search options, Info and the map. */
export function searchWork(search: SearchStatus): Work | null {
  if (search.state === 'downloading') return { key: 'download', label: 'Downloading visual search', detail: `${megabytes(search.received ?? 0)} of ${megabytes(search.size ?? 0)} MB`, value: search.size ? (search.received ?? 0) / search.size : null };
  if (search.state === 'loading') return { key: 'load', label: 'Starting visual search', detail: '', value: null };
  if (search.state === 'indexing' && search.total) return { key: 'index', label: 'Preparing visual search', detail: `${search.indexed.toLocaleString()} of ${search.total.toLocaleString()}`, value: search.indexed / search.total };
  if (search.state === 'error' && !search.indexed) return { key: 'error', label: search.downloaded ? 'Visual search couldn’t start' : 'Visual search couldn’t download', detail: '', value: null, error: true };
  return null;
}

/** A job and how far it has got, as one phrase: "Reading images: 1,200 of 7,872". */
export const workLabel = (work: Work) => work.detail ? `${work.label}: ${work.detail}` : work.label;

/** What visual search is waiting on while it is starting, in the status line's words. */
export function waitingOn(library: LibraryStatus) {
  const work = searchWork(library.search);
  if (work) return workLabel(work);
  if (library.scan.state === 'scanning') return 'Ready once your images are read.';
  return preparing(library.search) ? 'Preparing visual search' : 'Ready once this folder has images.';
}

/** Work whose amount done is known, with its bar at the estimate that moves on every second. */
export const estimated = (work: Work | null, progress: Estimate) => work && work.value !== null ? { ...work, value: progress.value ?? work.value } : work;

/** Background work in the line under the search bar: a spinner, then the job and how far it has got. Each job opens
 *  Info, where the bars and time left are.
 *  Until visual search is set up, the line offers it, and the download's progress then takes its place. A first scan
 *  shows its own progress in the grid, so `gathering` leaves it out here; `hideError` drops a failure already seen. */
export function Activity({ library, condition, size, gathering, hideError, onOpen, onSetUp }: { library: LibraryStatus; condition: SearchCondition; size: number; gathering: boolean; hideError: boolean; onOpen: () => void; onSetUp: () => void }) {
  const search = searchWork(library.search);
  const jobs = [gathering ? null : scanWork(library.scan), search?.error && hideError ? null : search].filter((job): job is Work => !!job);
  // Setting up visual search ends with a word that it worked; routine preparing of new images ends quietly.
  const [done, setDone] = useState(false);
  const setup = useRef(false);
  const { state } = library.search;
  useEffect(() => {
    if (condition === 'starting') setup.current = true;
    if (state === 'ready' && setup.current) { setup.current = false; setDone(true); }
  }, [condition, state]);
  useEffect(() => { if (!done) return; const timer = setTimeout(() => setDone(false), DONE_FOR); return () => clearTimeout(timer); }, [done]);
  const ready = done && !jobs.length;
  return <div className="activity">
    {/* Announces what is happening when that changes, not every tick of the numbers. */}
    <span className="sr-only" aria-live="polite">{ready ? READY : jobs.map(job => job.label).join(', ')}</span>
    {/* A narrow window keeps the numbers and drops the words around them. */}
    {jobs.map(job => <button key={job.key} className={job.error ? 'activity-item error-copy' : 'activity-item'} aria-label={workLabel(job)} title="Show in Info" onClick={onOpen}>
      {!job.error && <LoaderCircle className="spinner" />}<span>{job.detail ? <><span className="wide-only">{job.label}: </span><span className="numbers">{job.detail}</span></> : job.label}</span>
    </button>)}
    {condition === 'off' && <button className="activity-item" title={`Find images by describing them. Downloads a ${megabytes(size)} MB model once, which runs on this computer.`} onClick={onSetUp}>
      <span>{SET_UP}<span className="wide-only"> · {megabytes(size)} MB, once</span></span>
    </button>}
    {ready && <button className="activity-item" title={READY} onClick={onOpen}><span>{READY}</span></button>}
  </div>;
}
