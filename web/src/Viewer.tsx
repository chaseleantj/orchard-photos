import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, Copy, Download, FolderOpen, Images, ScanSearch, X, ZoomIn, ZoomOut } from 'lucide-react';
import type { Details, Filters, Picture, Results } from './types';
import { Disclosure } from './Panels';
import { dateLabel, downloadUrl, fileName, filterParams, folderOf, imageUrl, plural, post, request, sizeLabel, typeLabel } from './types';

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

export default function Viewer({ items, index, total, hasMore, loadingMore, pageError, rootName, platform, filters, photos, onChange, onClose, onSimilar, onFolder }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [details, setDetails] = useState<Details | null>(null);
  const [error, setError] = useState('');
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(false);
  const [copied, setCopied] = useState<{ id: string; note: string } | null>(null);
  // The grid shows one image per group of near-duplicates; the viewer can show any of them.
  const [members, setMembers] = useState<Picture[]>([]);
  const [shown, setShown] = useState(0);
  const front = items[index];
  const item = members[shown] ?? front;
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
    return () => { node.close(); document.body.style.overflow = previous; focus?.focus(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setZoom(false); setFailed(false); setError(''); setDetails(null);
    request<Details>(`/api/images/${item.id}`, { signal: controller.signal }).then(setDetails).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    if (items[index + 1]) { const next = new Image(); next.src = imageUrl(items[index + 1].id, 'display'); }
    return () => controller.abort();
  }, [item.id, index, items]);
  useEffect(() => {
    setMembers([]); setShown(0);
    if (front.members < 2) return;
    const controller = new AbortController();
    request<Results>(`/api/images?${new URLSearchParams({ ...filterParams(filters), group: front.group })}`, { signal: controller.signal })
      .then(data => { setMembers(data.items); setShown(Math.max(0, data.items.findIndex(member => member.id === front.id))); })
      .catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => controller.abort();
  }, [front.id, front.group, front.members, filters]);
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
  const file = details?.files.find(f => f.path === item.path);
  const others = details?.files.filter(f => f.path !== item.path) ?? [];
  // The date not already shown under the name.
  const otherDate = item.dated === 'taken' ? file && `Modified ${dateLabel(file.modified, true)}` : details?.taken && `Taken ${dateLabel(details.taken, true)}`;
  const parts = folder ? folder.split('/') : [rootName];
  const crumbs = (parts.length > CRUMBS ? ['…', ...parts.slice(-CRUMBS)] : parts).join(' › ');
  return <dialog ref={dialog} tabIndex={-1} className="viewer" aria-label="Image viewer" onCancel={onClose} onKeyDown={e => {
    if (e.key === 'ArrowRight' && (index < items.length - 1 || hasMore) && !loadingMore) { e.preventDefault(); onChange(index + 1); }
    if (e.key === 'ArrowLeft' && index > 0 && !loadingMore) { e.preventDefault(); onChange(index - 1); }
    if (e.key === 'ArrowDown' && shown < members.length - 1) { e.preventDefault(); setShown(shown + 1); }
    if (e.key === 'ArrowUp' && shown > 0) { e.preventDefault(); setShown(shown - 1); }
    if ((e.metaKey || e.ctrlKey) && e.key === 'c' && !getSelection()?.toString()) { e.preventDefault(); void copy(); }
  }}>
    <div className="viewer-layout">
      <header className="viewer-top"><div className="viewer-navigation">
        <button className="icon-button" aria-label="Previous image" title="Previous image" disabled={index === 0 || loadingMore} onClick={() => onChange(index - 1)}><ArrowLeft /></button>
        <span>{(index + 1).toLocaleString()} / {total.toLocaleString()}</span>
        <button className="icon-button" aria-label="Next image" title="Next image" disabled={loadingMore || (index === items.length - 1 && !hasMore)} onClick={() => onChange(index + 1)}><ArrowRight /></button>
      </div><div className="viewer-navigation">
        <button className="icon-button" aria-label={zoom ? 'Fit to screen' : 'View actual size'} title={zoom ? 'Fit to screen' : 'Actual size'} onClick={() => setZoom(!zoom)}>{zoom ? <ZoomOut /> : <ZoomIn />}</button>
        <button className="icon-button" aria-label="Close image" title="Close" onClick={onClose}><X /></button>
      </div></header>
      <div className={`image-stage ${zoom ? 'zoomed' : ''}`}>
        {failed ? <div className="empty"><p>This image could not be shown. The file may have moved or changed.</p><button className="text-button secondary" onClick={() => setFailed(false)}>Retry</button></div> : <img key={item.id} src={imageUrl(item.id, 'display')} alt={fileName(item.path)} onError={() => setFailed(true)} onClick={() => setZoom(!zoom)} />}
      </div>
      <aside className="image-details">
        <div className="detail-summary">
          <h1 title={fileName(item.path)}>{fileName(item.path)}</h1>
          <p>{item.dated === 'taken' ? 'Taken' : 'Modified'} {dateLabel(item.date, true)}</p>
          <button className="crumbs" title={`${folder || rootName}. Show only this folder`} onClick={() => onFolder(folder)}>{crumbs}</button>
          <p className="numbers">{item.width.toLocaleString()} × {item.height.toLocaleString()} · {sizeLabel(item.size)} · {typeLabel(item.mime)}</p>
          {details?.preview && <p>Shown as a converted preview. Download for the original {typeLabel(item.mime)}.</p>}
        </div>
        <div className="detail-actions">
          {onSimilar && <button className="text-button" onClick={() => onSimilar(item.id)}><ScanSearch />Find similar</button>}
          <button className="text-button" onClick={copy}>{copied?.id === item.id ? <Check /> : <Copy />}Copy image</button>
          <a className="text-button" href={downloadUrl(item.id, item.path)} download><Download />Download original</a>
          <button className="text-button" onClick={() => show(item.path)}><RevealIcon />{reveal}</button>
        </div>
        <p className={error || pageError ? 'detail-status error-copy' : 'detail-status'} role="status">{error || pageError || (copied?.id === item.id ? copied.note : '')}</p>
        {members.length > 1 && <section className="near-duplicates" aria-label="Near-duplicates">
          <h2>{plural(members.length, 'near-duplicate')}</h2>
          <ul>{members.map((member, place) => <li key={member.id}><button aria-pressed={place === shown} aria-label={`Show ${fileName(member.path)}`} title={member.path} onClick={() => setShown(place)}><img src={imageUrl(member.id)} alt="" decoding="async" /></button></li>)}</ul>
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
