import { GESTURE_QUIET } from './swipe';

// Zoom runs from the image fitted to the stage, scale 1, to DETAIL times the image's own pixels, or at least
// LEAST_MOST for an image with few pixels. A click zooms to the image's own pixels, or at least CLICK.
const DETAIL = 2;
const LEAST_MOST = 4;
const CLICK = 2;
// How far a pinch's wheel event zooms per unit of travel, and how far one press of Cmd or Ctrl and plus or minus goes.
const PINCH_RATE = .01;
const KEY_STEP = 1.5;
// Pointer travel that turns a click into a drag.
const DRAG_SLOP = 4;

/** WebKit sends a trackpad pinch as gesture events rather than wheel events with ctrlKey. */
type GestureEvent = UIEvent & { scale: number; clientX: number; clientY: number };
type Point = { clientX: number; clientY: number };

export interface StageZoom {
  /** The image to zoom, or null for none. A new image starts fitted. */
  set: (photo: HTMLImageElement | null) => void;
  toggle: () => void;
  /** Escape zooms out, and Cmd or Ctrl and plus, minus and zero zoom around the pointer. Says whether it took the key. */
  key: (event: KeyboardEvent) => boolean;
  stop: () => void;
}

/** Zoom and pan for the image on a stage. A click zooms in at the point clicked, and another click zooms out. While
 *  zoomed, a drag or two fingers pan, and a pinch zooms around the pointer. `changed` runs when the zoom turns on or off. */
export function stageZoom(stage: HTMLElement, changed: (zoomed: boolean) => void): StageZoom {
  let photo: HTMLImageElement | null = null;
  let scale = 1, x = 0, y = 0, pinchFrom = 1;
  let drag: { id: number; from: Point; x: number; y: number } | null = null;
  let dragged = false;
  let pointer: Point | null = null;
  // When the stage last took a two-finger scroll, so the rest of that gesture never becomes a swipe.
  let wheelAt = -Infinity;
  const zoomed = () => scale > 1;
  // The scale at which one image pixel fills one screen pixel.
  const ownPixels = (image: HTMLImageElement) => image.naturalWidth / ((image.clientWidth || 1) * devicePixelRatio);
  const most = (image: HTMLImageElement) => Math.max(LEAST_MOST, ownPixels(image) * DETAIL);
  // Pan no further than the image's edges; a side narrower than the stage stays centred.
  const clamp = (image: HTMLImageElement) => {
    const spareX = Math.max(0, (image.clientWidth * scale - stage.clientWidth) / 2);
    const spareY = Math.max(0, (image.clientHeight * scale - stage.clientHeight) / 2);
    x = Math.min(spareX, Math.max(-spareX, x));
    y = Math.min(spareY, Math.max(-spareY, y));
  };
  const show = (image: HTMLImageElement, animate = false) => {
    const was = stage.classList.contains('zoomed');
    image.style.transition = animate ? '' : 'none';
    image.style.transform = zoomed() ? `translate(${x}px, ${y}px) scale(${scale})` : '';
    stage.classList.toggle('zoomed', zoomed());
    // Zoomed in, a drag pans the image rather than carrying it out of the window.
    image.draggable = !zoomed();
    if (was !== zoomed()) changed(zoomed());
  };
  // Zoom to `next`, holding still the point under `at`, or the middle without one.
  const zoomTo = (next: number, at: Point | null = null, animate = false) => {
    if (!photo) return;
    next = Math.min(most(photo), Math.max(1, next));
    const box = stage.getBoundingClientRect();
    const px = at ? at.clientX - box.left - box.width / 2 : 0;
    const py = at ? at.clientY - box.top - box.height / 2 : 0;
    const grow = next / scale;
    x = px - grow * (px - x);
    y = py - grow * (py - y);
    scale = next;
    if (!zoomed()) x = y = 0;
    clamp(photo);
    show(photo, animate);
  };
  const zoomIn = (at: Point | null) => photo && zoomTo(Math.min(most(photo), Math.max(CLICK, ownPixels(photo))), at, true);
  const zoomOut = () => zoomTo(1, null, true);
  const release = () => { drag = null; stage.classList.remove('dragging'); };

  const listening = new AbortController();
  const options = { signal: listening.signal };
  stage.addEventListener('click', event => {
    if (!photo || dragged) return;
    if (zoomed()) zoomOut();
    else if (event.target === photo) zoomIn(event);
  }, options);
  stage.addEventListener('pointerdown', event => {
    dragged = false;
    if (!photo || !zoomed() || event.button !== 0) return;
    drag = { id: event.pointerId, from: event, x, y };
  }, options);
  stage.addEventListener('pointermove', event => {
    pointer = event;
    if (!drag || !photo) return;
    const dx = event.clientX - drag.from.clientX, dy = event.clientY - drag.from.clientY;
    if (!dragged && Math.hypot(dx, dy) < DRAG_SLOP) return;
    if (!dragged) { dragged = true; stage.setPointerCapture(drag.id); stage.classList.add('dragging'); }
    x = drag.x + dx; y = drag.y + dy;
    clamp(photo);
    show(photo);
  }, options);
  stage.addEventListener('pointerup', release, options);
  stage.addEventListener('pointercancel', release, options);
  stage.addEventListener('pointerleave', () => { if (!drag) pointer = null; }, options);
  // A trackpad pinch arrives as wheel events with ctrlKey. Taking every one keeps the page itself from zooming.
  stage.addEventListener('wheel', event => {
    if (!photo) return;
    if (event.ctrlKey) { event.preventDefault(); zoomTo(scale * Math.exp(-event.deltaY * PINCH_RATE), event); return; }
    // While zoomed two fingers pan, and the rest of that gesture, its momentum included, stays with the stage after
    // a zoom out, so it never reaches the swipe that moves to another image.
    if (!zoomed() && event.timeStamp - wheelAt >= GESTURE_QUIET) return;
    event.preventDefault();
    event.stopPropagation();
    wheelAt = event.timeStamp;
    if (!zoomed()) return;
    x -= event.deltaX; y -= event.deltaY;
    clamp(photo);
    show(photo);
  }, { ...options, passive: false });
  stage.addEventListener('gesturestart', event => { if (!photo) return; event.preventDefault(); pinchFrom = scale; }, options);
  stage.addEventListener('gesturechange', event => { if (!photo) return; event.preventDefault(); const gesture = event as GestureEvent; zoomTo(pinchFrom * gesture.scale, gesture); }, options);
  stage.addEventListener('gestureend', event => { if (photo) event.preventDefault(); }, options);
  // A resized window keeps the zoom, its pan held inside the image's new edges.
  const resized = new ResizeObserver(() => { if (photo && zoomed()) { clamp(photo); show(photo); } });
  resized.observe(stage);

  return {
    set(next) {
      const was = zoomed();
      if (photo && photo !== next) { photo.style.transform = ''; photo.draggable = true; }
      photo = next;
      scale = 1; x = y = 0;
      if (photo) { photo.style.transform = ''; photo.draggable = true; }
      release();
      stage.classList.remove('zoomed');
      if (was) changed(false);
    },
    toggle: () => zoomed() ? zoomOut() : zoomIn(null),
    key(event) {
      if (!photo) return false;
      const command = event.metaKey || event.ctrlKey;
      if (event.key === 'Escape' && !command && !event.altKey && zoomed()) zoomOut();
      else if (!command || event.altKey) return false;
      else if (event.key === '=' || event.key === '+') zoomTo(scale * KEY_STEP, pointer, true);
      else if (event.key === '-') zoomTo(scale / KEY_STEP, pointer, true);
      else if (event.key === '0') zoomOut();
      else return false;
      event.preventDefault();
      return true;
    },
    stop() { listening.abort(); resized.disconnect(); },
  };
}
