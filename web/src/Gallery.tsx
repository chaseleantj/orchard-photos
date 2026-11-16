import { memo, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { Layers, Play } from 'lucide-react';
import type { Picture } from './types';
import { dragImage, durationLabel, fileName, imageUrl, isVideo, monthLabel, plural, slowMotion } from './types';
import { aheadUrl, imagesAhead } from './preload';

const BUFFER = 1200;
const STEP = 400;
// Rows are filled to the full width at about this height; a month's last row keeps it rather than stretching.
const ROW = 220;
// A month heading's height, and the space above and below it. The first heading has no space above.
const HEADING = 21;
const ABOVE = 40;
const BELOW = 12;
// A pointer that rests on a tile this long, or presses it, loads its image for the viewer before the click.
const PREPARE_DELAY = 100;
type Position = { left: number; top: number; width: number; height: number };

/** The tile an arrow key moves to from `from`: the one before or after, or the nearest in the row above or below. */
function neighbour(positions: Position[], from: number, key: string) {
  if (key === 'ArrowLeft') return from > 0 ? from - 1 : null;
  if (key === 'ArrowRight') return from < positions.length - 1 ? from + 1 : null;
  if (key !== 'ArrowUp' && key !== 'ArrowDown') return null;
  const way = key === 'ArrowDown' ? 1 : -1;
  const here = positions[from], middle = here.left + here.width / 2;
  // Every tile in a row shares its top, so the next row starts at the first tile with another.
  let at = from;
  while (positions[at]?.top === here.top) at += way;
  const row = positions[at]?.top;
  if (row === undefined) return null;
  let best = at;
  for (let place = at; positions[place]?.top === row; place += way)
    if (Math.abs(positions[place].left + positions[place].width / 2 - middle) < Math.abs(positions[best].left + positions[best].width / 2 - middle)) best = place;
  return best;
}

/** The index of the first tile whose row reaches below `y`, in gallery coordinates. Rows only move down the list, so
 *  it is found by halving. */
function firstReaching(positions: Position[], y: number) {
  let low = 0, high = positions.length - 1;
  while (low < high) { const middle = (low + high) >> 1; if (positions[middle].top + positions[middle].height < y) low = middle + 1; else high = middle; }
  return low;
}

/** Where things are in the grid, for the timeline. Offsets are in page coordinates. */
export interface GalleryHandle {
  /** The index of the first image whose row reaches below `y`. */
  indexAt: (y: number) => number;
  /** Where the image's row starts, or its month's heading if it is the month's first image. */
  offsetOf: (index: number) => number;
  /** Where the first row of images starts, below any heading. */
  firstRow: () => number;
  /** Lays the grid out at once for the width it has just been given, while that width is still being animated toward
   *  it, and moves each tile and heading from where it is to its new place in the same motion, until `settled`. */
  glide: (settled: Promise<unknown>) => void;
}
const BOX = ['left', 'top', 'width', 'height'] as const;

/** The images in justified rows, each at its own shape. With `sections`, for date order, each month starts under its own heading. */
export default function Gallery({ items, sections, onOpen, ref }: { items: Picture[]; sections: boolean; onOpen: (index: number) => void; ref?: React.Ref<GalleryHandle> }) {
  const container = useRef<HTMLDivElement>(null);
  const [measured, setMeasured] = useState(0);
  // While the grid's width is animated, its layout holds the width it is heading for, so rows break once rather than
  // on every frame, which would shuffle the images between rows as the width passes through each break.
  const [pinned, setPinned] = useState<number | null>(null);
  const width = pinned ?? measured;
  // Visible band in gallery coordinates, snapped to STEP so scrolling re-renders only when it crosses a step.
  const [band, setBand] = useState<[number, number]>([0, 0]);
  // The one tile Tab stops at; the arrow keys move it across the grid.
  const [current, setCurrent] = useState(0);
  // Only the last tile pointed at keeps its image loaded.
  const [pointed] = useState(imagesAhead);
  const prepare = useCallback((item: Picture) => pointed.keep([aheadUrl(item)]), [pointed]);
  // The first row in view, and how far its top sits above the window's, at the width it was laid out for. When the
  // width changes, as when the folders sidebar opens or the window is resized, that row stays where it was.
  const anchor = useRef<{ index: number; offset: number; width: number } | null>(null);
  useLayoutEffect(() => {
    const element = container.current!;
    const observer = new ResizeObserver(entries => setMeasured(entries[0].contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let frame = 0;
    const measure = () => {
      frame = 0;
      const top = -container.current!.getBoundingClientRect().top;
      const { positions, width } = layout.current;
      const index = firstReaching(positions, top);
      anchor.current = top > 0 && positions[index] ? { index, offset: positions[index].top - top, width } : null;
      const start = Math.floor((top - BUFFER) / STEP) * STEP;
      const end = Math.ceil((top + innerHeight + BUFFER) / STEP) * STEP;
      setBand(old => old[0] === start && old[1] === end ? old : [start, end]);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(measure); };
    measure();
    addEventListener('scroll', schedule, { passive: true });
    addEventListener('resize', schedule);
    return () => { removeEventListener('scroll', schedule); removeEventListener('resize', schedule); cancelAnimationFrame(frame); };
  }, []);
  // Matches --gap in styles.css, which the loading skeleton uses.
  const gap = width < 560 ? 4 : 8;
  const target = width < 560 ? ROW * .55 : width < 900 ? ROW * .8 : ROW;
  const { positions, headings, height } = useMemo(() => {
    const positions: React.CSSProperties[] = [];
    const headings: { label: string; top: number; first: number }[] = [];
    let top = 0;
    let row: { index: number; ratio: number }[] = [];
    // The height at which these tiles exactly fill the width.
    const fill = (tiles: typeof row) => (width - gap * (tiles.length - 1)) / tiles.reduce((sum, tile) => sum + tile.ratio, 0);
    // Lays out the pending row: scaled to fill the width, or at the target height if it is the last of its run.
    const flush = (last: boolean) => {
      if (!row.length) return;
      const tall = Math.min(last ? target : Infinity, fill(row));
      let x = 0;
      row.forEach(({ index, ratio }, place) => {
        const left = Math.round(x);
        x += ratio * tall;
        const full = !last || tall < target;
        positions[index] = { left, top, height: tall, width: (place === row.length - 1 && full ? width : Math.round(x)) - left };
        x += gap;
      });
      top += tall + gap;
      row = [];
    };
    items.forEach((item, index) => {
      const month = sections ? monthLabel(new Date(item.date)) : '';
      if (sections && month !== headings.at(-1)?.label) {
        flush(true);
        const at = headings.length ? top - gap + ABOVE : 0;
        headings.push({ label: month, top: at, first: index });
        top = at + HEADING + BELOW;
      }
      // Panoramas and slivers are cropped toward a readable shape.
      const tile = { index, ratio: Math.min(3, Math.max(.5, item.width / item.height || 1)) };
      // The row breaks before or after this tile, whichever leaves its height closer to the target.
      const before = fill(row), after = fill([...row, tile]);
      if (after > target) row.push(tile);
      else if (row.length && Math.abs(before - target) < Math.abs(after - target)) { flush(false); row.push(tile); }
      else { row.push(tile); flush(false); }
    });
    flush(true);
    return { positions: positions as Position[], headings, height: Math.max(0, top - gap) };
  }, [items, sections, width, gap, target]);
  const layout = useRef({ positions, headings, width });
  layout.current = { positions, headings, width };
  useLayoutEffect(() => {
    const held = anchor.current;
    if (!held || held.width === width || !positions[held.index]) return;
    held.width = width;
    scrollTo({ top: container.current!.getBoundingClientRect().top + scrollY + positions[held.index].top - held.offset });
  }, [positions, width]);
  useImperativeHandle(ref, () => ({
    indexAt: y => {
      const { positions } = layout.current;
      return Math.max(0, firstReaching(positions, y - (container.current!.getBoundingClientRect().top + scrollY)));
    },
    offsetOf: index => {
      const { positions, headings } = layout.current;
      const heading = headings.find(h => h.first === index);
      return container.current!.getBoundingClientRect().top + scrollY + (heading ? heading.top : positions[Math.min(index, positions.length - 1)]?.top ?? 0);
    },
    firstRow: () => container.current!.getBoundingClientRect().top + scrollY + (layout.current.positions[0]?.top ?? 0),
    glide: settled => {
      const motion = slowMotion();
      const element = container.current!;
      if (!motion) return;
      // Where each drawn tile and heading is now, mid-motion included, and the scroll, which keeping the first row in
      // view may change.
      const moving = [...element.querySelectorAll<HTMLElement>('.picture, .month')];
      const from = new Map(moving.map(node => { const style = getComputedStyle(node); return [node.dataset.key!, BOX.map(side => parseFloat(style[side]))]; }));
      moving.forEach(node => node.getAnimations().forEach(animation => animation.cancel()));
      const scroll = scrollY;
      flushSync(() => setPinned(element.getBoundingClientRect().width));
      const shift = scrollY - scroll;
      for (const node of element.querySelectorAll<HTMLElement>('.picture, .month')) {
        const start = from.get(node.dataset.key!);
        if (!start) continue;
        const style = getComputedStyle(node);
        const end = BOX.map(side => parseFloat(style[side]));
        start[1] += shift;
        if (start.every((value, side) => Math.abs(value - end[side]) < .5)) continue;
        node.animate([Object.fromEntries(BOX.map((side, at) => [side, `${start[at]}px`])), Object.fromEntries(BOX.map((side, at) => [side, `${end[at]}px`]))], motion);
      }
      // Settled, the width is measured afresh, since the observer may not have seen the animation's last frame yet.
      void settled.then(() => { setMeasured(element.getBoundingClientRect().width); setPinned(null); });
    },
  }), []);
  const drawn = (index: number) => width > 0 && !!positions[index] && positions[index].top + positions[index].height >= band[0] && positions[index].top <= band[1];
  const stop = Math.min(current, items.length - 1);
  const move = (e: React.KeyboardEvent) => {
    if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey || !(e.target as HTMLElement).classList.contains('picture')) return;
    const to = neighbour(positions, stop, e.key);
    const tile = to === null ? null : container.current!.querySelector<HTMLElement>(`[data-index="${to}"]`);
    if (!tile) return;
    e.preventDefault();
    tile.focus({ preventScroll: true });
    tile.scrollIntoView({ block: 'nearest' });
  };
  // While the tab stop is scrolled out of the drawn band, the grid itself takes Tab and hands it to the first tile
  // below the header.
  const enter = (e: React.FocusEvent) => {
    if (e.target !== e.currentTarget) return;
    const tiles = [...container.current!.querySelectorAll<HTMLElement>('.picture')];
    const first = tiles.find(tile => tile.getBoundingClientRect().bottom > parseFloat(getComputedStyle(tile).scrollMarginTop)) ?? tiles[0];
    first?.focus({ preventScroll: true });
  };
  return <div className="gallery" ref={container} style={{ height }} aria-label="Images" tabIndex={drawn(stop) ? undefined : 0} onFocus={enter} onKeyDown={move}>
    {width > 0 && headings.map(({ label, top }) => top + HEADING >= band[0] && top <= band[1] ? <h2 key={label} className="month" data-key={label} style={{ top }}>{label}</h2> : null)}
    {items.map((item, index) => drawn(index) ? <Tile key={item.id} item={item} index={index} style={positions[index]} stop={index === stop} onOpen={onOpen} onFocus={setCurrent} onPrepare={prepare} /> : null)}
  </div>;
}
interface TileProps { item: Picture; index: number; style: React.CSSProperties; stop: boolean; onOpen: (index: number) => void; onFocus: (index: number) => void; onPrepare: (item: Picture) => void }
const Tile = memo(function Tile({ item, index, style, stop, onOpen, onFocus, onPrepare }: TileProps) {
  const [failed, setFailed] = useState(false);
  const resting = useRef(0);
  // An image that loads after its tile is drawn fades in. One the page already holds, as when scrolling back to it,
  // is simply there.
  const image = useRef<HTMLImageElement>(null);
  const awaited = useRef(false);
  const [arrived, setArrived] = useState(false);
  useLayoutEffect(() => { awaited.current = !image.current!.complete; }, []);
  const name = fileName(item.path);
  const label = item.members > 1 ? `Open ${name} and ${plural(item.members - 1, 'near-duplicate')}` : `Open ${name}`;
  // Only a pointer that moves readies the image, so a tile drawn under a still one, as when the viewer closes onto new
  // results, loads nothing.
  return <button className="picture" style={style} data-index={index} data-key={item.id} tabIndex={stop ? 0 : -1} onClick={() => onOpen(index)} onFocus={() => onFocus(index)} aria-label={label}
    onPointerMove={() => { resting.current ||= window.setTimeout(() => onPrepare(item), PREPARE_DELAY); }}
    onPointerLeave={() => { clearTimeout(resting.current); resting.current = 0; }}
    onPointerDown={() => onPrepare(item)}>
    {failed ? <span className="missing">Preview unavailable</span> : <img ref={image} className={arrived ? 'arrived' : undefined} src={imageUrl(item.id)} alt={name} decoding="async" onDragStart={dragImage(item.id)} onLoad={() => setArrived(awaited.current)} onError={() => setFailed(true)} />}
    {isVideo(item) && <span className="duration" aria-hidden="true"><Play />{item.duration ? durationLabel(item.duration) : null}</span>}
    {item.members > 1 && <span className="members" aria-hidden="true"><Layers />{item.members.toLocaleString()}</span>}
  </button>;
});
