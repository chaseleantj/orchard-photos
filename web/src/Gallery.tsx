import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { Picture } from './types';
import { dragImage, fileName, imageUrl } from './types';

const BUFFER = 1200;
const STEP = 400;

export default function Gallery({ items, onOpen }: { items: Picture[]; onOpen: (index: number) => void }) {
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
  const gap = width < 690 ? 12 : width > 1500 ? 32 : 24;
  const columns = width < 560 ? 2 : width < 900 ? 3 : width < 1200 ? 4 : 5;
  const { positions, height } = useMemo(() => {
    const columnWidth = (width - (columns - 1) * gap) / columns;
    const heights = Array(columns).fill(0) as number[];
    const positions = items.map(item => {
      const column = heights.indexOf(Math.min(...heights));
      const tile = columnWidth * Math.min(2, Math.max(.55, item.height / item.width));
      const position = { left: column * (columnWidth + gap), top: heights[column], width: columnWidth, height: tile };
      heights[column] += tile + gap;
      return position;
    });
    return { positions, height: Math.max(...heights, 0) };
  }, [items, width, columns, gap]);
  return <div className="gallery" ref={container} style={{ height }} aria-label="Images">
    {width > 0 && items.map((item, index) => {
      const { top, height: tile } = positions[index];
      return top + tile >= band[0] && top <= band[1] ? <Tile key={item.id} item={item} index={index} style={positions[index]} onOpen={onOpen} /> : null;
    })}
  </div>;
}
const Tile = memo(function Tile({ item, index, style, onOpen }: { item: Picture; index: number; style: React.CSSProperties; onOpen: (index: number) => void }) {
  const [failed, setFailed] = useState(false);
  const name = fileName(item.path);
  return <button className="picture" style={style} onClick={() => onOpen(index)} aria-label={`Open ${name}`} title={item.path}>
    {failed ? <span className="missing">Preview unavailable</span> : <img src={imageUrl(item.id)} alt={name} decoding="async" onDragStart={dragImage(item.id)} onError={() => setFailed(true)} />}
  </button>;
});
