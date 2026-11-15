import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import type { Facets } from './types';
import { fileName, folderOf, request } from './types';

interface Folder { path: string; count: number; children: Folder[] }
interface Row { folder: Folder; level: number }
const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

/** The open folder, the path '', with its subfolders as a tree, each folder's in name order. */
function tree(folders: Facets['folders']) {
  const nodes = new Map(folders.map(({ path, count }) => [path, { path, count, children: [] as Folder[] }]));
  for (const node of nodes.values()) if (node.path) nodes.get(folderOf(node.path))?.children.push(node);
  for (const node of nodes.values()) node.children.sort((a, b) => collator.compare(fileName(a.path), fileName(b.path)));
  return nodes.get('') ?? null;
}
const ancestors = (path: string) => { const above: string[] = []; for (let at = folderOf(path); at; at = folderOf(at)) above.push(at); return above; };

/** The folders sidebar: every image at the top, then the subfolders as a tree, each with how many tiles the grid shows
 *  for it. `folder` is the folder filter, which this only reads and sets through `onChoose`. `revision` refetches the
 *  counts when a scan changes them. `shown` hides it from focus and assistive technology while it is collapsed. */
export default function Folders({ root, revision, folder, noun, shown, onChoose }: { root: string; revision: number; folder: string; noun: string; shown: boolean; onChoose: (folder: string) => void }) {
  const [facets, setFacets] = useState<{ root: string; folders: Facets['folders'] } | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    request<Facets>('/api/facets', { signal: controller.signal })
      .then(data => { setFacets({ root, folders: data.folders }); setError(''); })
      .catch(e => { if (e.name !== 'AbortError') setError((e as Error).message); });
    return () => controller.abort();
  }, [root, revision]);
  // Another folder's counts are never shown under this one's name.
  const top = useMemo(() => facets && facets.root === root ? tree(facets.folders) : null, [facets, root]);
  // The folders whose subfolders are listed. The chosen folder's own folders open whenever it changes, so it is in view.
  const [open, setOpen] = useState(() => new Set(ancestors(folder)));
  const [opened, setOpened] = useState(folder);
  if (opened !== folder) { setOpened(folder); setOpen(old => new Set([...old, ...ancestors(folder)])); }
  const rows = useMemo(() => {
    const rows: Row[] = [];
    if (!top) return rows;
    // Every image heads the list, level with the folders it holds rather than above them.
    rows.push({ folder: { ...top, children: [] }, level: 1 });
    const walk = (node: Folder, level: number) => { rows.push({ folder: node, level }); if (open.has(node.path)) node.children.forEach(child => walk(child, level + 1)); };
    top.children.forEach(child => walk(child, 1));
    return rows;
  }, [top, open]);
  // The one row Tab stops at; the arrow keys move it. It follows the chosen folder, and falls back to it, then to every
  // image, when its own row is closed away.
  const [current, setCurrent] = useState(folder);
  const stop = rows.find(row => row.folder.path === current) ? current : rows.find(row => row.folder.path === folder) ? folder : '';
  const list = useRef<HTMLDivElement>(null);
  const element = (place: number) => list.current?.querySelectorAll<HTMLElement>('[role="treeitem"]')[place];
  // The chosen folder scrolls into view in a long list.
  const listed = !!top;
  useEffect(() => { element(rows.findIndex(row => row.folder.path === folder))?.scrollIntoView({ block: 'nearest' }); }, [folder, listed]); // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (path: string, to = !open.has(path)) => setOpen(old => { const next = new Set(old); if (to) next.add(path); else next.delete(path); return next; });
  const choose = (node: Folder) => { if (node.children.length) toggle(node.path, true); setCurrent(node.path); onChoose(node.path); };
  // Arrow keys move through the rows, and open or close a folder, or step to its first subfolder or the folder it is
  // in, as file trees do; Enter or Space shows the folder.
  const move = (e: React.KeyboardEvent) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const place = rows.findIndex(row => row.folder.path === stop);
    if (place < 0) return;
    const { folder: node, level } = rows[place];
    let parent = place - 1;
    while (parent >= 0 && rows[parent].level >= level) parent--;
    const to = {
      ArrowDown: place + 1, ArrowUp: place - 1, Home: 0, End: rows.length - 1,
      ArrowRight: node.children.length && open.has(node.path) ? place + 1 : place,
      ArrowLeft: node.children.length && open.has(node.path) ? place : parent,
    }[e.key];
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(node); return; }
    if (to === undefined) return;
    e.preventDefault();
    if (e.key === 'ArrowRight' && node.children.length && !open.has(node.path)) toggle(node.path, true);
    if (e.key === 'ArrowLeft' && node.children.length && open.has(node.path)) toggle(node.path, false);
    if (to < 0 || to >= rows.length || to === place) return;
    setCurrent(rows[to].folder.path);
    element(to)?.focus();
  };
  return <nav id="folders" className="sidebar" aria-label="Folders" inert={!shown}>
    {top && <div ref={list} className="folders" role="tree" aria-label="Folders" onKeyDown={move}>
      {rows.map(({ folder: node, level }) => {
        const name = node.path ? fileName(node.path) : `All ${noun}s`;
        return <div key={node.path || '/'} role="treeitem" className="folder" aria-level={level} aria-selected={node.path === folder} aria-expanded={node.children.length ? open.has(node.path) : undefined} tabIndex={node.path === stop ? 0 : -1}
          title={node.path ? `${node.path}, ${node.count.toLocaleString()}` : undefined} style={{ '--level': level - 1 } as React.CSSProperties} onClick={() => choose(node)} onFocus={() => setCurrent(node.path)}>
          {/* Opens or closes the folder without showing it, as its row's arrow keys do. */}
          <span className="folder-toggle" aria-hidden="true" onClick={e => { if (!node.children.length) return; e.stopPropagation(); toggle(node.path); }}>{node.children.length > 0 && <ChevronRight />}</span>
          <span className="folder-name">{name}</span>
          <span className="folder-count">{node.count.toLocaleString()}</span>
        </div>;
      })}
    </div>}
    {top && !top.children.length && <p className="folders-note">This folder has no subfolders with {noun}s.</p>}
    {error && <p className="folders-note error-copy" role="alert">{error}</p>}
  </nav>;
}
