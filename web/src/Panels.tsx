import { Fragment, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Check, ChevronDown, ChevronRight, FolderOpen, Image as ImageIcon, X } from 'lucide-react';
import type { Facets, Filters, Model, Range, SearchMode, SearchStatus, Status } from './types';
import { APP_NAME, RANGES, UPDATE_REASON, defaults, megabytes, plural, post, request, searchable, setUpLabel, settingUp, typeLabel } from './types';
import { Progress } from './Progress';
import { searchWork } from './Activity';

// Room kept between a popover and the control above it, and between a popover and the window edge.
const OFFSET = 8;
const EDGE = 16;

/** A popover opened from `anchor`: under it, lined up with its right edge, or with its left edge and width for `menu`. */
function Popover({ label, anchor, menu, className, onClose, children }: { label: string; anchor: HTMLElement | null; menu?: boolean; className: string; onClose: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    const node = ref.current!;
    node.showModal();
    // The popover takes focus itself, so no control inside it is ringed until the keyboard moves there.
    node.focus();
    const place = () => {
      if (!anchor?.isConnected) return;
      const r = anchor.getBoundingClientRect();
      if (menu) node.style.width = `${r.width}px`;
      const width = node.offsetWidth;
      const left = Math.max(EDGE, Math.min(innerWidth - width - EDGE, menu ? r.left : r.right - width));
      Object.assign(node.style, { top: `${r.bottom + OFFSET}px`, left: `${left}px`, right: 'auto', maxHeight: `${innerHeight - r.bottom - OFFSET - EDGE}px` });
    };
    place();
    addEventListener('resize', place);
    return () => { removeEventListener('resize', place); node.close(); };
  }, [anchor, menu]);
  return <dialog ref={ref} tabIndex={-1} className={className} aria-label={label} onCancel={onClose} onClick={e => { if (e.target !== e.currentTarget) return; const r = ref.current!.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) onClose(); }}>{children}</dialog>;
}

export function Panel({ title, anchor, onClose, children }: { title: string; anchor: HTMLElement | null; onClose: () => void; children: React.ReactNode }) {
  // The header gains an edge once the body has scrolled under it.
  const [scrolled, setScrolled] = useState(false);
  return <Popover label={title} anchor={anchor} className="panel" onClose={onClose}>
    <header className={scrolled ? 'scrolled' : undefined}><h2>{title}</h2><button className="icon-button" aria-label={`Close ${title.toLowerCase()}`} onClick={onClose}><X /></button></header>
    <div className="panel-body" onScroll={e => setScrolled(e.currentTarget.scrollTop > 0)}>{children}</div>
  </Popover>;
}

/** A section that opens on click, marked with the app's own chevron. */
export function Disclosure({ summary, children }: { summary: string; children: React.ReactNode }) {
  return <details className="disclosure"><summary><ChevronRight />{summary}</summary>{children}</details>;
}

function Select({ label, value, onChange, disabled, children }: { label: string; value: string; onChange: (value: string) => void; disabled?: boolean; children: React.ReactNode }) {
  return <div className="select"><select aria-label={label} value={value} disabled={disabled} onChange={e => onChange(e.target.value)}>{children}</select><ChevronDown /></div>;
}

export function FilterPanel({ filters, anchor, onApply, onClose }: { filters: Filters; anchor: HTMLElement | null; onApply: (filters: Filters) => void; onClose: () => void }) {
  const [draft, setDraft] = useState(filters);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { request<Facets>('/api/facets').then(setFacets, e => setError((e as Error).message)); }, []);
  const invalid = draft.range === 'custom' && !!draft.from && !!draft.to && draft.from > draft.to;
  const folders = facets?.folders ?? [];
  const types = facets?.types ?? [];
  const loading = !facets && !error;
  return <Panel title="Filters" anchor={anchor} onClose={onClose}>
    <fieldset className="field"><legend>Folder</legend>
      <Select label="Folder" value={draft.folder} disabled={loading} onChange={folder => setDraft({ ...draft, folder })}>
        <option value="">{loading ? 'Loading folders…' : 'All folders'}</option>
        {/* A remembered choice that no longer exists stays listed, so the panel never misstates what is applied. */}
        {draft.folder && facets && !folders.some(f => f.path === draft.folder) && <option value={draft.folder}>{draft.folder} · no images</option>}
        {folders.map(f => <option key={f.path} value={f.path}>{f.path} · {f.count.toLocaleString()}</option>)}
      </Select>
      {facets && !folders.length && <p className="field-note">This folder has no subfolders with images.</p>}
    </fieldset>
    <fieldset className="field"><legend>File type</legend>
      <Select label="File type" value={draft.type} disabled={loading} onChange={type => setDraft({ ...draft, type })}>
        <option value="">All types</option>
        {draft.type && facets && !types.some(t => t.mime === draft.type) && <option value={draft.type}>{typeLabel(draft.type)} · no images</option>}
        {types.map(t => <option key={t.mime} value={t.mime}>{typeLabel(t.mime)} · {t.count.toLocaleString()}</option>)}
      </Select>
    </fieldset>
    <fieldset className="field"><legend>Date</legend>
      <Select label="Date" value={draft.range} onChange={range => setDraft({ ...draft, range: range as Range })}>{RANGES.map(({ range, label }) => <option key={range} value={range}>{label}</option>)}</Select>
      {draft.range === 'custom' && <div className="date-inputs"><label><span>From</span><input aria-label="From date" type="date" value={draft.from} max={draft.to || undefined} onChange={e => setDraft({ ...draft, from: e.target.value })} /></label><label><span>To</span><input aria-label="To date" type="date" value={draft.to} min={draft.from || undefined} onChange={e => setDraft({ ...draft, to: e.target.value })} /></label></div>}
      {invalid && <p className="error-copy" role="alert">The end date must follow the start date.</p>}
      <p className="field-note">Photos are dated when they were taken. Images without that record use the date the file was last changed.</p>
    </fieldset>
    {error && <p className="error-copy" role="alert">{error}</p>}
    <div className="panel-footer"><button className="text-button secondary" onClick={() => setDraft(defaults)}>Reset</button><button className="text-button primary" disabled={invalid} onClick={() => { onApply(draft); onClose(); }}>Apply</button></div>
  </Panel>;
}

/** `narrowed` says the grid is filtered or searched, so it shows less than the library; `shown` is how many, when known.
 *  `scanLeft` and `searchLeft` estimate the time left for reading and for visual search. */
export function LibraryPanel({ status, shown, narrowed, scanLeft, searchLeft, anchor, onClose, onRefresh, onSetUp }: { status: Status; shown: number | null; narrowed: boolean; scanLeft: string; searchLeft: string; anchor: HTMLElement | null; onClose: () => void; onRefresh: () => void; onSetUp: () => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const action = async (url: string) => { setBusy(true); setError(''); try { await post(url); onRefresh(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const library = status.library!;
  const { counts, scan, search } = library;
  const scanning = scan.state === 'scanning';
  const complete = search.state === 'ready';
  const work = searchWork(search);
  const scanLabel = scan.changed ? `Reading ${(scan.done ?? 0).toLocaleString()} of ${scan.changed.toLocaleString()}${scanLeft ? `. ${scanLeft}` : ''}` : 'Looking for images…';
  // Each row is taken from the one above, so the last is exactly the number of images the unfiltered grid shows.
  const ledger = [
    { label: 'Image files', value: counts.files + counts.unreadable, shown: true },
    { label: 'Could not be read', value: -counts.unreadable, shown: !!counts.unreadable },
    { label: 'Identical copies, shown once', value: -counts.duplicates, shown: !!counts.duplicates },
    { label: 'Near-duplicates, stacked', value: -counts.nearDuplicates, shown: !!counts.nearDuplicates },
  ].filter(row => row.shown);
  const totalLabel = ledger.length < 2 ? 'Images' : narrowed ? 'In the library' : 'In the grid';
  return <Panel title="Info" anchor={anchor} onClose={onClose}>
    <p className="path">{status.folder!.label}</p>
    <p>Subfolders included, hidden ones skipped. Your files are never changed.</p>
    <dl className="counts">
      {ledger.length > 1 && ledger.map(row => <Fragment key={row.label}><dt>{row.label}</dt><dd>{row.value < 0 ? `− ${(-row.value).toLocaleString()}` : row.value.toLocaleString()}</dd></Fragment>)}
      <dt className={ledger.length > 1 ? 'total' : undefined}>{totalLabel}</dt><dd className={ledger.length > 1 ? 'total' : undefined}>{(counts.images - counts.nearDuplicates).toLocaleString()}</dd>
    </dl>
    {shown !== null && <p>{plural(shown, 'image')} shown with your filters.</p>}
    {!!library.photoLibraries.length && <p>{library.photoLibraries.length === 1 ? 'The Photos library here is' : 'The Photos libraries here are'} skipped, since macOS keeps {library.photoLibraries.length === 1 ? 'it' : 'them'} closed to other apps. Export photos to a folder to include them.</p>}
    {!!library.unlistedFolders && <p>{plural(library.unlistedFolders, 'folder')} could not be opened. Check their permissions.</p>}
    {scanning && <Progress value={scan.changed ? (scan.done ?? 0) / scan.changed : null} label="Reading images" />}
    <div className="panel-action"><p>{scanning ? scanLabel : 'Checks every minute.'}</p><button className="text-button secondary" disabled={busy || scanning} onClick={() => action('/api/scan')}>Rescan now</button></div>
    {scan.error && <p className="error-copy">{scan.error}</p>}
    <hr className="rule" /><h3>Visual search</h3>
    {work && !work.error ? <>
      <p>{work.label}{work.detail && <span className="numbers"> · {work.detail}</span>}</p>
      <Progress value={work.value} label={work.label} />
      {search.state === 'downloading' && <p>{searchLeft ? `${searchLeft}.` : 'This happens once.'} You can keep browsing meanwhile.</p>}
      {search.state === 'indexing' && <p>{searchLeft ? `${searchLeft}. ` : ''}Prepared images can be searched already.</p>}
    </> : search.state === 'error' ? <>
      <p className="error-copy" role="alert">{search.error}</p>
      <button className="text-button secondary" onClick={onSetUp}>Try again</button>
    </> : complete ? <p>Every image can be found by a description or a similar image. Search runs on this computer.</p>
    : search.downloaded && scanning ? <p>{plural(Math.max(0, counts.images - search.indexed), 'image')} to prepare once reading finishes.</p>
    : search.downloaded ? <>
      <p>{plural(Math.max(0, counts.images - search.indexed), 'image')} still to prepare. New images are prepared automatically.</p>
      <button className="text-button primary" onClick={onSetUp}>Finish preparing</button>
    </> : status.model.update ? <>
      <p>{UPDATE_REASON} It downloads once (about {megabytes(status.model.size)} MB), then prepares this folder’s images again. Until then, the search bar searches file names.</p>
      <button className="text-button primary" onClick={onSetUp}>{setUpLabel(status.model)}</button>
    </> : <>
      <p>Find images by describing them or by showing a similar one, and see the folder laid out by look. The search model downloads once (about {megabytes(status.model.size)} MB), then runs on this computer.</p>
      <button className="text-button primary" onClick={onSetUp}>{setUpLabel(status.model)}</button>
    </>}
    {search.error && search.state !== 'error' && <p className="error-copy">{search.error}</p>}
    {error && <p className="error-copy" role="alert">{error}</p>}
  </Panel>;
}

/** Open a folder: the system dialog where there is one, a typed path, or a recent folder. `offerSetup` adds the choice
 *  to set up visual search along with whichever folder is opened, for a first visit. */
export function FolderChooser({ status, offerSetup, onOpened, onSetUp }: { status: Status; offerSetup?: boolean; onOpened: (status: Status) => void; onSetUp?: () => void }) {
  const [path, setPath] = useState('');
  const [setup, setSetup] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const open = async (kind: string, run: () => Promise<Status & { cancelled?: boolean }>) => {
    setBusy(kind); setError('');
    try { const next = await run(); if (!next.cancelled) { onOpened(next); if (offerSetup && setup) onSetUp?.(); } } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };
  const forget = async (folder: string) => { try { onOpened(await post<Status>('/api/folder/forget', { path: folder })); } catch (e) { setError((e as Error).message); } };
  return <div className="chooser">
    {status.picker && <button className="text-button primary" disabled={!!busy} onClick={() => open('dialog', () => post('/api/folder/choose'))}><FolderOpen />{busy === 'dialog' ? 'Waiting for the folder dialog…' : 'Choose folder…'}</button>}
    <form className="path-form" onSubmit={e => { e.preventDefault(); void open('path', () => post('/api/folder', { path })); }}>
      <label htmlFor="folder-path">{status.picker ? 'Or type its path' : 'Folder path'}</label>
      <div className="path-row"><input id="folder-path" value={path} placeholder="~/Pictures" spellCheck={false} autoCapitalize="off" autoComplete="off" onChange={e => setPath(e.target.value)} /><button className="text-button secondary" type="submit" disabled={!!busy || !path.trim()}>{busy === 'path' ? 'Opening…' : 'Open'}</button></div>
    </form>
    {error && <p className="error-copy" role="alert">{error}</p>}
    {!!status.recent.length && <div className="recent"><h3>Recent</h3><ul>{status.recent.map(folder => <li key={folder.path}>
      <button className="recent-open" disabled={!!busy || !folder.available} title={folder.available ? folder.path : `${folder.path} is not available. Reconnect its drive to open it.`} onClick={() => open(folder.path, () => post('/api/folder', { path: folder.path }))}><span className="path">{folder.label}</span>{!folder.available && <span className="muted">Not available</span>}{busy === folder.path && <span className="muted">Opening…</span>}</button>
      <button className="icon-button" aria-label={`Forget ${folder.label}`} title="Remove from recent" onClick={() => forget(folder.path)}><X /></button>
    </li>)}</ul></div>}
    {offerSetup && <label className="check"><input type="checkbox" checked={setup} aria-describedby="setup-note" onChange={e => setSetup(e.target.checked)} /><span>{setUpLabel(status.model)} too<span className="muted" id="setup-note">Find images by describing them. Downloads a {megabytes(status.model.size)} MB model once, which runs on this computer.</span></span></label>}
  </div>;
}

export function FolderPanel({ status, anchor, onOpened, onClose }: { status: Status; anchor: HTMLElement | null; onOpened: (status: Status) => void; onClose: () => void }) {
  return <Panel title="Folder" anchor={anchor} onClose={onClose}>
    {status.folder && <p>Showing <span className="path">{status.folder.label}</span>. {APP_NAME} keeps a separate cache for each folder, so switching back is quick.</p>}
    <FolderChooser status={status} onOpened={next => { onOpened(next); if (next.folder?.id !== status.folder?.id) onClose(); }} />
  </Panel>;
}

/** How the search bar searches. It opens from the bar itself and is the one place the mode is chosen. Until visual
 *  search can answer, choosing Appearance sets it up. */
export function SearchMenu({ mode, search, model, anchor, onMode, onSetUp, onUpload, onClose }: { mode: SearchMode; search: SearchStatus | null; model: Model; anchor: HTMLElement | null; onMode: (mode: SearchMode) => void; onSetUp: () => void; onUpload: () => void; onClose: () => void }) {
  const ready = !!search && searchable(search);
  const busy = !!search && settingUp(search);
  const option = (value: SearchMode, label: string) => <button className="text-button menu-item" aria-pressed={mode === value} onClick={() => { onMode(value); onClose(); }}><Check />{label}</button>;
  return <Popover label="Search options" anchor={anchor} menu className="panel menu" onClose={onClose}>
    <div role="group" aria-labelledby="search-by">
      <div className="menu-label" id="search-by">Search by</div>
      {ready ? option('visual', 'Appearance') : <>
        <button className="text-button menu-item" aria-pressed={false} aria-describedby="appearance-note" disabled={busy} onClick={() => { onSetUp(); onClose(); }}><Check />Appearance</button>
        <div className="menu-note" id="appearance-note">{busy ? 'Getting ready. Progress shows under the search bar.' : search?.state === 'error' ? 'The last try failed. Choose it to try again.' : `${model.update ? 'Updates visual search to its new model' : 'Sets up visual search'}: a ${megabytes(model.size)} MB download, once.`}</div>
      </>}
      {option('name', 'File name')}
    </div>
    <hr className="menu-rule" />
    <button className="text-button menu-item" disabled={!ready} onClick={() => { onClose(); onUpload(); }}><ImageIcon />Find images like a file…</button>
    <div className="menu-note">{ready ? 'You can also drop or paste an image.' : `Works once visual search is ${model.update ? 'updated' : 'set up'}.`}</div>
  </Popover>;
}
