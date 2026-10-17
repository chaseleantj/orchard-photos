import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Maximize, Minus, Plus } from 'lucide-react';
import { MapEngine, PER_SHEET } from './mapEngine';
import type { MapCallbacks, MapCamera, MapPoint } from './mapEngine';
import { APP_NAME, SET_UP, filterParams, megabytes, request, storageKey } from './types';
import { Progress } from './Progress';
import { searchWork } from './Activity';
import type { Filters, Model, SearchStatus } from './types';

interface Working { state: string; stage?: string; error?: string }
interface MapData { points: MapPoint[]; pending: number; omitted: number; sheets: string[]; layout: Working }
type Phase = 'loading' | 'ready' | 'error';

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
  root: string; filters: Filters; highlight: string[] | null; search: SearchStatus; model: Model; scanning: boolean; revision: number; filtered: boolean; searching: boolean;
  onOpen: (point: MapPoint) => void; onSimilar: (id: string) => void; onCarry: MapCallbacks['onCarry']; left: string; onSetUp: () => void; onReset: () => void;
}

export default function Embedding({ root, filters, highlight, search, model, scanning, revision, filtered, searching, onOpen, onSimilar, onCarry, left, onSetUp, onReset }: Props) {
  const stage = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const engine = useRef<MapEngine | null>(null);
  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState('');
  const [data, setData] = useState<MapData | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [working, setWorking] = useState<Working | null>(null);
  const [slow, setSlow] = useState(false);
  const [sheetsLoaded, setSheetsLoaded] = useState<number | null>(null);
  const shown = useRef({ key: '', sheets: '' });
  // Each folder has its own map, and each filter its own remembered view of it.
  const key = JSON.stringify({ root, ...filterParams(filters) });
  const unprepared = search.indexed === 0;
  // With the model on this computer, images still being found or waiting for their turn are indexed without asking.
  const preparing = search.state === 'downloading' || search.state === 'loading' || search.state === 'indexing' || (search.downloaded && search.state === 'idle' && (scanning || search.indexed < search.total));
  const work = searchWork(search);
  // A folder's first map waits for all of its images, so its first layout is the real one.
  const holding = preparing && !data;
  const byId = useMemo(() => new Map((data?.points ?? []).map(p => [p.id, p])), [data]);
  const callbacks = useRef({ open: (id: string) => { const point = byId.get(id); if (point) onOpen(point); }, carry: onCarry });
  callbacks.current = { open: (id: string) => { const point = byId.get(id); if (point) onOpen(point); }, carry: onCarry };

  // The engine lives as long as the view; data comes and goes underneath it.
  useEffect(() => {
    const map = new MapEngine(canvas.current!, stage.current!, {
      onSelect: setSelectedId,
      onOpen: id => callbacks.current.open(id),
      onCarry: (id, x, y, dropped) => callbacks.current.carry(id, x, y, dropped),
      onSettle: camera => { try { localStorage.setItem(STORAGE, JSON.stringify({ key: keyRef.current, ...camera })); } catch { /* Position is a convenience. */ } },
    });
    engine.current = map;
    const observer = new ResizeObserver(([entry]) => { map.resize(entry.contentRect.width, entry.contentRect.height, devicePixelRatio); });
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
  // A bar only appears for work that outlasts a blink.
  const busy = (phase === 'loading' && !unprepared && !holding) || !!working;
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
      // Only the sheets holding the shown images are decoded, and a filter that needs the same ones keeps them.
      const needed = [...new Set(result.points.map(p => Math.floor(p.slot / PER_SHEET)))].sort((a, b) => a - b);
      const versions = needed.map(n => `${n}:${result.sheets[n]}`).join();
      let sheets: ImageBitmap[] | null = null;
      if (versions !== shown.current.sheets) {
        let loaded = 0;
        sheets = [];
        await Promise.all(needed.map(n => new Promise<void>((resolve, reject) => {
          const image = new Image();
          // Bitmaps stay decoded; a plain image can be evicted from the browser's cache and re-decoded mid-zoom.
          image.onload = () => { setSheetsLoaded(++loaded / needed.length); createImageBitmap(image).then(bitmap => { sheets![n] = bitmap; resolve(); }, reject); }; image.onerror = () => reject(new Error('The map images could not load. Retry, or rescan the folder.'));
          image.src = `/api/atlas/${n}?v=${result.sheets[n]}`;
        })));
      }
      if (controller.signal.aborted) return;
      const map = engine.current!;
      if (sheets) map.setSheets(sheets);
      // The same folder refreshed by a scan glides instead of restarting.
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

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && selectedId) { e.preventDefault(); callbacks.current.open(selectedId); return; }
    if ((e.key === 's' || e.key === 'S') && selectedId && !e.metaKey && !e.ctrlKey) { e.preventDefault(); onSimilar(selectedId); return; }
    if (engine.current?.key(e.nativeEvent)) e.preventDefault();
  };

  const empty = phase === 'ready' && data && data.points.length === 0;
  return <div className="map-stage" ref={stage} aria-busy={phase === 'loading'}>
    <canvas ref={canvas} className="map-canvas" tabIndex={0} role="application" aria-label="Image map. Similar images sit close together. Arrow keys move, plus and minus zoom, zero shows everything, Enter selects the image nearest the middle. Press and hold an image, then drag it to the search bar to find similar images." onKeyDown={onKeyDown} />
    {phase === 'loading' && !unprepared && !holding && <div className="map-placeholder" role="status" aria-label="Placing images">{placeholder.map((p, i) => <span key={i} style={{ left: `${p.x}%`, top: `${p.y}%`, animationDelay: `${p.delay}s` }} />)}</div>}
    {slow && busy && <div className="map-progress"><Progress value={working ? null : sheetsLoaded} label={working?.stage || 'Loading the map'} /></div>}
    {slow && working && <p className="map-note" role="status">{working.stage}…</p>}
    {unprepared && !preparing && (search.state === 'error'
      ? <div className="empty map-message" role="alert"><h1>{work?.label ?? 'Visual search couldn’t start'}</h1><p>{search.error}</p><button className="text-button secondary" onClick={onSetUp}>Try again</button></div>
      : <div className="empty map-message"><h1>Your folder, laid out by look</h1><p>Similar images gather together here. Setting up visual search downloads a {megabytes(model.size)} MB model once, which runs on this computer.</p><button className="text-button primary" onClick={onSetUp}>{SET_UP}</button></div>)}
    {holding && <div className="empty map-message" role="status"><h1>Preparing visual search</h1>
      <p>{search.state === 'downloading' ? `${work!.label} · ${work!.detail}.` : search.state === 'loading' ? `${work!.label}.` : !search.total ? 'Looking for images in the folder.' : `${search.indexed.toLocaleString()} of ${search.total.toLocaleString()} images ready. The map opens when they all are.`}{left && ` ${left}.`}</p>
      <div className="map-message-progress"><Progress value={work?.value ?? null} label="Preparing visual search" /></div></div>}
    {phase === 'error' && <div className="empty map-message" role="alert"><h1>The map didn’t load</h1><p>{error}</p><button className="text-button secondary" onClick={() => setRetry(r => r + 1)}>Retry</button></div>}
    {empty && <div className="empty map-message"><h1>No images here</h1><p>{filtered ? 'Widen the date range, or choose another folder or file type.' : 'This folder has no images yet.'}</p>{(filtered || searching) && <button className="text-button secondary" onClick={onReset}>Clear search and filters</button>}</div>}
    {phase === 'ready' && !working && !!data?.pending && <p className="map-note" aria-live="polite">{data.pending.toLocaleString()} {data.pending === 1 ? 'image is' : 'images are'} still being prepared</p>}
    {phase === 'ready' && !working && !data?.pending && !!data?.omitted && <p className="map-note">The map shows the newest {data.points.length.toLocaleString()} images. Filter by date or folder to see the other {data.omitted.toLocaleString()}.</p>}
    {phase === 'ready' && !empty && <div className="map-controls" role="group" aria-label="Map view">
      <button className="icon-button" aria-label="Zoom in" title="Zoom in" onClick={() => engine.current?.zoomBy(1.7)}><Plus /></button>
      <button className="icon-button" aria-label="Zoom out" title="Zoom out" onClick={() => engine.current?.zoomBy(1 / 1.7)}><Minus /></button>
      <button className="icon-button" aria-label="Show everything" title="Show everything" onClick={() => engine.current?.fit()}><Maximize /></button>
    </div>}
  </div>;
}

