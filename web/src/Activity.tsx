import { LoaderCircle } from 'lucide-react';
import type { Estimate } from './Progress';
import type { LibraryStatus, SearchCondition, Scan, SearchStatus } from './types';
import { SET_UP, megabytes, preparing } from './types';

/** One piece of background work: what it is, how far along in words, and how far as a fraction when known. */
interface Work { key: string; label: string; detail: string; value: number | null; error?: boolean }

function scanWork(scan: Scan): Work | null {
  if (scan.state !== 'scanning' || !scan.changed) return null;
  return { key: 'scan', label: 'Reading images', detail: `${(scan.done ?? 0).toLocaleString()} of ${scan.changed.toLocaleString()}`, value: (scan.done ?? 0) / scan.changed };
}

/** Visual search's work, named the same in the status line, the search options and the map. */
export function searchWork(search: SearchStatus): Work | null {
  if (search.state === 'downloading') return { key: 'download', label: 'Downloading visual search', detail: `${megabytes(search.received ?? 0)} of ${megabytes(search.size ?? 0)} MB`, value: search.size ? (search.received ?? 0) / search.size : null };
  if (search.state === 'loading') return { key: 'load', label: 'Starting visual search', detail: '', value: null };
  if (search.state === 'indexing' && search.total) return { key: 'index', label: 'Preparing visual search', detail: `${search.indexed.toLocaleString()} of ${search.total.toLocaleString()}`, value: search.indexed / search.total };
  if (search.state === 'error' && !search.indexed) return { key: 'error', label: search.downloaded ? 'Visual search couldn’t start' : 'Visual search couldn’t download', detail: '', value: null, error: true };
  return null;
}

/** A job and how far it has got, as one phrase: "Reading images: 1,200 of 7,872". */
export const workLabel = (work: Work) => work.detail ? `${work.label}: ${work.detail}` : work.label;

/** Why visual search can't answer yet, for where it is chosen. How far along it is stays in the status line. */
export function waitingOn(library: LibraryStatus) {
  const { state } = library.search;
  if (state === 'downloading') return 'Ready once visual search has downloaded.';
  if (state === 'loading') return 'Ready once visual search has started.';
  if (library.scan.state === 'scanning' && state !== 'indexing') return 'Ready once your images are read.';
  return preparing(library.search) ? 'Ready once the first images are prepared.' : 'Ready once this folder has images.';
}

/** What the page under the status line is already saying, which the line then leaves out: a first scan's progress in
 *  the grid, visual search's progress or failure in the map, and an offer to set up visual search. */
export interface Below { scan: boolean; search: boolean; setUp: boolean }

/** Work whose amount done is known, with its bar at the estimate that moves on every second. */
export const estimated = (work: Work | null, progress: Estimate) => work && work.value !== null ? { ...work, value: progress.value ?? work.value } : work;

/** Background work in the line under the search bar: a spinner, then the job and how far it has got. A failure to set
 *  up visual search offers to try again.
 *  Until visual search is set up, the line offers it, and the download's progress then takes its place. Nothing the
 *  page says `below` is said here too. */
export function Activity({ library, condition, size, below, onSetUp }: { library: LibraryStatus; condition: SearchCondition; size: number; below: Below; onSetUp: () => void }) {
  const search = searchWork(library.search);
  const jobs = [below.scan ? null : scanWork(library.scan), below.search ? null : search].filter((job): job is Work => !!job);
  return <div className="activity">
    {/* Announces what is happening when that changes, not every tick of the numbers. */}
    <span className="sr-only" aria-live="polite">{jobs.map(job => job.label).join(', ')}</span>
    {/* A narrow window keeps the numbers and drops the words around them. */}
    {jobs.map(job => job.error
      ? <button key={job.key} className="activity-item error-copy" title={library.search.error} onClick={onSetUp}><span>{job.label}<span className="wide-only"> · Try again</span></span></button>
      : <span key={job.key} className="activity-item" role="status" aria-label={workLabel(job)}><LoaderCircle className="spinner" /><span>{job.detail ? <><span className="wide-only">{job.label}: </span><span className="numbers">{job.detail}</span></> : job.label}</span></span>)}
    {condition === 'off' && !below.setUp && <button className="activity-item" onClick={onSetUp}>
      <span>{SET_UP}<span className="wide-only"> · {megabytes(size)} MB, once</span></span>
    </button>}
  </div>;
}
