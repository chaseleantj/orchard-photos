import app from '../../app.json';

export const APP_NAME = app.name;
export type SearchMode = 'name' | 'visual';
export type View = 'grid' | 'map';
export type Range = 'all' | 'today' | '7d' | '28d' | 'year' | 'custom';
export interface Filters { folder: string; type: string; range: Range; from: string; to: string }
/** One image or video, described by its newest file that passes the filters. `dated` says where its date came from,
 *  and `duration` is a video's length in seconds. In the grid it fronts its `group` of near-duplicates, `members`
 *  images in all, counting itself. */
export interface Picture { id: string; width: number; height: number; mime: string; size: number; duration: number | null; date: string; dated: 'taken' | 'modified'; path: string; copies: number; group: string; members: number }
interface FileCopy { path: string; modified: string }
export interface Details { id: string; width: number; height: number; mime: string; size: number; duration: number | null; taken: string | null; camera: string | null; root: string; source: 'folder' | 'photos'; files: FileCopy[]; preview: boolean }
/** `received` and `size` are bytes, sent while the model downloads. */
export interface SearchStatus { state: 'idle' | 'downloading' | 'loading' | 'indexing' | 'ready' | 'error'; indexed: number; total: number; downloaded: boolean; received?: number; size?: number; error?: string }
/** Visual queries can be answered: some images are prepared. */
export const searchable = (search: SearchStatus) => search.indexed > 0;
/** Visual search is downloading, starting, or preparing images for the first time. */
export const settingUp = (search: SearchStatus) => search.state === 'downloading' || search.state === 'loading' || (search.state === 'indexing' && !search.indexed);
export interface Scan { state: 'ready' | 'scanning' | 'error'; found?: number; done?: number; changed?: number; error?: string }
export interface LibraryStatus {
  /** `images` counts videos too, and `videos` how many of them are videos. */
  counts: { images: number; videos: number; files: number; duplicates: number; nearDuplicates: number; unreadable: number };
  unlistedFolders: number; unreached: number; photoLibraries: string[]; scan: Scan; search: SearchStatus; updated?: string; revision: number;
}
/** `photos` says this is the Mac's Photos library, read through Photos rather than as files. */
export interface Folder { path: string; label: string; name: string; id: string; photos: boolean }
interface RecentFolder { path: string; label: string; available: boolean }
/** The visual search model, shared by every folder. `present` says it is downloaded or on its way, and `size` is its
 *  download in bytes. */
export interface Model { present: boolean; size: number }
/** What setting up visual search is called, the same wherever it is offered. */
export const SET_UP = 'Set up visual search';
/** `photos` is the path that opens the Photos library, on a Mac that can read it. */
export interface Status { app: string; version: string; platform: string; picker: boolean; model: Model; folder: Folder | null; library: LibraryStatus | null; recent: RecentFolder[]; photos: string | null }
/** The opt-in check for a newer release, and the release it found, if any. */
export interface Updates { enabled: boolean; update: { version: string; url: string } | null }
export interface Facets { folders: { path: string; count: number }[]; types: { mime: string; count: number }[] }
/** How many tiles of the date-ordered grid fall in each month (`YYYY-MM`), newest first. */
export interface Timeline { months: { month: string; count: number }[]; total: number }
export interface Results { items: Picture[]; total: number; offset: number; hasMore: boolean }

export const defaults: Filters = { folder: '', type: '', range: 'all', from: '', to: '' };
export const RANGES: { range: Range; label: string; days?: number }[] = [{ range: 'today', label: 'Today', days: 1 }, { range: '7d', label: 'Past 7 days', days: 7 }, { range: '28d', label: 'Past 28 days', days: 28 }, { range: 'year', label: 'Past year', days: 365 }, { range: 'all', label: 'All' }, { range: 'custom', label: 'Custom range' }];
const localDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
/** The dates a filter selects. Presets are relative to now, so they stay correct when the app is left open. */
function dateBounds({ range, from, to }: Filters) {
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
export const post = <T,>(path: string, body: unknown = {}) => request<T>(path, { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } });
/** Thumbnails are small WebP copies, a video's of its first frame; `display` is the original, or a converted JPEG for
 *  images browsers cannot show. */
export function imageUrl(id: string, size: 'thumbnail' | 'display' = 'thumbnail') { return `/api/images/${id}/${size}`; }
export const downloadUrl = (id: string, path: string) => `/api/images/${id}/original?${new URLSearchParams({ path, download: '1' })}`;

/** Browser storage keys, namespaced by the app so two local apps never read each other's settings. */
export const storageKey = (name: string) => `${app.slug}.${name}`;
const STORAGE = storageKey('preferences');
interface Preferences { filters: Filters; theme: 'light' | 'dark'; view: View; root: string }
// Filters saved before videos shared one type name a single format, like video/quicktime.
const savedType = (type: unknown) => typeof type !== 'string' ? '' : isVideo({ mime: type }) ? VIDEO_TYPE : type;
export function readPreferences(): Preferences {
  const theme = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE) || '{}');
    const f = saved.filters || {};
    const text = (s: unknown) => typeof s === 'string' ? s : '';
    const validDate = (s: unknown) => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : '';
    const custom = validDate(f.from) || validDate(f.to);
    const filters: Filters = { folder: text(f.folder), type: savedType(f.type), range: RANGES.some(r => r.range === f.range && r.range !== 'all') ? f.range : custom ? 'custom' : 'all', from: validDate(f.from), to: validDate(f.to) };
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
/** The type filter's value for every video format, matching the server's. */
const VIDEO_TYPE = 'video';
const TYPES: Record<string, string> = {
  'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/gif': 'GIF', 'image/webp': 'WebP', 'image/avif': 'AVIF', 'image/bmp': 'BMP', 'image/tiff': 'TIFF', 'image/heif': 'HEIC',
  'video/quicktime': 'MOV', 'video/mp4': 'MP4', 'video/x-m4v': 'M4V', 'video/webm': 'WebM', 'video/x-matroska': 'MKV', 'video/x-msvideo': 'AVI', 'video/mpeg': 'MPEG', 'video/mp2t': 'MTS', 'video/3gpp': '3GP', 'video/x-ms-wmv': 'WMV', 'video/x-flv': 'FLV',
};
// RAW photos are typed image/x- and their extension, like image/x-nef.
export const typeLabel = (mime: string) => mime === VIDEO_TYPE ? 'Videos' : TYPES[mime] || mime.replace(/^(image|video)\/(x-)?/, '').toUpperCase();
export const isVideo = (picture: { mime: string }) => picture.mime.startsWith(`${VIDEO_TYPE}/`);
/** A video's length as a clock reads it, like 0:42 or 1:02:03. */
export function durationLabel(seconds: number) {
  const whole = Math.round(seconds), hours = Math.floor(whole / 3600), minutes = Math.floor(whole / 60) % 60, rest = String(whole % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}
export function sizeLabel(bytes: number) {
  if (bytes < 1000) return `${bytes} B`;
  const [value, unit] = bytes < 1e6 ? [bytes / 1e3, 'KB'] : bytes < 1e9 ? [bytes / 1e6, 'MB'] : [bytes / 1e9, 'GB'];
  return `${value.toLocaleString(undefined, { maximumFractionDigits: value < 10 ? 1 : 0 })} ${unit}`;
}
export const megabytes = (bytes: number) => Math.round(bytes / 1e6).toLocaleString();
export const plural = (count: number, one: string, many = `${one}s`) => `${count.toLocaleString()} ${count === 1 ? one : many}`;
/** What counts of the library call what it holds: images, or items once it holds videos too, as Apple Photos does. */
export const countNoun = (library: LibraryStatus | null) => library?.counts.videos ? 'item' : 'image';

export const IMAGE_DRAG = 'application/x-library-image';
// The macOS window finds the image's id in the drag's data after this mark, and adds its file once the drag leaves.
const IMAGE_MARK = 'library-image:';
/** Lets an image from the folder be dragged into the search bar to find similar images, or out of the window. */
export function dragImage(id: string) { return (e: React.DragEvent) => { e.dataTransfer.setData(IMAGE_DRAG, IMAGE_MARK + id); e.dataTransfer.effectAllowed = 'copy'; }; }
/** The id of an image dragged from the grid or viewer, or '' for anything else. */
export function draggedImage(data: DataTransfer) { const value = data.getData(IMAGE_DRAG); return value.startsWith(IMAGE_MARK) ? value.slice(IMAGE_MARK.length) : ''; }
