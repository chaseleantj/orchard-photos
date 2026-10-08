import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { GalleryHandle } from './Gallery';
import type { Timeline as Data } from './types';
import { monthLabel, monthStart } from './types';

// How long the month stays beside the marker once scrolling stops.
const LINGER = 900;
// The room a year label takes. A year with less room than this between its neighbours goes unlabelled.
const LABEL = 24;
// Space kept between the header and the row a jump lands on.
const LANDING = 16;
// Pointer travel that turns a press into a drag, so a slightly unsteady click still lands on its year.
const DRAG = 4;

interface Props {
  data: Data;
  /** How many images the grid has loaded; a jump past them waits for `onReach`. */
  loaded: number;
  gallery: React.RefObject<GalleryHandle | null>;
  header: React.RefObject<HTMLElement | null>;
  onReach: (index: number) => Promise<unknown>;
}

/** The whole library as a column of years beside the grid. Each month takes room in proportion to its images, so
 *  the column lines up with scrolling. It marks where the grid is, names the month under the pointer, and jumps
 *  there on a click, a drag or the arrow keys. */
export default function Timeline({ data, loaded, gallery, header, onReach }: Props) {
  const rail = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState(0);
  const [height, setHeight] = useState(0);
  const [current, setCurrent] = useState(0);
  const [hover, setHover] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [scrolling, setScrolling] = useState(false);
  const [focused, setFocused] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const { months, total } = data;
  const starts = useMemo(() => { let n = 0; return months.map(month => { const start = n; n += month.count; return start; }); }, [months]);
  const monthOf = (index: number) => {
    let low = 0, high = starts.length - 1;
    while (low < high) { const middle = (low + high + 1) >> 1; if (starts[middle] <= index) low = middle; else high = middle - 1; }
    return low;
  };
  // Positions run between the centres of the first and last label, so the marker at either end sits on a year.
  const span = Math.max(1, height - LABEL);
  const yOf = (index: number) => LABEL / 2 + index / total * span;
  const indexAt = (y: number) => Math.max(0, Math.min(total - 1, Math.floor((y - LABEL / 2) / span * total)));
  const labelOf = (index: number) => months.length ? monthLabel(monthStart(months[monthOf(index)].month)) : '';
  const currentYear = months[monthOf(current)]?.month.slice(0, 4);
  // Where crowded years compete for room, the newest, the oldest and the current year are named first, then the
  // years with the most images. The rest keep a tick, so a missing label never reads as a missing year.
  const { labels, ticks } = useMemo(() => {
    const all: { year: string; y: number; index: number; count: number }[] = [];
    months.forEach(({ month, count }, place) => {
      const year = month.slice(0, 4);
      if (all.at(-1)?.year === year) all.at(-1)!.count += count;
      else all.push({ year, y: yOf(starts[place]), index: starts[place], count });
    });
    const first = (year: { year: string; count: number }) => year === all[0] || year === all.at(-1) ? 2 : year.year === currentYear ? 1 : 0;
    const order = [...all].sort((a, b) => first(b) - first(a) || b.count - a.count);
    const labels: typeof all = [];
    for (const year of order) if (labels.every(label => Math.abs(label.y - year.y) >= LABEL)) labels.push(year);
    return { labels: labels.sort((a, b) => a.y - b.y), ticks: all.filter(year => !labels.includes(year)) };
  }, [months, starts, total, height, currentYear]); // eslint-disable-line react-hooks/exhaustive-deps
  // A point on the column: inside a label it is that year's start, so hovering a year previews where a click goes.
  const target = (y: number) => {
    const label = labels.find(l => Math.abs(y - l.y) < LABEL / 2);
    return label ? { index: label.index, y: label.y } : { index: indexAt(y), y };
  };

  // The column starts level with the top of the grid and runs to the bottom of the window.
  useLayoutEffect(() => {
    const place = () => setTop(gallery.current?.offsetOf(0) ?? header.current?.getBoundingClientRect().bottom ?? 0);
    place();
    const node = rail.current!;
    const observer = new ResizeObserver(([entry]) => setHeight(entry.contentRect.height));
    observer.observe(node);
    addEventListener('resize', place);
    return () => { observer.disconnect(); removeEventListener('resize', place); };
  }, [gallery, header]);

  // Scrolling moves the marker to the first row under the header, and a long scroll briefly names its month.
  const held = useRef(false);
  held.current = dragging;
  const complete = useRef(false);
  complete.current = loaded >= total;
  const sync = useRef(() => {});
  useEffect(() => {
    let frame = 0, timer = 0;
    const follow = sync.current = () => {
      frame = 0;
      if (held.current || !gallery.current) return;
      // At the foot of the whole library the marker reaches the end, though the top row is a little earlier.
      const foot = complete.current && innerHeight + scrollY >= document.documentElement.scrollHeight - 2;
      setCurrent(foot ? total - 1 : Math.min(total - 1, gallery.current.indexAt(scrollY + (header.current?.getBoundingClientRect().bottom ?? 0))));
    };
    // Only travel of more than a screen names the month; reading down a page leaves the column quiet.
    let from = scrollY;
    const scrolled = () => {
      if (!frame) frame = requestAnimationFrame(follow);
      if (Math.abs(scrollY - from) > innerHeight) setScrolling(true);
      clearTimeout(timer);
      timer = setTimeout(() => { setScrolling(false); from = scrollY; }, LINGER);
    };
    follow();
    addEventListener('scroll', scrolled, { passive: true });
    return () => { removeEventListener('scroll', scrolled); cancelAnimationFrame(frame); clearTimeout(timer); };
  }, [gallery, header, total]);

  // A jump scrolls once the grid holds the target. Past the loaded images it asks for them and lands after they render.
  const pending = useRef<number | null>(null);
  const land = () => {
    const index = pending.current;
    if (index === null || index >= loaded || !gallery.current) return;
    pending.current = null;
    const offset = index === 0 ? 0 : gallery.current.offsetOf(index) - (header.current?.getBoundingClientRect().bottom ?? 0) - LANDING;
    scrollTo({ top: offset, behavior: 'instant' });
  };
  useLayoutEffect(land, [loaded]); // eslint-disable-line react-hooks/exhaustive-deps
  const jump = (index: number) => {
    setCurrent(index);
    pending.current = index;
    if (index < loaded) { land(); return; }
    // Until the pages arrive the month stays named beside the marker. If they never do, the marker returns to the grid.
    setWaiting(true);
    void onReach(index).then(() => requestAnimationFrame(() => {
      if (pending.current === index) { pending.current = null; sync.current(); }
      setWaiting(false);
    }));
  };

  const pointerY = (e: React.PointerEvent) => e.clientY - rail.current!.getBoundingClientRect().top;
  const frame = useRef(0);
  const press = useRef<number | null>(null);
  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    // The pointer never focuses the column, so the page keys keep scrolling the page after a click.
    e.preventDefault();
    rail.current!.setPointerCapture(e.pointerId);
    const y = pointerY(e);
    press.current = y;
    jump(target(y).index);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const y = Math.max(0, Math.min(height, pointerY(e)));
    setHover(y);
    if (press.current === null) return;
    if (!dragging && Math.abs(y - press.current) < DRAG) return;
    setDragging(true);
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => jump(indexAt(y)));
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (press.current === null) return;
    press.current = null;
    rail.current!.releasePointerCapture(e.pointerId);
    setDragging(false);
  };
  const onKeyDown = (e: React.KeyboardEvent) => {
    const month = monthOf(current);
    const yearOf = (place: number) => months[place].month.slice(0, 4);
    const firstOfYear = (place: number) => { let p = place; while (p > 0 && yearOf(p - 1) === yearOf(place)) p--; return p; };
    let place: number | null = null;
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') place = Math.min(months.length - 1, month + 1);
    else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') place = current > starts[month] ? month : Math.max(0, month - 1);
    else if (e.key === 'PageDown') { let p = month; while (p < months.length - 1 && yearOf(p) === yearOf(month)) p++; place = p; }
    else if (e.key === 'PageUp') { const first = firstOfYear(month); place = current > starts[first] ? first : firstOfYear(Math.max(0, first - 1)); }
    else if (e.key === 'Home') place = 0;
    else if (e.key === 'End') place = months.length - 1;
    if (place === null) return;
    e.preventDefault();
    jump(starts[place]);
  };

  // The month is named beside the pointer while hovering, and beside the marker while dragging, loading, scrolling or focused.
  const pointing = hover !== null && !dragging ? target(hover) : null;
  const shown = dragging || !!pointing || waiting || scrolling || focused;
  return <div ref={rail} className="timeline" style={{ top }} role="slider" tabIndex={0} aria-label="Timeline" aria-orientation="vertical"
    aria-valuemin={0} aria-valuemax={total - 1} aria-valuenow={current} aria-valuetext={labelOf(current)}
    onPointerDown={onPointerDown} onMouseDown={e => e.preventDefault()} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp} onPointerLeave={() => setHover(null)}
    onKeyDown={onKeyDown} onFocus={e => setFocused(e.currentTarget.matches(':focus-visible'))} onBlur={() => setFocused(false)}>
    {labels.map(label => <span key={label.year} className="timeline-year" data-current={label.year === currentYear || undefined} style={{ top: label.y }}>{label.year}</span>)}
    {ticks.map(tick => <span key={tick.year} className="timeline-tick" style={{ top: tick.y }} />)}
    {pointing && <span className="timeline-hover" style={{ top: pointing.y }} />}
    <span className="timeline-marker" style={{ top: yOf(current) }} />
    <span className="timeline-chip" data-shown={shown || undefined} aria-hidden="true" style={{ top: pointing ? pointing.y : yOf(current) }}>{labelOf(pointing ? pointing.index : current)}</span>
  </div>;
}
