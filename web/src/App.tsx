import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Search, SlidersHorizontal, Moon, Sun, Info, ScanSearch, X, LayoutGrid, ChartScatter, FolderOpen, Image as ImageIcon } from 'lucide-react';
import Gallery from './Gallery';
import Embedding from './Embedding';
import Viewer from './Viewer';
import { Progress } from './Progress';
import { FilterPanel, FolderChooser, FolderPanel, LibraryPanel, SearchPanel } from './Panels';
import { APP_NAME, IMAGE_DRAG, defaults, filterParams, imageUrl, isFiltered, plural, rangeLabel, readPreferences, request, savePreferences, typeLabel } from './types';
import type { Picture, Results, SearchMode, Status, View } from './types';
const initial = readPreferences();
const IMAGE_ID = /^[a-f0-9]{64}$/;
const droppable = (e: React.DragEvent) => e.dataTransfer.types.includes('Files') || e.dataTransfer.types.includes(IMAGE_DRAG);
type PanelName = 'filters' | 'library' | 'folder' | 'search';
export default function App() {
  const [filters, setFilters] = useState(initial.filters);
  const [theme, setTheme] = useState(initial.theme);
  const [view, setView] = useState<View>(initial.view);
  // The folder the filters and grid belong to; a different folder resets what only made sense in the old one.
  const [root, setRoot] = useState(initial.root);
  const [picked, setPicked] = useState<Picture | null>(null);
  const [query, setQuery] = useState(new URLSearchParams(location.search).get('q') || '');
  const [submitted, setSubmitted] = useState(query);
  const [mode, setMode] = useState<SearchMode>('visual');
  const [similar, setSimilar] = useState('');
  const [upload, setUpload] = useState<File | null>(null);
  const [items, setItems] = useState<Picture[]>([]);
  const [total, setTotal] = useState(0);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState<Status | null>(null);
  const [offline, setOffline] = useState(false);
  const [panel, setPanel] = useState<PanelName | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [revision, setRevision] = useState(0);
  const [live, setLive] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [overSearch, setOverSearch] = useState(false);
  const mapped = view === 'map';
  const folder = status?.folder ?? null;
  const library = status?.library ?? null;
  const ready = !!folder && folder.id === root;
  const searchRef = useRef<HTMLInputElement>(null);
  const uploadRef = useRef<HTMLInputElement>(null);
  const requestId = useRef(0);
  const sentinel = useRef<HTMLDivElement>(null);
  const paging = useRef(false);
  const dragDepth = useRef(0);
  const previousRevision = useRef<string>('');
  const viewerOpen = useRef(false);
  const refreshPending = useRef(false);
  viewerOpen.current = selected !== null || picked !== null;
  useEffect(() => { if (selected === null && picked === null && refreshPending.current) { refreshPending.current = false; setLive(n => n + 1); } }, [selected, picked]);
  useEffect(() => { document.documentElement.dataset.theme = theme; savePreferences({ theme, filters, view, root }); }, [theme, filters, view, root]);

  const clearSearch = useCallback(() => { setQuery(''); setSubmitted(''); setSimilar(''); setUpload(null); history.replaceState(null, '', location.pathname); }, []);
  const applyStatus = useCallback((data: Status) => {
    setStatus(data); setOffline(false);
    // A scan that committed changes refreshes the grid in place, or once the viewer closes.
    const mark = data.folder && data.library ? `${data.folder.id}:${data.library.revision}` : '';
    if (previousRevision.current && mark && previousRevision.current !== mark && previousRevision.current.split(':')[0] === data.folder!.id) {
      if (viewerOpen.current) refreshPending.current = true; else setLive(n => n + 1);
    }
    previousRevision.current = mark;
  }, []);
  const refreshStatus = useCallback(async () => {
    try { applyStatus(await request<Status>('/api/status')); } catch { setOffline(true); }
  }, [applyStatus]);
  useEffect(() => { void refreshStatus(); const timer = setInterval(refreshStatus, 4000); return () => clearInterval(timer); }, [refreshStatus]);
  // Another folder was opened, here or from the command line: its subfolders and searches start fresh.
  useEffect(() => {
    if (!status) return;
    const id = status.folder?.id ?? '';
    if (id === root) return;
    if (root) { setFilters(f => ({ ...f, folder: '' })); clearSearch(); setSelected(null); setPicked(null); window.scrollTo({ top: 0 }); }
    setRoot(id);
  }, [status, root, clearSearch]);

  const fetchResults = useCallback(async (offset: number, signal?: AbortSignal, limit = 80) => {
    const params = new URLSearchParams({ ...filterParams(filters), q: submitted, mode, similar, offset: String(offset), limit: String(limit) });
    if (upload) return request<Results>(`/api/search/image?${params}`, { method: 'POST', body: upload, headers: { 'Content-Type': upload.type || 'application/octet-stream' }, signal });
    return request<Results>(`/api/images?${params}`, { signal });
  }, [filters, submitted, mode, similar, upload]);
  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    const id = ++requestId.current;
    paging.current = false; setLoading(true); setLoadingMore(false); setError(''); setSelected(null);
    fetchResults(0, controller.signal).then(data => { if (id !== requestId.current) return; setItems(data.items); setTotal(data.total); setMore(data.hasMore); }).catch(e => { if (e.name !== 'AbortError' && id === requestId.current) { setError(e.message); setItems([]); } }).finally(() => { if (id === requestId.current) setLoading(false); });
    return () => controller.abort();
  }, [fetchResults, revision, ready, root]);
  const loadMore = async () => {
    if (paging.current) return false;
    paging.current = true; const id = requestId.current; setLoadingMore(true); setError('');
    try { const data = await fetchResults(items.length); if (id === requestId.current) { setItems(old => { const seen = new Set(old.map(item => item.id)); return [...old, ...data.items.filter(item => !seen.has(item.id))]; }); setMore(data.hasMore); return true; } } catch (e) { if (id === requestId.current) setError((e as Error).message); } finally { if (id === requestId.current) { paging.current = false; setLoadingMore(false); } }
    return false;
  };
  // Infinite scroll: the next page loads before the end of the grid comes into view.
  const loadMoreRef = useRef(loadMore);
  loadMoreRef.current = loadMore;
  useEffect(() => {
    if (!more || loading || error || mapped || !sentinel.current) return;
    const observer = new IntersectionObserver(entries => { if (entries[0].isIntersecting) void loadMoreRef.current(); }, { rootMargin: '0px 0px 1500px 0px' });
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [more, loading, error, mapped, items.length]);
  // A finished scan refreshes what is loaded in place: no loading state, no jump, viewer untouched.
  const liveRef = useRef({ fetchResults, count: 0 });
  liveRef.current = { fetchResults, count: items.length };
  useEffect(() => {
    if (!live) return;
    const controller = new AbortController(); const id = requestId.current; const { fetchResults: fetchFresh, count } = liveRef.current;
    fetchFresh(0, controller.signal, Math.min(200, Math.max(80, count))).then(data => {
      if (id !== requestId.current) return;
      setItems(old => { const fresh = new Set(data.items.map(item => item.id)); const merged = [...data.items, ...old.slice(data.items.length).filter(item => !fresh.has(item.id))]; setMore(data.total > merged.length); return merged; });
      setTotal(data.total);
    }).catch(() => { /* The next scan retries; the loaded grid stays as it was. */ });
    return () => controller.abort();
  }, [live]);
  const changeSelected = async (index: number) => { if (index < items.length) setSelected(index); else if (await loadMore()) setSelected(index); };
  const reset = () => { clearSearch(); setFilters(defaults); window.scrollTo({ top: 0 }); };
  useEffect(() => { window.scrollTo({ top: 0 }); }, [filters, submitted, mode, similar, upload]);
  // Image searches are answered by a ranked grid, wherever they start.
  const findSimilar = useCallback((id: string) => { clearSearch(); setPicked(null); setSelected(null); setView('grid'); setSimilar(id); setMode('visual'); }, [clearSearch]);
  const useImage = useCallback((file: File) => {
    if (!file.type.startsWith('image/') && !/\.(heic|heif)$/i.test(file.name)) { setError('Choose an image file to search.'); return; }
    if (file.size > 20 * 1024 * 1024) { setError('Choose an image smaller than 20 MB.'); return; }
    clearSearch(); setPanel(null); setUpload(file); setMode('visual'); setSelected(null); setPicked(null); setView('grid');
  }, [clearSearch]);
  const showFolder = (path: string) => { setSelected(null); setPicked(null); clearSearch(); setView('grid'); setFilters(f => ({ ...f, folder: path })); };
  useEffect(() => {
    const paste = (e: ClipboardEvent) => { const file = Array.from(e.clipboardData?.files || []).find(f => f.type.startsWith('image/')); if (file && ready) { e.preventDefault(); useImage(file); } };
    const keyboard = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); if (selected === null && !picked && !panel) searchRef.current?.focus(); } };
    window.addEventListener('paste', paste); window.addEventListener('keydown', keyboard);
    return () => { window.removeEventListener('paste', paste); window.removeEventListener('keydown', keyboard); };
  }, [useImage, panel, selected, picked, ready]);
  const filtered = isFiltered(filters);
  const searching = !!submitted || !!similar || !!upload;
  const [uploadUrl, setUploadUrl] = useState('');
  useEffect(() => { if (!upload) { setUploadUrl(''); return; } const url = URL.createObjectURL(upload); setUploadUrl(url); return () => URL.revokeObjectURL(url); }, [upload]);
  const reference = similar ? imageUrl(similar) : uploadUrl;
  // A dropped HEIC can be searched but not drawn by most browsers; it then shows as a generic image.
  const [referenceFailed, setReferenceFailed] = useState(false);
  useEffect(() => setReferenceFailed(false), [reference]);
  const scan = library?.scan;
  const scanBusy = scan?.state === 'scanning';
  // While new results load, the map keeps lighting the previous matches instead of flashing back to everything.
  const lastHighlight = useRef<string[] | null>(null);
  const highlight = useMemo(() => { if (!searching) lastHighlight.current = null; else if (!loading) lastHighlight.current = items.map(item => item.id); return lastHighlight.current; }, [searching, loading, items]);
  const subtitle = (similar || upload) && !mapped ? `${total.toLocaleString()} most similar ${total === 1 ? 'image' : 'images'}` : mapped && searching ? `Closest ${plural(items.length, 'match', 'matches')}` : searching ? (mode === 'visual' ? `${plural(total, 'image')} by similarity` : plural(total, 'match', 'matches')) : plural(total, 'image');
  const scope = [filters.folder && `in ${filters.folder}`, filters.type && typeLabel(filters.type), rangeLabel(filters), scanBusy && 'Updating'].filter(Boolean).map(part => ` · ${part}`).join('');
  const gathering = scanBusy && !library?.counts.images;
  return <div className={mapped && ready ? 'app map-view' : 'app'} onDragEnter={e => { if (ready && droppable(e)) { e.preventDefault(); dragDepth.current++; setDragging(true); } }} onDragOver={e => { if (!ready || !droppable(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; setOverSearch(!!(e.target as Element).closest?.('.search')); }} onDragLeave={() => { dragDepth.current--; if (dragDepth.current <= 0) { setDragging(false); setOverSearch(false); } }} onDrop={e => { if (!ready) return; e.preventDefault(); dragDepth.current = 0; setDragging(false); setOverSearch(false); const id = e.dataTransfer.getData(IMAGE_DRAG); const file = e.dataTransfer.files[0]; if (IMAGE_ID.test(id)) findSimilar(id); else if (file) useImage(file); }}>
    <header className="header">
      <button className="wordmark" onClick={reset} aria-label={`${APP_NAME}, show every image`}>{APP_NAME}</button>
      {ready && <form className="search" data-drop={overSearch ? 'over' : dragging ? 'ready' : undefined} role="search" onSubmit={e => { e.preventDefault(); setSimilar(''); setUpload(null); setSubmitted(query.trim()); history.replaceState(null, '', query.trim() ? `?q=${encodeURIComponent(query.trim())}` : location.pathname); }}>
        {reference && !referenceFailed ? <img className="search-reference" src={reference} alt="Image you are matching" onError={() => setReferenceFailed(true)} /> : reference ? <ImageIcon aria-label="Image you are matching" /> : <Search />}<label className="sr-only" htmlFor="search">Search images</label><input ref={searchRef} id="search" value={query} placeholder={dragging ? 'Drop an image to find similar' : similar || upload ? 'Similar images' : mode === 'visual' ? 'Search by appearance' : 'Search file names'} onChange={e => setQuery(e.target.value)} />
        {(query || searching) && <button className="icon-button" type="button" aria-label="Clear search" onClick={clearSearch}><X /></button>}
        <button className="icon-button" type="button" aria-label="Search options" title="Search options" aria-expanded={panel === 'search'} onClick={() => setPanel('search')}><ScanSearch /></button>
      </form>}
      <div className="header-actions">{ready && <><div className="view-switch" role="group" aria-label="View"><button className="text-button" aria-pressed={!mapped} aria-label="Grid" title="Grid" onClick={() => setView('grid')}><LayoutGrid /><span>Grid</span></button><button className="text-button" aria-pressed={mapped} aria-label="Map" title="Map by appearance" onClick={() => setView('map')}><ChartScatter /><span>Map</span></button></div><button className="text-button" aria-label="Filters" aria-expanded={panel === 'filters'} onClick={() => setPanel('filters')}><SlidersHorizontal /><span>{filtered ? 'Filtered' : 'Filter'}</span></button></>}<button className="icon-button" aria-label={theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'} title={theme === 'light' ? 'Dark mode' : 'Light mode'} onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>{theme === 'light' ? <Moon /> : <Sun />}</button>{ready && <button className="icon-button" aria-label="Library information" title="Library" aria-expanded={panel === 'library'} onClick={() => setPanel('library')}><Info /></button>}</div>
    </header>
    {ready && <div className="library-meta"><p aria-live="polite">{loading ? 'Finding images…' : subtitle}{scope}</p><button className="text-button folder-button" title={`${folder!.path}. Choose another folder`} aria-expanded={panel === 'folder'} onClick={() => setPanel('folder')}><FolderOpen /><span>{folder!.name}</span></button></div>}
    <main aria-busy={loading}>
      {offline && <div className="notice error" role="alert"><span>{APP_NAME} is not responding. Check that it is still running in Terminal.</span><button className="text-button" onClick={refreshStatus}>Retry</button></div>}
      {status && !folder ? <div className="empty welcome"><h1>Choose a folder of images</h1><p>{APP_NAME} shows every image inside it, including subfolders, and keeps its own cache. Your files are never changed.</p><FolderChooser status={status} onOpened={applyStatus} /></div>
      : !ready ? <div className="skeleton" aria-label="Loading images">{Array.from({ length: 5 }, (_, i) => <span key={i} />)}</div>
      : mapped ? <Embedding key={root} root={root} rootName={folder!.name} filters={filters} highlight={highlight} search={library!.search} scanning={!!scanBusy} revision={revision + live} filtered={filtered} searching={searching} onOpen={setPicked} onSimilar={findSimilar} onLibrary={() => setPanel('library')} onReset={reset} /> : <>
      {scan?.state === 'error' && <div className="notice error" role="alert"><span>{scan.error}{library!.counts.images ? ' Showing the images from the last scan.' : ''}</span><button className="text-button" onClick={() => setPanel('folder')}>Choose folder</button></div>}
      {error && <div className="notice error" role="alert"><span>{error}</span><button className="text-button" onClick={() => setRevision(r => r + 1)}>Retry</button>{searching && <button className="text-button" onClick={() => setPanel('library')}>Search setup</button>}</div>}
      {loading && !items.length ? <div className="skeleton" aria-label="Loading images">{Array.from({ length: 5 }, (_, i) => <span key={i} />)}</div>
      : !items.length && !error ? (searching || filtered ? <div className="empty"><h1>No images here</h1><p>Try another search, or widen the folder, type or date filters.</p><button className="text-button" onClick={reset}>Clear search and filters</button></div>
        : gathering ? <div className="empty"><h1>Gathering your images</h1><p>{scan?.changed ? `Reading ${scan.done?.toLocaleString()} of ${plural(scan.changed, 'file')} in ${folder!.name}. Images appear as they are found.` : `Looking through ${folder!.name} and its subfolders.`}</p><div className="empty-progress"><Progress value={scan?.changed ? (scan.done ?? 0) / scan.changed : null} label="Reading images" /></div></div>
        : <div className="empty"><h1>No images in this folder</h1><p>{folder!.name} has no JPEG, PNG, HEIC, WebP, GIF, TIFF, BMP or AVIF files. Hidden folders are skipped.</p><button className="text-button" onClick={() => setPanel('folder')}>Choose another folder</button></div>)
      : <Gallery items={items} onOpen={setSelected} />}
      {more && !loading && <div className="load-more" ref={sentinel} aria-live="polite">{loadingMore ? 'Loading…' : ''}</div>}
      </>}
    </main>
    {panel === 'filters' && <FilterPanel filters={filters} onApply={setFilters} onClose={() => setPanel(null)} />}
    {panel === 'library' && status?.library && <LibraryPanel status={status} onClose={() => setPanel(null)} onRefresh={refreshStatus} />}
    {panel === 'folder' && status && <FolderPanel status={status} onOpened={applyStatus} onClose={() => setPanel(null)} />}
    {panel === 'search' && <SearchPanel mode={mode} onMode={setMode} onUpload={() => uploadRef.current?.click()} onClose={() => setPanel(null)} />}
    {selected !== null && items[selected] && <Viewer items={items} index={selected} onChange={changeSelected} total={total} hasMore={more} loadingMore={loadingMore} pageError={error} rootName={folder?.name ?? ''} platform={status?.platform ?? ''} onClose={() => setSelected(null)} onSimilar={findSimilar} onFolder={showFolder} />}
    {picked && <Viewer items={[picked]} index={0} onChange={() => {}} total={1} hasMore={false} loadingMore={false} pageError="" rootName={folder?.name ?? ''} platform={status?.platform ?? ''} onClose={() => setPicked(null)} onSimilar={findSimilar} onFolder={showFolder} />}
    <input className="sr-only" ref={uploadRef} type="file" accept="image/*,.heic,.heif" aria-label="Image to match" tabIndex={-1} onChange={e => { if (e.target.files?.[0]) useImage(e.target.files[0]); e.target.value = ''; }} />
  </div>;
}
