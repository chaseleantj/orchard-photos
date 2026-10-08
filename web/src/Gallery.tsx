import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Layers } from 'lucide-react';
import type { Picture } from './types';
import { dragImage, fileName, imageUrl, plural } from './types';

const BUFFER = 1200;
const STEP = 400;
// Rows are filled to the full width at about this height; a month's last row keeps it rather than stretching.
const ROW = 220;
// A month heading's height, and the space above and below it. The first heading has no space above.
const HEADING = 29;
const ABOVE = 40;
const BELOW = 12;
const monthOf = (date: string) => new Date(date).toLocaleString(undefined, { month: 'long', year: 'numeric' });

/** The images in justified rows, in order, each at its own shape. With `sections`, for date order, each month starts under its own heading. */
export default function Gallery({ items, sections, onOpen }: { items: Picture[]; sections: boolean; onOpen: (index: number) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  // Visible band in gallery coordinates, snapped to STEP so scrolling re-renders only when it crosses a step.
  const [band, setBand] = useState<[number, number]>([0, 0]);
  useLayoutEffect(() => {
    const element = container.current!;
    const observer = new ResizeObserver(entries => setWidth(entries[0].contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let frame = 0;
    const measure = () => {
      frame = 0;
      const top = -container.current!.getBoundingClientRect().top;
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
    const headings: { label: string; top: number }[] = [];
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
      const month = sections ? monthOf(item.date) : '';
      if (sections && month !== headings.at(-1)?.label) {
        flush(true);
        const at = headings.length ? top - gap + ABOVE : 0;
        headings.push({ label: month, top: at });
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
    return { positions, headings, height: Math.max(0, top - gap) };
  }, [items, sections, width, gap, target]);
  return <div className="gallery" ref={container} style={{ height }} aria-label="Images">
    {width > 0 && headings.map(({ label, top }) => top + HEADING >= band[0] && top <= band[1] ? <h2 key={top} className="month" style={{ top }}>{label}</h2> : null)}
    {width > 0 && items.map((item, index) => {
      const { top, height: tile } = positions[index] as { top: number; height: number };
      return top + tile >= band[0] && top <= band[1] ? <Tile key={item.id} item={item} index={index} style={positions[index]} onOpen={onOpen} /> : null;
    })}
  </div>;
}
const Tile = memo(function Tile({ item, index, style, onOpen }: { item: Picture; index: number; style: React.CSSProperties; onOpen: (index: number) => void }) {
  const [failed, setFailed] = useState(false);
  const name = fileName(item.path);
  const label = item.members > 1 ? `Open ${name} and ${plural(item.members - 1, 'near-duplicate')}` : `Open ${name}`;
  return <button className="picture" style={style} onClick={() => onOpen(index)} aria-label={label} title={item.path}>
    {failed ? <span className="missing">Preview unavailable</span> : <img src={imageUrl(item.id)} alt={name} decoding="async" onDragStart={dragImage(item.id)} onError={() => setFailed(true)} />}
    {item.members > 1 && <span className="members" aria-hidden="true"><Layers />{item.members.toLocaleString()}</span>}
  </button>;
});
