import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, X, Download, ScanSearch, FolderOpen, Folder } from 'lucide-react';
import type { Details, Filters, Picture, Results } from './types';
import { dateLabel, downloadUrl, fileName, filterParams, folderOf, imageUrl, plural, post, request, sizeLabel, typeLabel } from './types';

interface Props {
  items: Picture[]; index: number; total: number; hasMore: boolean; loadingMore: boolean; pageError: string; rootName: string; platform: string; filters: Filters;
  onChange: (index: number) => void; onClose: () => void; onSimilar: (id: string) => void; onFolder: (folder: string) => void;
}

export default function Viewer({ items, index, total, hasMore, loadingMore, pageError, rootName, platform, filters, onChange, onClose, onSimilar, onFolder }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [details, setDetails] = useState<Details | null>(null);
  const [error, setError] = useState('');
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(false);
  // The grid shows one image per group of near-duplicates; the viewer can show any of them.
  const [members, setMembers] = useState<Picture[]>([]);
  const [shown, setShown] = useState(0);
  const front = items[index];
  const item = members[shown] ?? front;
  const folder = folderOf(item.path);
  const reveal = platform === 'darwin' ? 'Show in Finder' : 'Show in folder';
  useEffect(() => {
    const node = dialog.current!;
    const focus = document.activeElement as HTMLElement;
    node.showModal();
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
  const file = details?.files.find(f => f.path === item.path);
  const others = details?.files.filter(f => f.path !== item.path) ?? [];
  return <dialog ref={dialog} className="viewer" aria-label="Image viewer" onCancel={onClose} onKeyDown={e => {
    if (e.key === 'ArrowRight' && (index < items.length - 1 || hasMore) && !loadingMore) { e.preventDefault(); onChange(index + 1); }
    if (e.key === 'ArrowLeft' && index > 0 && !loadingMore) { e.preventDefault(); onChange(index - 1); }
    if (e.key === 'ArrowDown' && shown < members.length - 1) { e.preventDefault(); setShown(shown + 1); }
    if (e.key === 'ArrowUp' && shown > 0) { e.preventDefault(); setShown(shown - 1); }
  }}>
    <div className="viewer-layout">
      <header className="viewer-top"><div className="viewer-navigation">
        <button className="icon-button" aria-label="Previous image" disabled={index === 0 || loadingMore} onClick={() => onChange(index - 1)}><ArrowLeft /></button>
        <span>{index + 1} / {total}</span>
        <button className="icon-button" aria-label="Next image" disabled={loadingMore || (index === items.length - 1 && !hasMore)} onClick={() => onChange(index + 1)}><ArrowRight /></button>
      </div><button className="icon-button" autoFocus aria-label="Close image" onClick={onClose}><X /></button></header>
      <div className={`image-stage ${zoom ? 'zoomed' : ''}`}>
        {failed ? <div className="empty"><p>This image could not be shown. The file may have moved or changed.</p><button className="text-button" onClick={() => setFailed(false)}>Retry</button></div> : <img key={item.id} src={imageUrl(item.id, 'display')} alt={fileName(item.path)} onError={() => setFailed(true)} onClick={() => setZoom(!zoom)} />}
      </div>
      <aside className="image-details">
        <h1>{fileName(item.path)}</h1>
        <p>{item.dated === 'taken' ? 'Taken' : 'Modified'} {dateLabel(item.date, true)}</p>
        <button className="text-button folder-link" title="Show only this folder" onClick={() => onFolder(folder)}><Folder /><span>{folder || rootName}</span></button>
        <p className="numbers">{item.width.toLocaleString()} × {item.height.toLocaleString()} · {sizeLabel(item.size)} · {typeLabel(item.mime)}</p>
        {details?.camera && <p>{details.camera}</p>}
        {details?.preview && <p>Shown as a converted preview. Download for the original {typeLabel(item.mime)}.</p>}
        {(error || pageError) && <p className="error-copy" role="alert">{error || pageError}</p>}
        <div className="detail-actions">
          <a className="text-button" href={downloadUrl(item.id, item.path)} download><Download />Download original</a>
          <button className="text-button" onClick={() => show(item.path)}><FolderOpen />{reveal}</button>
          <button className="text-button" onClick={() => onSimilar(item.id)}><ScanSearch />Find similar</button>
          <button className="text-button" onClick={() => setZoom(!zoom)}>{zoom ? 'Fit to screen' : 'View actual size'}</button>
        </div>
        {members.length > 1 && <section className="near-duplicates" aria-label="Near-duplicates">
          <h2>{plural(members.length, 'near-duplicate')}</h2>
          <ul>{members.map((member, place) => <li key={member.id}><button aria-pressed={place === shown} aria-label={`Show ${fileName(member.path)}`} title={member.path} onClick={() => setShown(place)}><img src={imageUrl(member.id)} alt="" decoding="async" /></button></li>)}</ul>
        </section>}
        {details && <details className="disclosure"><summary>File</summary>
          <p className="path">{details.root}/{item.path}</p>
          {file && <p>Modified {dateLabel(file.modified, true)}</p>}
          {details.taken && <p>Taken {dateLabel(details.taken, true)}</p>}
        </details>}
        {!!others.length && <details className="disclosure"><summary>Also saved in {plural(others.length, 'other place')}</summary><ul className="file-list">{others.map(other => <li key={other.path}><span className="path">{other.path}</span><button className="text-button" onClick={() => show(other.path)}>{reveal}</button></li>)}</ul></details>}
      </aside>
    </div>
  </dialog>;
}
