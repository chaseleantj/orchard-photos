// A two-finger swipe arrives as a run of wheel events, and the trackpad's momentum keeps them coming for a second or
// two after the fingers lift. A swipe moves once its sideways travel reaches DISTANCE, then holds while the rest of
// it runs out, so one swipe never moves twice however fast or long it is. The hold ends, and the next swipe counts,
// when the wheel goes quiet for GESTURE_QUIET, when it turns the other way, after HOLD, or when, once the swipe has
// died down to a DECAY share of its fastest event, it pushes RENEW times harder than its slowest since. Momentum only
// ever slows, so that push is new fingers. Swipes that follow each other inside the momentum leave no quiet gap, so
// the gap alone would lose them. A gesture's first event fixes its axis, so a scroll that drifts sideways never swipes.
const DISTANCE = 120;
const DECAY = 1 / 4;
const RENEW = 2;
// Smaller pushes are the jitter of slow momentum, not a new swipe.
const RENEW_MIN = 6;
const HOLD = 1500;
/** How long the wheel stays quiet between gestures. */
export const GESTURE_QUIET = 300;

/** Reads wheel events in order. Returns null for one that isn't part of a sideways swipe, 0 for one that is but
 *  doesn't move, and -1 or 1 to move back or forward. */
export function swipe() {
  let travel = 0, last = -Infinity;
  // Whether the current gesture is sideways; null until an event decides.
  let sideways: boolean | null = null;
  // The direction the current swipe moved in, 0 until it moves; when it moved; its fastest event since, and its
  // slowest once it has died down.
  let moved = 0, movedAt = 0, fastest = 0, slowest = Infinity;
  return ({ deltaX, deltaY, ctrlKey, timeStamp }: WheelEvent) => {
    // A trackpad pinch arrives as wheel events with ctrlKey.
    if (ctrlKey) return null;
    if (timeStamp - last >= GESTURE_QUIET) { travel = 0; moved = 0; sideways = null; }
    last = timeStamp;
    if (Math.abs(deltaX) === Math.abs(deltaY)) return null;
    sideways ??= Math.abs(deltaX) > Math.abs(deltaY);
    if (!sideways || Math.abs(deltaX) < Math.abs(deltaY)) return null;
    const push = Math.abs(deltaX);
    if (moved) {
      const renewed = (Math.sign(deltaX) === -moved && push >= RENEW_MIN) || push >= Math.max(RENEW_MIN, slowest * RENEW) || timeStamp - movedAt >= HOLD;
      if (!renewed) {
        fastest = Math.max(fastest, push);
        if (push <= fastest * DECAY) slowest = Math.min(slowest, push);
        return 0;
      }
      travel = 0; moved = 0;
    }
    travel += deltaX;
    if (Math.abs(travel) < DISTANCE) return 0;
    moved = Math.sign(travel); movedAt = timeStamp; fastest = push; slowest = Infinity;
    return moved;
  };
}

/** Whether `node`, or a box around it, scrolls sideways, where two fingers scroll it instead of swiping. */
export function scrollsSideways(node: EventTarget | null) {
  for (let at = node instanceof Element ? node : null; at && at !== document.body; at = at.parentElement)
    if (at.scrollWidth - at.clientWidth > 1 && /auto|scroll/.test(getComputedStyle(at).overflowX)) return true;
  return false;
}
