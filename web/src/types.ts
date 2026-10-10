import app from '../../app.json';

export const APP_NAME = app.name;
export type SearchMode = 'name' | 'visual';
export type View = 'grid' | 'map';
export type Range = 'all' | 'today' | '7d' | '28d' | 'year' | 'custom';
export interface Filters { folder: string; type: string; range: Range; from: string; to: string }
/** One image, described by its newest file that passes the filters. `dated` says where its date came from.
 *  In the grid it fronts its `group` of near-duplicates, `members` images in all, counting itself. */
export interface Picture { id: string; width: number; height: number; mime: string; size: number; date: string; dated: 'taken' | 'modified'; path: string; copies: number; group: string; members: number }
export interface FileCopy { path: string; modified: string }
export interface Details { id: string; width: number; height: number; mime: string; size: number; taken: string | null; camera: string | null; root: string; files: FileCopy[]; preview: boolean }
/** `received` and `size` are bytes, sent while the model downloads. */
export interface SearchStatus { state: 'idle' | 'downloading' | 'loading' | 'indexing' | 'ready' | 'error'; indexed: number; total: number; downloaded: boolean; received?: number; size?: number; error?: string }
/** Visual queries can be answered: some images are prepared. */
export const searchable = (search: SearchStatus) => search.indexed > 0;
/** Visual search is downloading, starting, or preparing images for the first time. */
export const settingUp = (search: SearchStatus) => search.state === 'downloading' || search.state === 'loading' || (search.state === 'indexing' && !search.indexed);
export interface Scan { state: 'ready' | 'scanning' | 'error'; found?: number; done?: number; changed?: number; error?: string }
export interface LibraryStatus {
  counts: { images: number; files: number; duplicates: number; nearDuplicates: number; unreadable: number };
  unreadable: { path: string; error: string }[]; unlistedFolders: number; photoLibraries: string[]; scan: Scan; search: SearchStatus; updated?: string; revision: number;
}
export interface Folder { path: string; label: string; name: string; id: string }
export interface RecentFolder { path: string; label: string; available: boolean }
/** `model` says the visual search model is downloaded or on its way. */
export interface Status { app: string; platform: string; model: boolean; folder: Folder | null; library: LibraryStatus | null; recent: RecentFolder[] }
export interface Facets { folders: { path: string; count: number }[]; types: { mime: string; count: number }[] }
/** How many tiles of the date-ordered grid fall in each month (`YYYY-MM`), newest first. */
export interface Timeline { months: { month: string; count: number }[]; total: number }
export interface Results { items: Picture[]; total: number; offset: number; hasMore: boolean }

export const defaults: Filters = { folder: '', type: '', range: 'all', from: '', to: '' };
export const RANGES: { range: Range; label: string; days?: number }[] = [{ range: 'today', label: 'Today', days: 1 }, { range: '7d', label: 'Past 7 days', days: 7 }, { range: '28d', label: 'Past 28 days', days: 28 }, { range: 'year', label: 'Past year', days: 365 }, { range: 'all', label: 'All' }, { range: 'custom', label: 'Custom range' }];
const localDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
/** The dates a filter selects. Presets are relative to now, so they stay correct when the app is left open. */
export function dateBounds({ range, from, to }: Filters) {
  const days = RANGES.find(r => r.range === range)?.days;
  if (!days) return range === 'custom' ? { from, to } : { from: '', to: '' };
  const start = new Date(); start.setDate(start.getDate() - days + 1);
  return { from: localDay(start), to: '' };
}
export const filterParams = (filters: Filters) => ({ folder: filters.folder, type: filters.type, ...dateBounds(filters), tz: String(-new Date().getTimezoneOffset()) });
export function rangeLabel(filters: Filters) {
  if (filters.range !== 'custom') return RANGES.find(r => r.range === filters.range && r.days)?.label || '';
  return filters.from && filters.to ? `${dateLabel(filters.from)} – ${dateLabel(filters.to)}` : filters.from ? `From ${dateLabel(filters.from)}` : filters.to ? `Until ${dateLabel(filters.to)}` : '';
}
export const isFiltered = (filters: Filters) => !!filters.folder || !!filters.type || filters.range !== 'all';

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.error || `${APP_NAME} could not be reached. Check that it is running, then retry.`);
  return data;
}
export const post = <T,>(path: string, body?: unknown) => request<T>(path, { method: 'POST', ...(body === undefined ? {} : { body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } }) });
/** Thumbnails are small WebP copies; `display` is the original, or a converted JPEG for formats browsers cannot show. */
export function imageUrl(id: string, size: 'thumbnail' | 'display' = 'thumbnail') { return `/api/images/${id}/${size}`; }
export const downloadUrl = (id: string, path: string) => `/api/images/${id}/original?${new URLSearchParams({ path, download: '1' })}`;

/** Browser storage keys, namespaced by the app so two local apps never read each other's settings. */
export const storageKey = (name: string) => `${app.slug}.${name}`;
const STORAGE = storageKey('preferences');
export interface Preferences { filters: Filters; theme: 'light' | 'dark'; view: View; root: string }
export function readPreferences(): Preferences {
  const theme = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE) || '{}');
    const f = saved.filters || {};
    const text = (s: unknown) => typeof s === 'string' ? s : '';
    const validDate = (s: unknown) => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : '';
    const custom = validDate(f.from) || validDate(f.to);
    const filters: Filters = { folder: text(f.folder), type: text(f.type), range: RANGES.some(r => r.range === f.range && r.range !== 'all') ? f.range : custom ? 'custom' : 'all', from: validDate(f.from), to: validDate(f.to) };
    if (filters.from && filters.to && filters.from > filters.to) { filters.from = ''; filters.to = ''; }
    return { filters, theme: ['light', 'dark'].includes(saved.theme) ? saved.theme : theme, view: saved.view === 'map' ? 'map' : 'grid', root: text(saved.root) };
  } catch { return { filters: defaults, theme, view: 'grid', root: '' }; }
}
export function savePreferences(preferences: Preferences) {
  try { localStorage.setItem(STORAGE, JSON.stringify(preferences)); } catch { /* Browsing remains available without storage. */ }
}

export function dateLabel(date: string, full = false) {
  return new Date(date).toLocaleString(undefined, full ? { year: 'numeric', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit' } : { year: 'numeric', month: 'short', day: 'numeric' });
}
/** A month as the grid's headings and the timeline name it, like "June 2026". */
export const monthLabel = (date: Date) => date.toLocaleString(undefined, { month: 'long', year: 'numeric' });
/** A `YYYY-MM` month as a local date on its first day. */
export const monthStart = (month: string) => new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)) - 1, 1);
export const fileName = (path: string) => path.slice(path.lastIndexOf('/') + 1);
export const folderOf = (path: string) => path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
const TYPES: Record<string, string> = { 'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/gif': 'GIF', 'image/webp': 'WebP', 'image/avif': 'AVIF', 'image/bmp': 'BMP', 'image/tiff': 'TIFF', 'image/heif': 'HEIC' };
export const typeLabel = (mime: string) => TYPES[mime] || mime.replace(/^image\//, '').toUpperCase();
export function sizeLabel(bytes: number) {
  if (bytes < 1000) return `${bytes} B`;
  const [value, unit] = bytes < 1e6 ? [bytes / 1e3, 'KB'] : bytes < 1e9 ? [bytes / 1e6, 'MB'] : [bytes / 1e9, 'GB'];
  return `${value.toLocaleString(undefined, { maximumFractionDigits: value < 10 ? 1 : 0 })} ${unit}`;
}
export const megabytes = (bytes: number) => Math.round(bytes / 1e6).toLocaleString();
export const plural = (count: number, one: string, many = `${one}s`) => `${count.toLocaleString()} ${count === 1 ? one : many}`;

export const IMAGE_DRAG = 'application/x-library-image';
/** Lets an image from the folder be dragged into the search bar to find similar images. */
export function dragImage(id: string) { return (e: React.DragEvent) => { e.dataTransfer.setData(IMAGE_DRAG, id); e.dataTransfer.effectAllowed = 'copy'; }; }
