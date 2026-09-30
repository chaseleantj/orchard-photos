import type { Picture } from './types';
import { imageUrl } from './types';

export interface MapPoint extends Picture { x: number; y: number; slot: number }
export interface MapCamera { x: number; y: number; zoom: number }
export interface MapCallbacks {
  onSelect: (id: string | null) => void;
  onFrame: () => void;
  onSettle: (camera: MapCamera) => void;
}

// These mirror server/atlas.py: 64px cells holding a 60px icon, 32 per row.
const CELL = 64, INSET = 2, INNER = CELL - 2 * INSET, COLUMNS = 32, PER_SHEET = COLUMNS * COLUMNS;
const CORNER = 7 / INNER;
const DIMMED = 0.22;
const RECEDED = 0.5;
const SHARP_AT = 72;
const MAX_ZOOM = 120;
const MIN_ZOOM = 0.4;
const MAX_ICON = 220;
const MAX_LOADS = 8;
const MAX_THUMBS = 480;

interface Camera { x: number; y: number; k: number }
interface Thumb { image: HTMLImageElement; ready: boolean; shown: number; used: number }

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const approach = (rate: number, dt: number) => 1 - Math.exp(-dt / rate);

/** Draws the embedding on a canvas and owns the camera, hover and hit-testing. React only sees selections. */
export class MapEngine {
  private ctx: CanvasRenderingContext2D;
  private w = 0; private h = 0; private dpr = 1;
  private points: MapPoint[] = [];
  private index = new Map<string, number>();
  private sheets: ImageBitmap[] = [];
  private cam: Camera = { x: 0, y: 0, k: 1 };
  private goal: Camera = { x: 0, y: 0, k: 1 };
  private anchor: { wx: number; wy: number; mx: number; my: number } | null = null;
  private flight = false;
  private fitK = 1; private base = 20;
  private bounds = { minX: -1, maxX: 1, minY: -1, maxY: 1 };
  private hovered = -1; private selected = -1;
  private members: Set<number> | null = null;
  private lift = new Map<number, number>();
  private dim = 0; private intro = 1;
  private morphing = 1; private morphFrom = new Float32Array(0); private morphTo = new Float32Array(0);
  private sx = new Float32Array(0); private sy = new Float32Array(0);
  private order: number[] = [];
  private thumbs = new Map<string, Thumb>();
  private loading = 0;
  private frame = 0; private last = 0; private clock = 0;
  private settle = 0;
  private pointer: { x: number; y: number } | null = null;
  private touches = new Map<number, { x: number; y: number }>();
  private drag: { x: number; y: number; moved: boolean; vx: number; vy: number; t: number } | null = null;
  private pinch: { distance: number; x: number; y: number } | null = null;
  private glide = { vx: 0, vy: 0 };
  private reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  constructor(private canvas: HTMLCanvasElement, private stage: HTMLElement, private calls: MapCallbacks) {
    this.ctx = canvas.getContext('2d')!;
    stage.addEventListener('wheel', this.wheel, { passive: false });
    stage.addEventListener('pointerdown', this.down);
    stage.addEventListener('pointermove', this.move);
    stage.addEventListener('pointerup', this.up);
    stage.addEventListener('pointercancel', this.cancel);
    stage.addEventListener('pointerleave', this.leave);
    stage.addEventListener('dblclick', this.double);
  }

  destroy() {
    cancelAnimationFrame(this.frame); clearTimeout(this.settle);
    const s = this.stage;
    s.removeEventListener('wheel', this.wheel);
    s.removeEventListener('pointerdown', this.down);
    s.removeEventListener('pointermove', this.move);
    s.removeEventListener('pointerup', this.up);
    s.removeEventListener('pointercancel', this.cancel);
    s.removeEventListener('pointerleave', this.leave);
    s.removeEventListener('dblclick', this.double);
    this.thumbs.clear(); this.sheets.forEach(sheet => sheet.close()); this.sheets = [];
  }

  // ---- Data ------------------------------------------------------------------------------------

  resize(width: number, height: number, dpr: number) {
    const first = this.w === 0, before = this.fitK;
    this.w = width; this.h = height; this.dpr = dpr;
    this.canvas.width = Math.round(width * dpr); this.canvas.height = Math.round(height * dpr);
    this.measure();
    if (first && this.points.length) this.fit(false);
    else if (this.points.length) {
      // Keep the same framing when the window changes shape.
      this.fitK = this.frameOf(this.points.map((_, i) => i)).k;
      const ratio = this.fitK / before;
      this.cam.k *= ratio; this.goal.k *= ratio;
      if (this.anchor) this.anchor = null;
    }
    this.invalidate();
  }

  setSheets(sheets: ImageBitmap[]) { this.sheets.forEach(sheet => sheet.close()); this.sheets = sheets; this.invalidate(); }

  setPoints(points: MapPoint[], restore?: MapCamera) {
    const selected = this.selected >= 0 ? this.points[this.selected]?.id : null;
    this.points = points; this.morphing = 1;
    this.index = new Map(points.map((p, i) => [p.id, i]));
    this.sx = new Float32Array(points.length); this.sy = new Float32Array(points.length);
    this.hovered = -1; this.lift.clear(); this.members = null; this.dim = 0;
    this.selected = selected ? this.index.get(selected) ?? -1 : -1;
    if (this.selected < 0 && selected) this.calls.onSelect(null);
    this.measure();
    if (this.w) {
      this.fitK = this.frameOf(this.points.map((_, i) => i)).k;
      if (restore) this.jump(restore); else this.fit(false);
    }
    this.intro = this.reduced ? 1 : 0;
    this.invalidate();
  }

  /** Swaps in a new arrangement of the same library: images glide from where they were to where they now belong. */
  morph(points: MapPoint[], refit: boolean) {
    if (!this.points.length || this.reduced) { this.setPoints(points, refit ? undefined : this.camera); return; }
    const before = new Map(this.points.map(p => [p.id, p]));
    const selected = this.selected >= 0 ? this.points[this.selected].id : null;
    // The engine owns these copies: their coordinates change every frame.
    this.points = points.map(p => ({ ...p }));
    this.index = new Map(this.points.map((p, i) => [p.id, i]));
    this.sx = new Float32Array(points.length); this.sy = new Float32Array(points.length);
    this.hovered = -1; this.lift.clear(); this.members = null; this.dim = 0;
    this.selected = selected ? this.index.get(selected) ?? -1 : -1;
    if (this.selected < 0 && selected) this.calls.onSelect(null);
    this.measure();
    if (this.w) { this.fitK = this.frameOf(this.points.map((_, i) => i)).k; if (refit) this.fit(true); }
    this.morphFrom = new Float32Array(points.length * 2); this.morphTo = new Float32Array(points.length * 2);
    this.points.forEach((p, i) => {
      const old = before.get(p.id);
      this.morphFrom.set([old ? old.x : p.x, old ? old.y : p.y], i * 2); this.morphTo.set([p.x, p.y], i * 2);
    });
    this.morphing = 0;
    this.invalidate();
  }

  setHighlight(ids: string[] | null) {
    const set = ids && new Set(ids.map(id => this.index.get(id)).filter((i): i is number => i !== undefined));
    this.members = set && set.size ? set : null;
    if (this.members) this.flyTo([...this.members]);
    this.invalidate();
  }

  /** Base icon size follows the library size, so a handful of images does not look lost. */
  private measure() {
    const n = Math.max(1, this.points.length);
    this.base = clamp(0.6 * Math.sqrt((this.w * this.h) / n), 20, 64);
    if (!this.points.length) return;
    const xs = this.points.map(p => p.x).sort((a, b) => a - b), ys = this.points.map(p => p.y).sort((a, b) => a - b);
    this.bounds = { minX: xs[0], maxX: xs[xs.length - 1], minY: ys[0], maxY: ys[ys.length - 1] };
  }

  // ---- Camera ----------------------------------------------------------------------------------

  private frameOf(indices: number[]): Camera {
    const pad = clamp(Math.min(this.w, this.h) * 0.07, 20, 72) + this.base / 2;
    const xs = indices.map(i => this.points[i].x).sort((a, b) => a - b);
    const ys = indices.map(i => this.points[i].y).sort((a, b) => a - b);
    const minX = xs[0], maxX = xs[xs.length - 1], minY = ys[0], maxY = ys[ys.length - 1];
    const k = Math.min((this.w - 2 * pad) / Math.max(maxX - minX, 1e-6), (this.h - 2 * pad) / Math.max(maxY - minY, 1e-6));
    return { x: (minX + maxX) / 2, y: (minY + maxY) / 2, k };
  }

  fit(animated = true) {
    if (!this.points.length || !this.w) return;
    const frame = this.frameOf(this.points.map((_, i) => i));
    this.fitK = frame.k;
    this.travel(frame, animated);
  }

  private flyTo(indices: number[]) {
    const frame = this.frameOf(indices);
    frame.k = clamp(frame.k, this.fitK * 0.8, this.fitK * 14);
    this.travel(frame, true);
  }

  private travel(goal: Camera, animated: boolean) {
    this.goal = { ...goal }; this.anchor = null; this.glide = { vx: 0, vy: 0 };
    if (animated && !this.reduced) this.flight = true; else this.cam = { ...goal };
    this.invalidate();
  }

  jump(camera: MapCamera) {
    const k = clamp(this.fitK * camera.zoom, this.fitK * MIN_ZOOM, this.fitK * MAX_ZOOM);
    this.travel({ x: camera.x, y: camera.y, k }, false);
  }

  get camera(): MapCamera { return { x: this.goal.x, y: this.goal.y, zoom: this.goal.k / this.fitK }; }

  zoomBy(factor: number, mx = this.w / 2, my = this.h / 2, instant = false) {
    const k = clamp(this.goal.k * factor, this.fitK * MIN_ZOOM, this.fitK * MAX_ZOOM);
    const wx = (mx - this.w / 2) / this.goal.k + this.goal.x, wy = (my - this.h / 2) / this.goal.k + this.goal.y;
    this.goal = { k, x: wx - (mx - this.w / 2) / k, y: wy - (my - this.h / 2) / k };
    this.flight = false; this.glide = { vx: 0, vy: 0 };
    if (instant || this.reduced) { this.cam = { ...this.goal }; this.anchor = null; } else this.anchor = { wx, wy, mx, my };
    this.limit(); this.invalidate();
  }

  panBy(dx: number, dy: number, instant = true) {
    this.goal.x += dx / this.goal.k; this.goal.y += dy / this.goal.k;
    this.anchor = null; this.flight = false;
    this.limit();
    if (instant || this.reduced) this.cam = { ...this.goal };
    this.invalidate();
  }

  /** Keep some of the data on screen, so the view can never be lost in empty space. */
  private limit() {
    const b = this.bounds, g = this.goal;
    g.x = clamp(g.x, b.minX - this.w / g.k * 0.4, b.maxX + this.w / g.k * 0.4);
    g.y = clamp(g.y, b.minY - this.h / g.k * 0.4, b.maxY + this.h / g.k * 0.4);
  }

  private iconSize(k = this.cam.k) { return Math.min(MAX_ICON, this.base * Math.sqrt(k / this.fitK)); }

  /** Screen position and size of a point, for overlays that follow the camera. */
  project(id: string) {
    const i = this.index.get(id);
    if (i === undefined) return null;
    const p = this.points[i], c = this.cam;
    return { x: (p.x - c.x) * c.k + this.w / 2, y: (p.y - c.y) * c.k + this.h / 2, size: this.iconSize() };
  }

  // ---- Selection -------------------------------------------------------------------------------

  select(id: string | null, reveal = false) {
    const i = id === null ? -1 : this.index.get(id) ?? -1;
    if (i === this.selected) return;
    this.selected = i;
    if (i >= 0 && reveal) this.reveal(i);
    this.calls.onSelect(i >= 0 ? this.points[i].id : null);
    this.invalidate();
  }

  private reveal(i: number) {
    const p = this.points[i], g = this.goal, margin = 96;
    const x = (p.x - g.x) * g.k + this.w / 2, y = (p.y - g.y) * g.k + this.h / 2;
    if (x > margin && x < this.w - margin && y > margin && y < this.h - margin) return;
    this.goal = { ...g, x: p.x, y: p.y }; this.anchor = null; this.flight = true;
  }

  /** Move to the nearest image in a direction, within a 50 degree cone. */
  step(dx: number, dy: number) {
    if (this.selected < 0) return;
    const from = this.points[this.selected];
    let best = -1, bestScore = Infinity;
    this.points.forEach((p, i) => {
      if (i === this.selected || (this.members && !this.members.has(i))) return;
      const ax = p.x - from.x, ay = p.y - from.y, along = ax * dx + ay * dy, across = Math.abs(ax * dy - ay * dx);
      if (along <= 1e-6 || across > along * 1.2) return;
      const score = along + across * 0.6;
      if (score < bestScore) { bestScore = score; best = i; }
    });
    if (best >= 0) this.select(this.points[best].id, true);
  }

  /** The image nearest the middle of the view. */
  nearestToCenter() {
    let best = -1, bestDistance = Infinity;
    const c = this.goal;
    this.points.forEach((p, i) => {
      if (this.members && !this.members.has(i)) return;
      const d = (p.x - c.x) ** 2 + (p.y - c.y) ** 2;
      if (d < bestDistance) { bestDistance = d; best = i; }
    });
    return best >= 0 ? this.points[best].id : null;
  }

  // ---- Pointer input ---------------------------------------------------------------------------

  private local(e: { clientX: number; clientY: number }) {
    const r = this.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }
  private onChrome(e: Event) { return (e.target as HTMLElement).closest?.('.map-card, .map-controls, button, a') !== null; }

  private wheel = (e: WheelEvent) => {
    e.preventDefault();
    const { x, y } = this.local(e);
    const delta = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1);
    this.zoomBy(Math.exp(-delta * (e.ctrlKey ? 0.012 : 0.002)), x, y);
  };

  private down = (e: PointerEvent) => {
    if (this.onChrome(e) || (e.pointerType === 'mouse' && e.button !== 0)) return;
    this.stage.setPointerCapture(e.pointerId);
    const p = this.local(e);
    this.touches.set(e.pointerId, p);
    this.glide = { vx: 0, vy: 0 };
    if (this.touches.size === 1) this.drag = { ...p, moved: false, vx: 0, vy: 0, t: e.timeStamp };
    else { this.drag = null; this.startPinch(); }
  };

  private startPinch() {
    const [a, b] = [...this.touches.values()];
    this.pinch = { distance: Math.hypot(a.x - b.x, a.y - b.y) || 1, x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  }

  private move = (e: PointerEvent) => {
    const p = this.local(e);
    if (this.touches.has(e.pointerId)) this.touches.set(e.pointerId, p);
    if (this.pinch && this.touches.size >= 2) {
      const [a, b] = [...this.touches.values()];
      const distance = Math.hypot(a.x - b.x, a.y - b.y) || 1, x = (a.x + b.x) / 2, y = (a.y + b.y) / 2;
      this.panBy(-(x - this.pinch.x), -(y - this.pinch.y));
      this.zoomBy(distance / this.pinch.distance, x, y, true);
      this.pinch = { distance, x, y };
      return;
    }
    if (this.drag && this.touches.has(e.pointerId)) {
      const d = this.drag, dx = p.x - d.x, dy = p.y - d.y;
      if (!d.moved && Math.hypot(dx, dy) < 5) return;
      d.moved = true; this.canvas.style.cursor = 'grabbing';
      const dt = Math.max(1, e.timeStamp - d.t);
      d.vx = 0.7 * (dx / dt) + 0.3 * d.vx; d.vy = 0.7 * (dy / dt) + 0.3 * d.vy;
      d.x = p.x; d.y = p.y; d.t = e.timeStamp;
      this.panBy(-dx, -dy);
      this.setHover(-1);
      return;
    }
    this.pointer = p;
    this.setHover(this.hit(p.x, p.y));
  };

  private up = (e: PointerEvent) => {
    const p = this.local(e), d = this.drag;
    this.touches.delete(e.pointerId);
    if (this.touches.size < 2) this.pinch = null;
    if (!d) return;
    this.drag = null; this.canvas.style.cursor = '';
    if (!d.moved) {
      const i = this.hit(p.x, p.y);
      this.select(i >= 0 ? this.points[i].id : null);
    } else if (!this.reduced && e.timeStamp - d.t < 80 && Math.hypot(d.vx, d.vy) > 0.05) {
      this.glide = { vx: d.vx, vy: d.vy }; this.invalidate();
    }
    if (e.pointerType !== 'mouse') this.setHover(-1);
  };

  private cancel = (e: PointerEvent) => { this.touches.delete(e.pointerId); this.pinch = null; this.drag = null; this.canvas.style.cursor = ''; };
  private leave = () => { this.pointer = null; if (!this.drag) this.setHover(-1); };
  private double = (e: MouseEvent) => {
    if (this.onChrome(e)) return;
    const { x, y } = this.local(e);
    this.zoomBy(2.4, x, y);
  };

  // ---- Hit testing and hover -------------------------------------------------------------------

  /** Topmost image under a screen position. The image already lifted is tested at its lifted size. */
  private hit(x: number, y: number) {
    const size = this.iconSize();
    const inside = (i: number, s: number) => Math.abs(x - this.sx[i]) <= s / 2 && Math.abs(y - this.sy[i]) <= s / 2;
    if (this.hovered >= 0 && inside(this.hovered, this.liftedSize(this.hovered, size))) return this.hovered;
    for (let n = this.order.length - 1; n >= 0; n--) if (inside(this.order[n], size)) return this.order[n];
    return -1;
  }

  private setHover(i: number) {
    if (i === this.hovered) return;
    this.hovered = i;
    if (i >= 0 && !this.lift.has(i)) this.lift.set(i, 0);
    this.canvas.style.cursor = i >= 0 ? 'pointer' : '';
    this.invalidate();
  }

  private liftedSize(i: number, size: number) { const t = this.lift.get(i) ?? 0; return size + Math.max(18, size * 0.35) * t; }

  // ---- Frame loop ------------------------------------------------------------------------------

  invalidate() { if (!this.frame) this.frame = requestAnimationFrame(this.tick); }

  private tick = (now: number) => {
    this.frame = 0;
    const dt = Math.min(48, this.last ? now - this.last : 16); this.last = now; this.clock = now;
    const busy = this.update(dt);
    this.draw();
    this.calls.onFrame();
    if (busy) this.invalidate(); else { this.last = 0; this.settled(); }
  };

  private update(dt: number) {
    let busy = false;
    const { cam, goal } = this;
    if (this.glide.vx || this.glide.vy) {
      this.panBy(-this.glide.vx * dt, -this.glide.vy * dt);
      const decay = Math.exp(-dt / 320);
      this.glide.vx *= decay; this.glide.vy *= decay;
      if (Math.hypot(this.glide.vx, this.glide.vy) < 0.01) this.glide = { vx: 0, vy: 0 };
      busy = true;
    }
    const a = approach(this.flight ? 130 : 80, dt);
    const dk = Math.log(goal.k / cam.k);
    if (Math.abs(dk) > 0.0004) { cam.k *= Math.exp(dk * a); busy = true; } else cam.k = goal.k;
    if (this.anchor) {
      const n = this.anchor;
      cam.x = n.wx - (n.mx - this.w / 2) / cam.k; cam.y = n.wy - (n.my - this.h / 2) / cam.k;
      if (cam.k === goal.k) this.anchor = null;
    } else {
      const ex = goal.x - cam.x, ey = goal.y - cam.y;
      if (Math.abs(ex) * cam.k > 0.2 || Math.abs(ey) * cam.k > 0.2) { cam.x += ex * a; cam.y += ey * a; busy = true; } else { cam.x = goal.x; cam.y = goal.y; this.flight = false; }
    }
    if (this.anchor) busy = true;
    const dimGoal = this.members ? 1 : this.selected >= 0 ? 0.18 : 0;
    if (Math.abs(dimGoal - this.dim) > 0.003) { this.dim += (dimGoal - this.dim) * (this.reduced ? 1 : approach(150, dt)); busy = true; } else this.dim = dimGoal;
    if (this.morphing < 1) {
      this.morphing = Math.min(1, this.morphing + dt / 700);
      const eased = 1 - Math.pow(1 - this.morphing, 3), { morphFrom: a, morphTo: b } = this;
      this.points.forEach((p, i) => { p.x = a[i * 2] + (b[i * 2] - a[i * 2]) * eased; p.y = a[i * 2 + 1] + (b[i * 2 + 1] - a[i * 2 + 1]) * eased; });
      busy = true;
    }
    if (this.intro < 1) { this.intro = Math.min(1, this.intro + dt / 900); busy = true; }
    for (const [i, t] of this.lift) {
      const goalLift = i === this.hovered ? 1 : 0;
      const next = this.reduced ? goalLift : t + (goalLift - t) * approach(70, dt);
      if (goalLift === 0 && next < 0.01) this.lift.delete(i); else { this.lift.set(i, Math.abs(goalLift - next) < 0.005 ? goalLift : next); if (this.lift.get(i) !== goalLift) busy = true; }
    }
    if (this.pointer && !this.drag && busy) this.setHover(this.hit(this.pointer.x, this.pointer.y));
    return busy || this.pendingThumbs;
  }

  private settled() {
    clearTimeout(this.settle);
    // Before any points arrive the camera means nothing; saving it would override the first fit.
    if (!this.points.length) return;
    this.settle = window.setTimeout(() => this.calls.onSettle(this.camera), 350);
  }

  // ---- Drawing ---------------------------------------------------------------------------------

  private pendingThumbs = false;

  private draw() {
    const { ctx, cam, w, h, dpr, points } = this;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const size = this.iconSize(), half = size / 2, sharp = size * dpr > SHARP_AT;
    const lit: number[] = [], faded: number[] = [];
    for (let i = points.length - 1; i >= 0; i--) {
      const p = points[i], x = (p.x - cam.x) * cam.k + w / 2, y = (p.y - cam.y) * cam.k + h / 2;
      this.sx[i] = x; this.sy[i] = y;
      if (x < -half || x > w + half || y < -half || y > h + half) continue;
      (!this.members || this.members.has(i) ? lit : faded).push(i);
    }
    this.order = faded.concat(lit);
    const mute = 1 - (1 - DIMMED) * this.dim;
    const paint = (i: number) => {
      if (this.lift.has(i)) return;
      const receded = this.members ? !this.members.has(i) && i !== this.selected : this.selected >= 0 && i !== this.selected;
      // A radial bloom on arrival: the centre of the map appears first.
      const r = Math.min(1, Math.hypot(points[i].x, points[i].y)), t = clamp(this.intro * 1.6 - r * 0.6, 0, 1), eased = 1 - Math.pow(1 - t, 3);
      // Whatever is not being looked at shrinks to fine dust, so the lit images read as figures on a ground.
      const scale = (receded && this.members ? 1 - (1 - RECEDED) * this.dim : 1) * (this.intro >= 1 ? 1 : 0.6 + 0.4 * eased);
      this.tile(i, size * scale, (receded ? mute : 1) * (this.intro >= 1 ? 1 : eased), 0, sharp && !receded);
    };
    for (const i of this.order) paint(i);
    const raised = [...this.lift.keys()].filter(i => this.sx[i] > -size && this.sx[i] < w + size).sort((a, b) => this.lift.get(a)! - this.lift.get(b)!);
    for (const i of raised) { const s = this.liftedSize(i, size); this.tile(i, s, 1, this.lift.get(i)!, s * dpr > SHARP_AT); }
    ctx.globalAlpha = 1;
    if (sharp) this.requestThumbs(); else this.pendingThumbs = false;
  }

  private tile(i: number, size: number, alpha: number, lift: number, sharp: boolean) {
    const { ctx } = this, p = this.points[i], sheet = this.sheets[Math.floor(p.slot / PER_SHEET)];
    if (!sheet || alpha <= 0.004) return;
    const cell = p.slot % PER_SHEET, x = this.sx[i] - size / 2, y = this.sy[i] - size / 2;
    ctx.globalAlpha = alpha;
    if (lift > 0) { ctx.shadowColor = 'rgba(0,0,0,.22)'; ctx.shadowBlur = 24 * lift; ctx.shadowOffsetY = 8 * lift; }
    ctx.drawImage(sheet, (cell % COLUMNS) * CELL + INSET, Math.floor(cell / COLUMNS) * CELL + INSET, INNER, INNER, x, y, size, size);
    if (lift > 0) { ctx.shadowColor = 'transparent'; ctx.shadowBlur = 0; ctx.shadowOffsetY = 0; }
    if (!sharp) return;
    const thumb = this.thumb(p.id, true);
    if (!thumb) return;
    thumb.used = this.clock;
    const fade = clamp((this.clock - thumb.shown) / 200, 0, 1);
    const image = thumb.image, side = Math.min(image.naturalWidth, image.naturalHeight);
    ctx.save();
    ctx.beginPath(); ctx.roundRect(x, y, size, size, size * CORNER); ctx.clip();
    ctx.globalAlpha = alpha * fade;
    ctx.drawImage(image, (image.naturalWidth - side) / 2, (image.naturalHeight - side) / 2, side, side, x, y, size, size);
    ctx.restore();
    if (fade < 1) this.pendingThumbs = true;
  }

  // ---- Sharp thumbnails ------------------------------------------------------------------------

  private thumb(id: string, ask: boolean) {
    const found = this.thumbs.get(id);
    if (found) return found.ready ? found : null;
    if (!ask || this.loading >= MAX_LOADS) return null;
    this.load(id);
    return null;
  }

  private load(id: string) {
    const image = new Image(), entry: Thumb = { image, ready: false, shown: 0, used: this.clock };
    this.thumbs.set(id, entry); this.loading++;
    image.decoding = 'async';
    image.onload = () => { entry.ready = true; entry.shown = performance.now(); this.loading--; this.pendingThumbs = true; this.invalidate(); };
    image.onerror = () => { this.loading--; };
    image.src = imageUrl(id);
    if (this.thumbs.size > MAX_THUMBS) {
      const stale = [...this.thumbs.entries()].filter(([, t]) => t.ready && t.used < this.clock - 1000).sort((a, b) => a[1].used - b[1].used).slice(0, MAX_THUMBS / 4);
      for (const [key] of stale) this.thumbs.delete(key);
    }
  }

  /** Fetch sharp thumbnails for what is on screen, nearest to the middle first. */
  private requestThumbs() {
    if (this.loading >= MAX_LOADS) { this.pendingThumbs = true; return; }
    const cx = this.w / 2, cy = this.h / 2;
    const want = this.order.filter(i => !this.thumbs.has(this.points[i].id)).sort((a, b) => Math.hypot(this.sx[a] - cx, this.sy[a] - cy) - Math.hypot(this.sx[b] - cx, this.sy[b] - cy));
    for (const i of want.slice(0, MAX_LOADS - this.loading)) this.load(this.points[i].id);
    this.pendingThumbs = want.length > 0;
  }

  // ---- Keyboard --------------------------------------------------------------------------------

  key(e: KeyboardEvent) {
    const arrows: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (e.metaKey || e.ctrlKey || e.altKey) return false;
    if (e.key in arrows) {
      const [dx, dy] = arrows[e.key];
      if (this.selected >= 0 && !e.shiftKey) this.step(dx, dy); else this.panBy(dx * 120, dy * 120, false);
    } else if (e.key === '+' || e.key === '=') this.zoomBy(1.6);
    else if (e.key === '-' || e.key === '_') this.zoomBy(1 / 1.6);
    else if (e.key === '0') this.fit();
    else if (e.key === 'Escape' && this.selected >= 0) this.select(null);
    else if ((e.key === 'Enter' || e.key === ' ') && this.selected < 0) { const id = this.nearestToCenter(); if (id) this.select(id, true); }
    else return false;
    return true;
  }
}
