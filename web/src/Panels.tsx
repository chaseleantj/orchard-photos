import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ArrowUpRight, Check, ChevronDown, Copy, FolderOpen, Image as ImageIcon, Images, X } from 'lucide-react';
import type { Facets, Filters, LibraryStatus, Model, Range, SearchCondition, SearchMode, Status, Updates } from './types';
import { APP_NAME, RANGES, SET_UP, megabytes, post, request, typeLabel } from './types';
import { waitingOn } from './Activity';

// Room kept between a popover and the control above it, and between a popover and the window edge.
const OFFSET = 8;
const EDGE = 16;
// How long the version's menu says the diagnostics were copied.
const COPIED_FOR = 4000;

/** A popover opened from `anchor`: under it, or over it where there is more room above. It lines up with the anchor's
 *  right edge (`end`), its left edge (`start`), or both (`stretch`, taking its width). `focus` is the element inside
 *  that takes focus as it opens; otherwise the popover takes it itself, so no control inside is marked until the
 *  keyboard moves there. */
function Popover({ label, anchor, align = 'end', focus, className, onClose, onKeyDown, children }: { label: string; anchor: HTMLElement | null; align?: 'start' | 'end' | 'stretch'; focus?: (popover: HTMLDialogElement) => HTMLElement | null; className: string; onClose: () => void; onKeyDown?: (e: React.KeyboardEvent<HTMLDialogElement>) => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    const node = ref.current!;
    node.showModal();
    (focus?.(node) ?? node).focus();
    const place = () => {
      if (!anchor?.isConnected) return;
      const r = anchor.getBoundingClientRect();
      if (align === 'stretch') node.style.width = `${r.width}px`;
      const width = node.offsetWidth;
      const left = Math.max(EDGE, Math.min(innerWidth - width - EDGE, align === 'end' ? r.right - width : r.left));
      const below = innerHeight - r.bottom - OFFSET - EDGE, above = r.top - OFFSET - EDGE;
      const up = node.scrollHeight > below && above > below;
      node.toggleAttribute('data-up', up);
      Object.assign(node.style, { top: `${up ? r.top - OFFSET - Math.min(node.scrollHeight, above) : r.bottom + OFFSET}px`, left: `${left}px`, right: 'auto', maxHeight: `${up ? above : below}px` });
    };
    place();
    addEventListener('resize', place);
    return () => { removeEventListener('resize', place); node.close(); };
  // `focus` is a new function each render and is only read as the popover opens, so it does not reopen it.
  }, [anchor, align]); // eslint-disable-line react-hooks/exhaustive-deps
  return <dialog ref={ref} tabIndex={-1} className={className} aria-label={label} onKeyDown={onKeyDown} onCancel={e => { e.stopPropagation(); onClose(); }} onClick={e => { if (e.target !== e.currentTarget) return; const r = ref.current!.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) onClose(); }}>{children}</dialog>;
}

function Panel({ title, anchor, onClose, children }: { title: string; anchor: HTMLElement | null; onClose: () => void; children: React.ReactNode }) {
  // The header gains an edge once the body has scrolled under it.
  const [scrolled, setScrolled] = useState(false);
  return <Popover label={title} anchor={anchor} className="panel" onClose={onClose}>
    <header className={scrolled ? 'scrolled' : undefined}><h2>{title}</h2><button className="icon-button" aria-label={`Close ${title.toLowerCase()}`} onClick={onClose}><X /></button></header>
    <div className="panel-body" onScroll={e => setScrolled(e.currentTarget.scrollTop > 0)}>{children}</div>
  </Popover>;
}

interface Choice { value: string; label: string; note?: string }

/** A field that opens a menu of choices under it, in the same menu the search bar opens, with a tick on the one chosen.
 *  The arrow keys move between choices and Escape closes it without choosing. */
function Dropdown({ label, value, choices, placeholder, onChange }: { label: string; value: string; choices: Choice[]; placeholder?: string; onChange: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const chosen = choices.find(c => c.value === value);
  const close = () => { setOpen(false); button.current?.focus(); };
  const move = (e: React.KeyboardEvent<HTMLDialogElement>) => {
    const all = [...e.currentTarget.querySelectorAll<HTMLElement>('.menu-item')], at = all.indexOf(document.activeElement as HTMLElement);
    const to = { ArrowDown: at + 1, ArrowUp: at < 0 ? all.length - 1 : at - 1, Home: 0, End: all.length - 1 }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    all[Math.max(0, Math.min(all.length - 1, to))]?.focus();
  };
  return <>
    <button ref={button} type="button" className="dropdown" aria-label={`${label}, ${chosen?.label ?? placeholder ?? ''}`} aria-haspopup="dialog" aria-expanded={open} disabled={!choices.length} onClick={() => setOpen(true)}
      onKeyDown={e => { if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); setOpen(true); } }}>
      <span className="dropdown-value">{chosen?.label ?? placeholder}</span>{chosen?.note && <span className="muted">{chosen.note}</span>}<ChevronDown />
    </button>
    {open && <Popover label={label} anchor={button.current} align="stretch" className="panel menu dropdown-menu" onClose={close} onKeyDown={move}
      focus={popover => popover.querySelector<HTMLElement>('[aria-pressed="true"]') ?? popover.querySelector<HTMLElement>('.menu-item')}>
      <div role="group" aria-label={label}>
        {choices.map(c => <button key={c.value} type="button" className="text-button menu-item" aria-pressed={c.value === value} onClick={() => { onChange(c.value); close(); }}>
          <Check /><span className="dropdown-value">{c.label}</span>{c.note && <span className="muted">{c.note}</span>}
        </button>)}
      </div>
    </Popover>}
  </>;
}

/** The file type and date filters, which take effect as they are chosen. A custom range takes effect once its dates
 *  are in order. */
export function FilterPanel({ filters, anchor, onApply, onClose }: { filters: Filters; anchor: HTMLElement | null; onApply: (filters: Filters) => void; onClose: () => void }) {
  const [draft, setDraft] = useState(filters);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { request<Facets>('/api/facets').then(setFacets, e => setError((e as Error).message)); }, []);
  // A date field passes through years like 0002 and 0020 while one is typed, so a date takes effect once its year is
  // whole, and the range is judged only then.
  const whole = (date: string) => !date || date >= '1000';
  const inOrder = (f: Filters) => !f.from || !f.to || f.from <= f.to;
  const ready = (f: Filters) => f.range !== 'custom' || (whole(f.from) && whole(f.to) && inOrder(f));
  const invalid = draft.range === 'custom' && whole(draft.from) && whole(draft.to) && !inOrder(draft);
  const change = (next: Partial<Filters>) => {
    const filters = { ...draft, ...next };
    if (Object.entries(next).every(([key, value]) => draft[key as keyof Filters] === value)) return;
    setDraft(filters);
    if (ready(filters)) onApply(filters);
  };
  const types = facets?.types ?? [];
  const typeChoices: Choice[] = facets ? [
    { value: '', label: 'All types' },
    ...(draft.type && !types.some(t => t.type === draft.type) ? [{ value: draft.type, label: typeLabel(draft.type), note: 'No images' }] : []),
    ...types.map(t => ({ value: t.type, label: typeLabel(t.type), note: t.count.toLocaleString() })),
  ] : [];
  return <Panel title="Filters" anchor={anchor} onClose={onClose}>
    <fieldset className="field"><legend>File type</legend>
      <Dropdown label="File type" value={draft.type} choices={typeChoices} placeholder={error ? 'Types unavailable' : 'Loading types…'} onChange={type => change({ type })} />
    </fieldset>
    <fieldset className="field"><legend>Date</legend>
      <Dropdown label="Date" value={draft.range} choices={RANGES.map(({ range, label }) => ({ value: range, label }))} onChange={range => change({ range: range as Range })} />
      {draft.range === 'custom' && <div className="date-inputs"><label><span>From</span><input aria-label="From date" type="date" value={draft.from} max={draft.to || undefined} onChange={e => change({ from: e.target.value })} /></label><label><span>To</span><input aria-label="To date" type="date" value={draft.to} min={draft.from || undefined} onChange={e => change({ to: e.target.value })} /></label></div>}
      {invalid && <p className="error-copy" role="alert">The end date must follow the start date.</p>}
    </fieldset>
    {error && <p className="error-copy" role="alert">{error}</p>}
  </Panel>;
}

/** The version, at the foot of the sidebar, which opens the opt-in update check, the newer release it found, and the
 *  diagnostics a bug report asks for. */
export function AboutMenu({ version, library }: { version: string; library: LibraryStatus }) {
  const [open, setOpen] = useState(false);
  const [updates, setUpdates] = useState<Updates | null>(null);
  const [report, setReport] = useState('');
  const [copied, setCopied] = useState<'copied' | 'select' | null>(null);
  const [error, setError] = useState('');
  const button = useRef<HTMLButtonElement>(null);
  const reportArea = useRef<HTMLTextAreaElement>(null);
  // An update check that fails says nothing; the next day's check tries again.
  useEffect(() => { request<Updates>('/api/updates').then(setUpdates, () => {}); }, []);
  // Fetched ahead of the click, since a webview may only allow the copy while the click is being handled.
  const { scan, search, revision } = library;
  useEffect(() => { request<{ report: string }>('/api/diagnostics').then(data => setReport(data.report), () => {}); }, [scan.state, scan.error, search.state, search.error, revision]);
  useEffect(() => { if (copied !== 'copied') return; const timer = setTimeout(() => setCopied(null), COPIED_FOR); return () => clearTimeout(timer); }, [copied]);
  useEffect(() => { if (copied === 'select') reportArea.current?.select(); }, [copied]);
  const turn = async (enabled: boolean) => {
    setError(''); setUpdates(old => old && { ...old, enabled });
    try { setUpdates(await post<Updates>('/api/updates', { enabled })); } catch (e) { setUpdates(old => old && { ...old, enabled: !enabled }); setError((e as Error).message); }
  };
  const copy = async (target: HTMLElement) => setCopied(await copyText(report, target) ? 'copied' : 'select');
  const close = () => { setOpen(false); setCopied(null); setError(''); };
  return <>
    <button ref={button} className="text-button about" aria-haspopup="dialog" aria-expanded={open} title={updates?.update ? `Version ${updates.update.version} is available` : undefined} onClick={() => setOpen(true)}>{APP_NAME} {version}</button>
    {open && <Popover label={`${APP_NAME} ${version}`} anchor={button.current} align="start" className="panel menu about-menu" onClose={close}>
      {updates?.update && <a className="text-button menu-item" href={updates.update.url} target="_blank" rel="noreferrer"><ArrowUpRight />Get version {updates.update.version}</a>}
      <button className="text-button menu-item" aria-pressed={!!updates?.enabled} disabled={!updates} onClick={() => void turn(!updates?.enabled)}><Check />Check for updates</button>
      <button className="text-button menu-item" disabled={!report} onClick={e => void copy(e.currentTarget)}>{copied === 'copied' ? <><Check />Diagnostics copied</> : <><Copy />Copy diagnostics</>}</button>
      {copied === 'select' && <textarea ref={reportArea} className="report" readOnly rows={report.split('\n').length} value={report} aria-label="Diagnostics" />}
      {error && <p className="menu-note error-copy" role="alert">{error}</p>}
    </Popover>}
  </>;
}

/** Put text on the clipboard while a click on `button` is handled. Webviews without the async clipboard, or that refuse
 *  it, still run the copy command on a selected field. Returns whether either worked. */
async function copyText(text: string, button: HTMLElement) {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* Not offered, or refused. */ }
  // Inside the open panel, since a modal dialog makes the rest of the page inert.
  const field = document.createElement('textarea');
  Object.assign(field, { value: text, readOnly: true });
  Object.assign(field.style, { position: 'fixed', opacity: '0' });
  (button.closest('dialog') ?? document.body).append(field);
  field.select();
  let copied = false;
  try { copied = document.execCommand('copy'); } catch { /* Refused too. */ }
  field.remove();
  button.focus();
  return copied;
}

/** Open a folder: the system dialog, or a typed path where there is none, or a recent folder. `offerSetup` adds the choice
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
    {status.photos && !status.folder?.photos && <button className="text-button secondary" disabled={!!busy} onClick={() => open('photos', () => post('/api/folder', { path: status.photos }))}><Images />{busy === 'photos' ? 'Opening…' : 'Photos library'}</button>}
    {!status.picker && <form className="path-form" onSubmit={e => { e.preventDefault(); void open('path', () => post('/api/folder', { path })); }}>
      <label htmlFor="folder-path">Folder path</label>
      <div className="path-row"><input id="folder-path" value={path} placeholder="~/Pictures" spellCheck={false} autoCapitalize="off" autoComplete="off" onChange={e => setPath(e.target.value)} /><button className="text-button secondary" type="submit" disabled={!!busy || !path.trim()}>{busy === 'path' ? 'Opening…' : 'Open'}</button></div>
    </form>}
    {error && <p className="error-copy" role="alert">{error}</p>}
    {!!status.recent.length && <div className="recent"><h3>Recent</h3><ul>{status.recent.map(folder => <li key={folder.path}>
      <button className="recent-open" disabled={!!busy || !folder.available} title={folder.available ? folder.path : `${folder.path} is not available. Reconnect its drive to open it.`} onClick={() => open(folder.path, () => post('/api/folder', { path: folder.path }))}><span className="path">{folder.label}</span>{!folder.available && <span className="muted">Not available</span>}{busy === folder.path && <span className="muted">Opening…</span>}</button>
      <button className="icon-button" aria-label={`Forget ${folder.label}`} title="Remove from recent" onClick={() => forget(folder.path)}><X /></button>
    </li>)}</ul></div>}
    {offerSetup && <label className="check"><input type="checkbox" checked={setup} aria-describedby="setup-note" onChange={e => setSetup(e.target.checked)} /><span>{SET_UP} too<span className="muted" id="setup-note">Find images by describing them. Downloads a {megabytes(status.model.size)} MB model once, which runs on this computer.</span></span></label>}
  </div>;
}

export function FolderPanel({ status, anchor, onOpened, onClose }: { status: Status; anchor: HTMLElement | null; onOpened: (status: Status) => void; onClose: () => void }) {
  return <Panel title="Folder" anchor={anchor} onClose={onClose}>
    {status.folder && <p>Showing <span className="path">{status.folder.label}</span>.</p>}
    <FolderChooser status={status} onOpened={next => { onOpened(next); if (next.folder?.id !== status.folder?.id) onClose(); }} />
  </Panel>;
}

/** How the search bar searches. It opens from the bar itself and is the one place the mode is chosen. Until visual
 *  search is set up, choosing Appearance sets it up; while it is starting, Appearance says what it is waiting on. */
export function SearchMenu({ mode, condition, library, model, anchor, onMode, onSetUp, onUpload, onClose }: { mode: SearchMode; condition: SearchCondition | null; library: LibraryStatus | null; model: Model; anchor: HTMLElement | null; onMode: (mode: SearchMode) => void; onSetUp: () => void; onUpload: () => void; onClose: () => void }) {
  const ready = condition === 'on';
  const busy = condition === 'starting';
  const option = (value: SearchMode, label: string) => <button className="text-button menu-item" aria-pressed={mode === value} onClick={() => { onMode(value); onClose(); }}><Check />{label}</button>;
  return <Popover label="Search options" anchor={anchor} align="stretch" className="panel menu" onClose={onClose}>
    <div role="group" aria-labelledby="search-by">
      <div className="menu-label" id="search-by">Search by</div>
      {ready ? option('visual', 'Appearance') : <>
        <button className="text-button menu-item" aria-pressed={false} aria-describedby="appearance-note" disabled={busy} onClick={() => { onSetUp(); onClose(); }}><Check />Appearance</button>
        <div className="menu-note" id="appearance-note">{busy ? waitingOn(library!) : condition === 'failed' ? 'The last try failed. Choose it to try again.' : `Sets up visual search: a ${megabytes(model.size)} MB download, once.`}</div>
      </>}
      {option('name', 'File name')}
    </div>
    <hr className="menu-rule" />
    <button className="text-button menu-item" disabled={!ready} onClick={() => { onClose(); onUpload(); }}><ImageIcon />Find images like a file…</button>
    <div className="menu-note">{ready ? 'You can also drop or paste an image.' : busy ? 'Works once visual search is ready.' : 'Works once visual search is set up.'}</div>
  </Popover>;
}
