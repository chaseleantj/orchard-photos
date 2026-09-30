import { forwardRef, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Maximize, Minus, Plus, RefreshCw, X } from 'lucide-react';
import { MapEngine } from './mapEngine';
import type { MapCamera, MapPoint } from './mapEngine';
import { APP_NAME, dateLabel, dragImage, fileName, filterParams, folderOf, imageUrl, request, storageKey } from './types';
import { Progress } from './Progress';
import type { Filters, SearchStatus } from './types';

interface Working { state: string; stage?: string; error?: string }
interface MapData { points: MapPoint[]; pending: number; sheets: string[]; layout: Working }
type Phase = 'loading' | 'ready' | 'error';

const CARD_EDGE = 240;
const CARD_EDGE_NARROW = 190;
const CARD_PAD = 8;
const CARD_MARGIN = 12;
const STORAGE = storageKey('map');

// A stable scatter that previews the shape of the map while it loads.
const placeholder = Array.from({ length: 46 }, (_, i) => {
  const a = Math.sin(i * 12.9898) * 43758.5453, b = Math.sin(i * 78.233) * 12543.145;
  const angle = (a - Math.floor(a)) * Math.PI * 2, radius = Math.sqrt(b - Math.floor(b)) * 0.36;
  return { x: 50 + Math.cos(angle) * radius * 100 * 1.1, y: 50 + Math.sin(angle) * radius * 100 * 0.8, delay: (i % 9) * 0.18 };
});

function readCamera(key: string): MapCamera | undefined {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE) || 'null');
    if (saved?.key === key && [saved.x, saved.y, saved.zoom].every(Number.isFinite)) return { x: saved.x, y: saved.y, zoom: saved.zoom };
  } catch { /* A missing camera just means the map starts fitted. */ }
}

interface Props {
  root: string; rootName: string; filters: Filters; highlight: string[] | null; search: SearchStatus; scanning: boolean; revision: number; filtered: boolean; searching: boolean;
  onOpen: (point: MapPoint) => void; onSimilar: (id: string) => void; onLibrary: () => void; onReset: () => void;
}

export default function Embedding({ root, rootName, filters, highlight, search, scanning, revision, filtered, searching, onOpen, onSimilar, onLibrary, onReset }: Props) {
  const stage = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const engine = useRef<MapEngine | null>(null);
  const card = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState('');
  const [data, setData] = useState<MapData | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [working, setWorking] = useState<Working | null>(null);
  const [slow, setSlow] = useState(false);
  const [sheetsLoaded, setSheetsLoaded] = useState<number | null>(null);
  const shown = useRef({ key: '', sheets: '' });
  const [size, setSize] = useState({ width: 1440 });
  // Each folder has its own map, and each filter its own remembered view of it.
  const key = JSON.stringify({ root, ...filterParams(filters) });
  const unprepared = search.indexed === 0;
  // With the model on this computer, images still being found or waiting for their turn are indexed without asking.
  const preparing = search.state === 'loading' || search.state === 'indexing' || (search.downloaded && search.state === 'idle' && (scanning || search.indexed < search.total));
  // A folder's first map waits for all of its images, so its first layout is the real one.
  const holding = preparing && !data;
  const byId = useMemo(() => new Map((data?.points ?? []).map(p => [p.id, p])), [data]);
  const selected = selectedId ? byId.get(selectedId) ?? null : null;
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selectedId;

  const place = useCallback(() => {
    const node = card.current, id = selectedRef.current, map = engine.current, host = stage.current;
    if (!node || !id || !map || !host) return;
    const at = map.project(id);
    if (!at) return;
    const surface = node.firstElementChild as HTMLElement, image = surface.firstElementChild as HTMLElement;
    const halfWidth = surface.offsetWidth / 2, above = CARD_PAD + image.offsetHeight / 2, below = surface.offsetHeight - above;
    const x = Math.min(Math.max(at.x, CARD_MARGIN + halfWidth), Math.max(CARD_MARGIN + halfWidth, host.clientWidth - CARD_MARGIN - halfWidth));
    const y = Math.min(Math.max(at.y, CARD_MARGIN + above), Math.max(CARD_MARGIN + above, host.clientHeight - CARD_MARGIN - below));
    node.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
  }, []);
  useLayoutEffect(place, [selectedId, place]);

  const callbacks = useRef({ open: onOpen, place });
  callbacks.current = { open: onOpen, place };

  // The engine lives as long as the view; data comes and goes underneath it.
  useEffect(() => {
    const map = new MapEngine(canvas.current!, stage.current!, {
      onSelect: setSelectedId,
      onFrame: () => callbacks.current.place(),
      onSettle: camera => { try { localStorage.setItem(STORAGE, JSON.stringify({ key: keyRef.current, ...camera })); } catch { /* Position is a convenience. */ } },
    });
    engine.current = map;
    const observer = new ResizeObserver(([entry]) => { setSize({ width: entry.contentRect.width }); map.resize(entry.contentRect.width, entry.contentRect.height, devicePixelRatio); });
    observer.observe(stage.current!);
    return () => { observer.disconnect(); map.destroy(); engine.current = null; };
  }, []);
  const keyRef = useRef(key);
  keyRef.current = key;

  const follow = useCallback(async (signal?: AbortSignal) => {
    for (;;) {
      await new Promise(done => setTimeout(done, 400));
      const now = await request<Working>('/api/layout', { signal });
      setWorking(now);
      if (now.state === 'error') throw new Error(now.error);
      if (now.state === 'idle') return;
    }
  }, []);
  const relayout = async () => {
    setWorking({ state: 'computing', stage: 'Laying out the map' });
    try { await request('/api/layout', { method: 'POST' }); await follow(); setWorking(null); setRetry(r => r + 1); }
    catch (e) { setWorking(null); setError((e as Error).message); setPhase('error'); }
  };
  // A bar only appears for work that outlasts a blink.
  const busy = phase === 'loading' || !!working;
  useEffect(() => { if (!busy) { setSlow(false); return; } const timer = setTimeout(() => setSlow(true), 250); return () => clearTimeout(timer); }, [busy]);
  useEffect(() => {
    if (unprepared || holding) return;
    const controller = new AbortController();
    setPhase(old => old === 'ready' ? old : 'loading'); setError('');
    const params = new URLSearchParams(filterParams(filters));
    (async () => {
      const result = await request<MapData>(`/api/map?${params}`, { signal: controller.signal });
      if (result.layout.state !== 'ready') {
        // The first UMAP fit runs on the server; follow it, then load the map.
        setWorking(result.layout);
        await follow(controller.signal);
        setWorking(null); setRetry(r => r + 1);
        return;
      }
      setWorking(null);
      // The icon sheets only change when images are added, so a new filter or refit keeps the decoded ones.
      const versions = result.sheets.join();
      let sheets: ImageBitmap[] | null = null;
      if (versions !== shown.current.sheets) {
        let loaded = 0;
        sheets = await Promise.all(result.sheets.map((version, n) => new Promise<ImageBitmap>((resolve, reject) => {
          const image = new Image();
          // Bitmaps stay decoded; a plain image can be evicted from the browser's cache and re-decoded mid-zoom.
          image.onload = () => { setSheetsLoaded(++loaded / result.sheets.length); createImageBitmap(image).then(resolve, reject); }; image.onerror = () => reject(new Error('The map images could not load. Retry, or rescan the folder.'));
          image.src = `/api/atlas/${n}?v=${version}`;
        })));
      }
      if (controller.signal.aborted) return;
      const map = engine.current!;
      if (sheets) map.setSheets(sheets);
      // The same folder refit, or refreshed by a scan, glides instead of restarting.
      if (shown.current.key === key) map.morph(result.points, false);
      else map.setPoints(result.points, readCamera(key));
      shown.current = { key, sheets: versions };
      setData(result); setPhase('ready'); setSheetsLoaded(null);
    })().catch(e => { if (e.name !== 'AbortError') { setError(e instanceof TypeError ? `${APP_NAME} could not be reached. Check that it is running, then retry.` : e.message); setPhase('error'); } });
    return () => controller.abort();
    // The map reloads when the folder or filters change, a scan lands, or the user retries; search only lights points up.
  }, [key, revision, retry, unprepared, preparing]); // eslint-disable-line react-hooks/exhaustive-deps

  const lit = highlight && highlight.length ? highlight : null;
  useEffect(() => { if (phase === 'ready') engine.current?.setHighlight(lit); }, [lit, phase, data]);

  // Bring the view back to everything once a search is cleared.
  const wasLit = useRef(false);
  useEffect(() => { if (phase === 'ready' && wasLit.current && !lit) engine.current?.fit(); wasLit.current = !!lit; }, [lit, phase]);

  const view = useCallback((id: string | null) => { const point = id ? byId.get(id) : null; if (point) onOpen(point); }, [byId, onOpen]);
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && selectedId) { e.preventDefault(); view(selectedId); return; }
    if ((e.key === 's' || e.key === 'S') && selectedId && !e.metaKey && !e.ctrlKey) { e.preventDefault(); onSimilar(selectedId); return; }
    if (engine.current?.key(e.nativeEvent)) e.preventDefault();
  };

  const empty = phase === 'ready' && data && data.points.length === 0;
  return <div className="map-stage" ref={stage} aria-busy={phase === 'loading'}>
    <canvas ref={canvas} className="map-canvas" tabIndex={0} role="application" aria-label="Image map. Similar images sit close together. Arrow keys move, plus and minus zoom, zero shows everything, Enter selects the image nearest the middle." onKeyDown={onKeyDown} />
    {phase === 'loading' && !unprepared && !holding && <div className="map-placeholder" role="status" aria-label="Placing images">{placeholder.map((p, i) => <span key={i} style={{ left: `${p.x}%`, top: `${p.y}%`, animationDelay: `${p.delay}s` }} />)}</div>}
    {slow && busy && <div className="map-progress"><Progress value={working ? null : sheetsLoaded} label={working?.stage || 'Loading the map'} /></div>}
    {slow && working && <p className="map-note" role="status">{working.stage}…</p>}
    {!unprepared && phase !== 'error' && <div className="map-refit"><button className="icon-button" aria-label="Refit the map" title="Lay out the map again from every image in the folder" disabled={!!working || phase !== 'ready'} onClick={relayout}><RefreshCw /></button></div>}
    {unprepared && !preparing && <div className="empty map-message"><h1>Your folder, laid out by look</h1><p>Prepare visual search once and similar images will gather here.</p><button className="text-button" onClick={onLibrary}>Visual search</button></div>}
    {holding && <div className="empty map-message" role="status"><h1>Preparing visual search</h1><p>{search.state === 'loading' ? 'Loading the search model.' : !search.total ? 'Looking for images in the folder.' : `${search.indexed.toLocaleString()} of ${search.total.toLocaleString()} images ready. The map opens when they all are.`}</p><div className="map-message-progress"><Progress value={search.total ? search.indexed / search.total : null} label="Preparing images" /></div></div>}
    {phase === 'error' && <div className="empty map-message" role="alert"><h1>The map didn’t load</h1><p>{error}</p><button className="text-button" onClick={() => setRetry(r => r + 1)}>Retry</button></div>}
    {empty && <div className="empty map-message"><h1>No images here</h1><p>{filtered ? 'Widen the date range, or choose another folder or file type.' : 'This folder has no images yet.'}</p>{(filtered || searching) && <button className="text-button" onClick={onReset}>Clear search and filters</button>}</div>}
    {phase === 'ready' && !working && !!data?.pending && <p className="map-note" aria-live="polite">{data.pending.toLocaleString()} {data.pending === 1 ? 'image is' : 'images are'} still being prepared</p>}
    {phase === 'ready' && !empty && <div className="map-controls" role="group" aria-label="Map view">
      <button className="icon-button" aria-label="Zoom in" title="Zoom in" onClick={() => engine.current?.zoomBy(1.7)}><Plus /></button>
      <button className="icon-button" aria-label="Zoom out" title="Zoom out" onClick={() => engine.current?.zoomBy(1 / 1.7)}><Minus /></button>
      <button className="icon-button" aria-label="Show everything" title="Show everything" onClick={() => engine.current?.fit()}><Maximize /></button>
    </div>}
    {selected && <Card key={selected.id} ref={card} point={selected} rootName={rootName} narrow={size.width < 560} onClose={() => engine.current?.select(null)} tile={engine.current?.project(selected.id)?.size ?? 24} place={place}
      onView={() => onOpen(selected)} onSimilar={() => onSimilar(selected.id)} />}
  </div>;
}


const Card = forwardRef<HTMLDivElement, { point: MapPoint; rootName: string; narrow: boolean; onClose: () => void; tile: number; place: () => void; onView: () => void; onSimilar: () => void }>(function Card({ point, rootName, narrow, onClose, tile, place, onView, onSimilar }, ref) {
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);
  const longest = Math.max(point.width, point.height);
  const edge = narrow ? CARD_EDGE_NARROW : CARD_EDGE;
  const scale = Math.min(edge, Math.max(150, longest)) / longest;
  const width = Math.max(48, Math.round(point.width * scale)), height = Math.max(48, Math.round(point.height * scale));
  const square = Math.min(width, height);
  useEffect(() => { const frame = requestAnimationFrame(() => requestAnimationFrame(() => setOpen(true))); return () => cancelAnimationFrame(frame); }, []);
  useLayoutEffect(place, [place]);
  // Start exactly on the tile: its centred square crop, scaled to the tile's size.
  const from = { '--from': tile / square, '--cut-x': `${(width - square) / 2}px`, '--cut-y': `${(height - square) / 2}px` } as React.CSSProperties;
  return <div className="map-card" ref={ref} data-open={open} style={{ ...from, '--card-width': `${Math.max(width, 208) + 2 * CARD_PAD}px` } as React.CSSProperties}>
    <div className="map-card-surface" style={{ marginTop: -(CARD_PAD + height / 2) }}>
      <div className="map-card-image" style={{ width, height }}>
        {failed ? <span className="missing">Preview unavailable</span> : <img src={imageUrl(point.id)} alt={fileName(point.path)} width={width} height={height} onError={() => setFailed(true)} onDragStart={dragImage(point.id)} />}
      </div>
      <div className="map-card-caption">
        <p className="map-card-title" title={point.path}>{fileName(point.path)}</p>
        <p className="map-card-meta">{folderOf(point.path) || rootName} · {dateLabel(point.date)}</p>
        <div className="map-card-actions"><button className="text-button" onClick={onView}>View</button><button className="text-button" onClick={onSimilar}>Find similar</button><button className="icon-button" aria-label="Close preview" onClick={onClose}><X /></button></div>
      </div>
    </div>
  </div>;
});
