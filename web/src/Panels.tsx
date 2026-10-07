import { useEffect, useRef, useState } from 'react';
import { ChevronDown, FolderOpen, X } from 'lucide-react';
import type { Facets, Filters, Range, SearchMode, Status } from './types';
import { APP_NAME, RANGES, defaults, plural, post, request, typeLabel } from './types';
import { Progress } from './Progress';

export function Panel({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const node = ref.current!; node.showModal(); return () => node.close(); }, []);
  return <dialog ref={ref} className="panel" aria-label={title} onCancel={onClose} onClick={e => { if (e.target !== e.currentTarget) return; const r = ref.current!.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) onClose(); }}><header><h2>{title}</h2><button className="icon-button" aria-label={`Close ${title.toLowerCase()}`} onClick={onClose}><X /></button></header>{children}</dialog>;
}

function Select({ label, value, onChange, disabled, children }: { label: string; value: string; onChange: (value: string) => void; disabled?: boolean; children: React.ReactNode }) {
  return <div className="select"><select aria-label={label} value={value} disabled={disabled} onChange={e => onChange(e.target.value)}>{children}</select><ChevronDown /></div>;
}

export function FilterPanel({ filters, onApply, onClose }: { filters: Filters; onApply: (filters: Filters) => void; onClose: () => void }) {
  const [draft, setDraft] = useState(filters);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { request<Facets>('/api/facets').then(setFacets, e => setError((e as Error).message)); }, []);
  const invalid = draft.range === 'custom' && !!draft.from && !!draft.to && draft.from > draft.to;
  const folders = facets?.folders ?? [];
  const types = facets?.types ?? [];
  const loading = !facets && !error;
  return <Panel title="Filters" onClose={onClose}>
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
    <div className="panel-footer"><button className="text-button" onClick={() => setDraft(defaults)}>Reset</button><button className="text-button solid" disabled={invalid} onClick={() => { onApply(draft); onClose(); }}>Apply</button></div>
  </Panel>;
}

export function LibraryPanel({ status, onClose, onRefresh }: { status: Status; onClose: () => void; onRefresh: () => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const action = async (url: string) => { setBusy(true); setError(''); try { await post(url); onRefresh(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const library = status.library!;
  const { counts, scan, search } = library;
  const scanning = scan.state === 'scanning';
  const indexing = search.state === 'loading' || search.state === 'indexing';
  const scanLabel = scan.changed ? `Reading images · ${(scan.done ?? 0).toLocaleString()} / ${scan.changed.toLocaleString()}` : 'Looking for images…';
  return <Panel title="Library" onClose={onClose}>
    <p>Every image in <span className="path">{status.folder!.label}</span> and its subfolders. Hidden folders are skipped, and your files are never changed.</p>
    <dl className="counts">
      <dt>Images</dt><dd>{counts.images.toLocaleString()}</dd>
      {!!counts.duplicates && <><dt>Duplicate files</dt><dd>{counts.duplicates.toLocaleString()}</dd></>}
      {!!counts.nearDuplicates && <><dt>Near-duplicates</dt><dd>{counts.nearDuplicates.toLocaleString()}</dd></>}
      {!!counts.unreadable && <><dt>Unreadable files</dt><dd>{counts.unreadable.toLocaleString()}</dd></>}
    </dl>
    {!!counts.duplicates && <p>Identical files appear once. Opening an image lists every place it is saved.</p>}
    {!!counts.nearDuplicates && <p>Images that look almost the same, like bursts and resized copies, share one tile showing the sharpest. Opening it shows the rest.</p>}
    {!!library.unreadable.length && <details className="disclosure"><summary>Files that could not be read</summary><ul className="file-list">{library.unreadable.map(file => <li key={file.path}><span className="path">{file.path}</span><span>{file.error}</span></li>)}</ul>{counts.unreadable > library.unreadable.length && <p>And {plural(counts.unreadable - library.unreadable.length, 'more file')}.</p>}</details>}
    {!!library.unlistedFolders && <p>{plural(library.unlistedFolders, 'folder')} could not be opened. Check their permissions.</p>}
    {scanning && <Progress value={scan.changed ? (scan.done ?? 0) / scan.changed : null} label="Reading images" />}
    <button className="text-button" disabled={busy || scanning} onClick={() => action('/api/scan')}>{scanning ? scanLabel : 'Rescan folder'}</button>
    {scan.error && <p className="error-copy">{scan.error}</p>}
    <hr className="rule" /><h2>Visual search</h2>
    <p>Find images by what they look like, from a description or another image. Search runs on this computer.</p>
    <p>{search.state === 'ready' ? `${plural(search.indexed, 'image')} searchable` : indexing ? `${search.state === 'loading' ? 'Loading search model' : 'Preparing images'} · ${search.indexed.toLocaleString()} / ${search.total.toLocaleString()}` : search.downloaded ? 'The search model is on this computer. New images are prepared automatically.' : 'Download the search model once (about 600 MB), then search offline.'}</p>
    {indexing && !!search.total && <Progress value={search.indexed / search.total} label="Preparing images" />}
    <button className="text-button" disabled={busy || indexing || !counts.images} title={!counts.images ? 'Add images to the folder first' : undefined} onClick={() => action('/api/search/index')}>{search.state === 'ready' ? 'Update visual index' : search.indexed ? 'Finish preparing' : 'Prepare visual search'}</button>
    {search.error && <p className="error-copy">{search.error}</p>}
    {error && <p className="error-copy" role="alert">{error}</p>}
  </Panel>;
}

/** Open a folder: the system dialog where there is one, a typed path, or a recent folder. */
export function FolderChooser({ status, onOpened }: { status: Status; onOpened: (status: Status) => void }) {
  const [path, setPath] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const open = async (kind: string, run: () => Promise<Status & { cancelled?: boolean }>) => {
    setBusy(kind); setError('');
    try { const next = await run(); if (!next.cancelled) onOpened(next); } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };
  const forget = async (folder: string) => { try { onOpened(await post<Status>('/api/folder/forget', { path: folder })); } catch (e) { setError((e as Error).message); } };
  return <div className="chooser">
    {status.platform === 'darwin' && <button className="text-button solid" disabled={!!busy} onClick={() => open('dialog', () => post('/api/folder/choose'))}><FolderOpen />{busy === 'dialog' ? 'Waiting for the folder dialog…' : 'Choose folder…'}</button>}
    <form className="path-form" onSubmit={e => { e.preventDefault(); void open('path', () => post('/api/folder', { path })); }}>
      <label htmlFor="folder-path">{status.platform === 'darwin' ? 'Or type its path' : 'Folder path'}</label>
      <div className="path-row"><input id="folder-path" value={path} placeholder="~/Pictures" spellCheck={false} autoCapitalize="off" autoComplete="off" onChange={e => setPath(e.target.value)} /><button className="text-button" type="submit" disabled={!!busy || !path.trim()}>{busy === 'path' ? 'Opening…' : 'Open'}</button></div>
    </form>
    {error && <p className="error-copy" role="alert">{error}</p>}
    {!!status.recent.length && <div className="recent"><h3>Recent</h3><ul>{status.recent.map(folder => <li key={folder.path}>
      <button className="recent-open" disabled={!!busy || !folder.available} title={folder.available ? folder.path : `${folder.path} is not available. Reconnect its drive to open it.`} onClick={() => open(folder.path, () => post('/api/folder', { path: folder.path }))}><span className="path">{folder.label}</span>{!folder.available && <span className="muted">Not available</span>}{busy === folder.path && <span className="muted">Opening…</span>}</button>
      <button className="icon-button" aria-label={`Forget ${folder.label}`} title="Remove from recent" onClick={() => forget(folder.path)}><X /></button>
    </li>)}</ul></div>}
  </div>;
}

export function FolderPanel({ status, onOpened, onClose }: { status: Status; onOpened: (status: Status) => void; onClose: () => void }) {
  return <Panel title="Folder" onClose={onClose}>
    {status.folder && <p>Showing <span className="path">{status.folder.label}</span>. {APP_NAME} keeps a separate cache for each folder, so switching back is quick.</p>}
    <FolderChooser status={status} onOpened={next => { onOpened(next); if (next.folder?.id !== status.folder?.id) onClose(); }} />
  </Panel>;
}

export function SearchPanel({ mode, onMode, onUpload, onClose }: { mode: SearchMode; onMode: (mode: SearchMode) => void; onUpload: () => void; onClose: () => void }) {
  return <Panel title="Search" onClose={onClose}><div className="field"><div className="mode-options"><button className="text-button" aria-pressed={mode === 'visual'} onClick={() => { onMode('visual'); onClose(); }}>By appearance</button><button className="text-button" aria-pressed={mode === 'name'} onClick={() => { onMode('name'); onClose(); }}>By file name</button></div></div><button className="text-button" onClick={onUpload}>Choose an image to match</button><p>You can also drop or paste an image.</p></Panel>;
}
