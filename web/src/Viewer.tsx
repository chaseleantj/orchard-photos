import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, Copy, Download, FolderOpen, Images, ScanSearch, X, ZoomIn, ZoomOut } from 'lucide-react';
import type { Details, Filters, Picture, Results } from './types';
import { Disclosure } from './Panels';
import { dateLabel, downloadUrl, dragImage, durationLabel, fileName, filterParams, folderOf, imageUrl, isVideo, plural, post, request, sizeLabel, typeLabel } from './types';
import { aheadUrl, imagesAhead, shared } from './preload';
import { scrollsSideways, swipe } from './swipe';
import { stageZoom, type StageZoom } from './zoom';

interface Props {
  items: Picture[]; index: number; total: number; hasMore: boolean; loadingMore: boolean; pageError: string; rootName: string; platform: string; filters: Filters;
  /** The Photos library has no folders, and its photos are shown in Photos rather than Finder. */
  photos: boolean;
  onChange: (index: number) => void; onClose: () => void; onSimilar: ((id: string) => void) | null; onFolder: (folder: string) => void;
}
// The deepest folders name a place; the rest of a long path is in the tooltip and under Details.
const CRUMBS = 3;
// Browsers refuse canvases much larger than this.
const CLIPBOARD_PIXELS = 50_000_000;
const ARROWS: Record<string, ['step' | 'climb', number]> = { ArrowLeft: ['step', -1], ArrowRight: ['step', 1], ArrowUp: ['climb', -1], ArrowDown: ['climb', 1] };

export default function Viewer({ items, index, total, hasMore, loadingMore, pageError, rootName, platform, filters, photos, onChange, onClose, onSimilar, onFolder }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const photo = useRef<HTMLImageElement>(null);
  const zoom = useRef<StageZoom>(null);
  const [zoomed, setZoomed] = useState(false);
  const [loaded, setLoaded] = useState<Details | null>(null);
  const [error, setError] = useState('');
  const [failed, setFailed] = useState(false);
  const [copied, setCopied] = useState<{ id: string; note: string } | null>(null);
  // The grid shows one image per group of near-duplicates; the viewer can show any of them.
  const [stack, setStack] = useState<{ front: string; members: Picture[]; shown: number } | null>(null);
  // Requests for details and near-duplicates, shared by the image on screen and those loaded ahead of it, and the
  // images loaded ahead, all dropped when the viewer closes.
  const [ahead] = useState(() => ({ details: shared<Details>(), stacks: shared<Picture[]>(), images: imagesAhead() }));
  // The way the last step went, so loading ahead follows it.
  const heading = useRef(1);
  const front = items[index];
  const members = stack?.front === front.id ? stack.members : [];
  const shown = members.length ? stack!.shown : 0;
  const showMember = (place: number) => setStack({ ...stack!, shown: place });
  const item = members[shown] ?? front;
  const details = loaded?.id === item.id ? loaded : null;
  const video = isVideo(item);
  const folder = photos ? '' : folderOf(item.path);
  const reveal = photos ? 'Show in Photos' : platform === 'darwin' ? 'Show in Finder' : 'Show in folder';
  const RevealIcon = photos ? Images : FolderOpen;
  useEffect(() => {
    const node = dialog.current!;
    const focus = document.activeElement as HTMLElement;
    node.showModal();
    // The viewer takes focus itself, so the close button is not ringed until the keyboard moves there.
    node.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const zooming = zoom.current = stageZoom(stage.current!, setZoomed);
    return () => { node.close(); document.body.style.overflow = previous; focus?.focus(); zooming.stop(); ahead.images.clear(); };
  }, [ahead]);
  const loadDetails = (id: string) => ahead.details(id, () => request<Details>(`/api/images/${id}`));
  const loadStack = (picture: Picture) => ahead.stacks(picture.group, () => request<Results>(`/api/images?${new URLSearchParams({ ...filterParams(filters), group: picture.group })}`).then(data => data.items));
  // Each image starts fitted, with nothing shown that belonged to the one before. A video isn't zoomed.
  useEffect(() => zoom.current!.set(photo.current), [item.id, failed, video]);
  useEffect(() => {
    let current = true;
    setFailed(false); setError('');
    loadDetails(item.id).then(data => { if (current) setLoaded(data); }).catch(e => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [item.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setStack(null);
    if (front.members < 2) return;
    let current = true;
    loadStack(front).then(data => { if (current) setStack({ front: front.id, members: data, shown: Math.max(0, data.findIndex(member => member.id === front.id)) }); })
      .catch(e => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [front.id, front.group, front.members, filters]); // eslint-disable-line react-hooks/exhaustive-deps
  // Once the image on screen has loaded, so nothing competes with it, the images a step can reach next load: the
  // next two the way the steps go and one behind, and the near-duplicates either side, each with its details. Those
  // that leave this window stop loading.
  const loadAhead = () => {
    const near = [members[shown + 1], members[shown - 1]];
    for (const offset of [heading.current, 2 * heading.current, -heading.current]) {
      const entry = items[index + offset];
      near.push(entry);
      if (entry?.members > 1) loadStack(entry).catch(() => { /* Retried when it is shown. */ });
    }
    const reachable = near.filter(entry => entry && entry.id !== item.id);
    for (const entry of reachable) loadDetails(entry.id).catch(() => { /* Retried when it is shown. */ });
    ahead.images.keep(reachable.map(aheadUrl));
  };
  const fail = () => { setFailed(true); loadAhead(); };
  const canStep = (direction: number) => !loadingMore && (direction < 0 ? index > 0 : index < items.length - 1 || hasMore);
  const step = (direction: number) => { if (!canStep(direction)) return; heading.current = direction; onChange(index + direction); };
  const climb = (direction: number) => { if (members[shown + direction]) showMember(shown + direction); };
  const show = async (path: string) => { setError(''); try { await post(`/api/images/${item.id}/reveal`, { path }); } catch (e) { setError((e as Error).message); } };
  const copy = async () => {
    const id = item.id;
    setError(''); setCopied(null);
    try {
      // Safari only allows the write if the clipboard item is created during the click, so it takes a promise.
      const png = toPng(imageUrl(id, 'display'));
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': png.then(result => result.blob) })]);
      const { width, height, scaled } = await png;
      setCopied({ id, note: scaled ? `Copied at ${width.toLocaleString()} × ${height.toLocaleString()}, the most the clipboard takes` : 'Copied' });
    } catch (e) { setError((e as Error).name === 'NotAllowedError' ? 'This browser blocked the clipboard. Download the image instead.' : 'The image could not be copied. Download it instead.'); }
  };
  // Keys and swipes are read from the window, so they still reach the viewer when focus has fallen out of it, as when
  // the button it was on is disabled.
  const keys = useRef<(e: KeyboardEvent) => void>(null);
  keys.current = e => {
    if (e.defaultPrevented || e.isComposing) return;
    const node = dialog.current!;
    if (!e.composedPath().includes(node)) node.focus({ preventScroll: true });
    if ((e.metaKey || e.ctrlKey) && e.key === 'c' && !video && !getSelection()?.toString()) { e.preventDefault(); void copy(); return; }
    if (zoom.current!.key(e) || e.metaKey || e.ctrlKey || e.altKey || e.shiftKey || !ARROWS[e.key]) return;
    // Every arrow is taken, even with nowhere to go, since the Mac window beeps at a key the page leaves.
    e.preventDefault();
    const [kind, direction] = ARROWS[e.key];
    if (kind === 'step') step(direction); else climb(direction);
  };
  const steps = useRef(step);
  steps.current = step;
  useEffect(() => {
    const node = dialog.current!;
    // One recognizer for every image, so a swipe's momentum stops at the next one.
    const recognize = swipe();
    const wheel = (e: WheelEvent) => {
      if (scrollsSideways(e.target)) return;
      const direction = recognize(e);
      if (direction === null) return;
      // Taking the event also stops the browser's own back swipe.
      e.preventDefault();
      if (direction) steps.current(direction);
    };
    const keydown = (e: KeyboardEvent) => keys.current!(e);
    node.addEventListener('wheel', wheel, { passive: false });
    window.addEventListener('keydown', keydown);
    return () => { node.removeEventListener('wheel', wheel); window.removeEventListener('keydown', keydown); };
  }, []);
  const file = details?.files.find(f => f.path === item.path);
  const others = details?.files.filter(f => f.path !== item.path) ?? [];
  // The date not already shown under the name.
  const otherDate = item.dated === 'taken' ? file && `Modified ${dateLabel(file.modified, true)}` : details?.taken && `Taken ${dateLabel(details.taken, true)}`;
  const parts = folder ? folder.split('/') : [rootName];
  const crumbs = (parts.length > CRUMBS ? ['…', ...parts.slice(-CRUMBS)] : parts).join(' › ');
  return <dialog ref={dialog} tabIndex={-1} className="viewer" aria-label="Image viewer" onCancel={onClose}>
    <div className="viewer-layout">
      <header className="viewer-top"><div className="viewer-navigation">
        <button className="icon-button" aria-label="Previous image" title="Previous image" disabled={!canStep(-1)} onClick={() => step(-1)}><ArrowLeft /></button>
        <span>{(index + 1).toLocaleString()} / {total.toLocaleString()}</span>
        <button className="icon-button" aria-label="Next image" title="Next image" disabled={!canStep(1)} onClick={() => step(1)}><ArrowRight /></button>
      </div><div className="viewer-navigation">
        {!video && <button className="icon-button" aria-label={zoomed ? 'Fit to screen' : 'Zoom in'} aria-keyshortcuts={zoomed ? 'Escape' : undefined} title={zoomed ? 'Fit to screen (Esc)' : 'Zoom in'} onClick={() => zoom.current!.toggle()}>{zoomed ? <ZoomOut /> : <ZoomIn />}</button>}
        <button className="icon-button" aria-label="Close image" title="Close" onClick={onClose}><X /></button>
      </div></header>
      {/* One image element for every step: it keeps showing the last image until the next has loaded, so quick
          steps never flash an empty stage, and each new step replaces the load before it. A video plays at once,
          muted and looping over its first frame, since WebKit only starts a video without sound; its controls unmute it. */}
      <div ref={stage} className="image-stage">
        {failed ? <div className="empty"><p>{video ? 'This video can’t be played here. Download it to watch it.' : 'This image could not be shown. The file may have moved or changed.'}</p><button className="text-button secondary" onClick={() => setFailed(false)}>Retry</button></div>
        : video ? <video key={item.id} src={imageUrl(item.id, 'display')} poster={imageUrl(item.id)} aria-label={fileName(item.path)} autoPlay muted loop controls playsInline onLoadedData={loadAhead} onError={fail} />
        : <img ref={photo} src={imageUrl(item.id, 'display')} alt={fileName(item.path)} onDragStart={dragImage(item.id)} onLoad={loadAhead} onError={fail} />}
      </div>
      <aside className="image-details">
        <div className="detail-summary">
          <h1 title={fileName(item.path)}>{fileName(item.path)}</h1>
          <p>{item.dated === 'taken' ? 'Taken' : 'Modified'} {dateLabel(item.date, true)}</p>
          <button className="crumbs" title={`${folder || rootName}. Show only this folder`} onClick={() => onFolder(folder)}>{crumbs}</button>
          <p className="numbers">{item.width.toLocaleString()} × {item.height.toLocaleString()}{item.duration ? ` · ${durationLabel(item.duration)}` : ''} · {sizeLabel(item.size)} · {typeLabel(item.mime)}</p>
          {details?.preview && <p>Shown as a converted preview. Download for the original {typeLabel(item.mime)}.</p>}
        </div>
        <div className="detail-actions">
          {onSimilar && <button className="text-button" onClick={() => onSimilar(item.id)}><ScanSearch />Find similar</button>}
          {!video && <button className="text-button" onClick={copy}>{copied?.id === item.id ? <Check /> : <Copy />}Copy image</button>}
          <a className="text-button" href={downloadUrl(item.id, item.path)} download><Download />Download original</a>
          <button className="text-button" onClick={() => show(item.path)}><RevealIcon />{reveal}</button>
        </div>
        <p className={error || pageError ? 'detail-status error-copy' : 'detail-status'} role="status">{error || pageError || (copied?.id === item.id ? copied.note : '')}</p>
        {members.length > 1 && <section className="near-duplicates" aria-label="Near-duplicates">
          <h2>{plural(members.length, 'near-duplicate')}</h2>
          <ul>{members.map((member, place) => <li key={member.id}><button aria-pressed={place === shown} aria-label={`Show ${fileName(member.path)}`} onClick={() => showMember(place)}><img src={imageUrl(member.id)} alt="" decoding="async" onDragStart={dragImage(member.id)} /></button></li>)}</ul>
        </section>}
        {details && <Disclosure summary="Details">
          <p className="path">{photos ? `In your ${details.root} library` : `${details.root}/${item.path}`}</p>
          {otherDate && <p>{otherDate}</p>}
          {details.camera && <p>{details.camera}</p>}
          {!!others.length && <><p>Also saved in {plural(others.length, 'other place')}</p><ul className="file-list">{others.map(other => <li key={other.path}><span className="path">{photos ? fileName(other.path) : other.path}</span><button className="icon-button" aria-label={`${reveal}: ${photos ? fileName(other.path) : other.path}`} title={reveal} onClick={() => show(other.path)}><RevealIcon /></button></li>)}</ul></>}
        </Disclosure>}
      </aside>
    </div>
  </dialog>;
}

/** The image as a PNG, the one format every browser can put on the clipboard, scaled down only past what a canvas holds. */
async function toPng(url: string) {
  const response = await fetch(url);
  if (!response.ok) throw new Error('Unavailable');
  const bitmap = await createImageBitmap(await response.blob());
  const scale = Math.min(1, Math.sqrt(CLIPBOARD_PIXELS / (bitmap.width * bitmap.height)));
  const width = Math.round(bitmap.width * scale), height = Math.round(bitmap.height * scale);
  const canvas = new OffscreenCanvas(width, height);
  canvas.getContext('2d')!.drawImage(bitmap, 0, 0, width, height);
  bitmap.close();
  return { blob: await canvas.convertToBlob({ type: 'image/png' }), width, height, scaled: scale < 1 };
}
