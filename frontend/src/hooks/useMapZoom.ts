import { useEffect, useRef, useState, type RefObject } from "react";

export const MAX_ZOOM = 6;

export interface MapView {
  x: number;
  y: number;
  w: number;
  h: number;
}
type Base = readonly [number, number, number, number];

const clamp = (v: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(hi, v));

/** Zoom 1x..MAX_ZOOM; panning may overshoot the map edge by up to a quarter view so edge sites can be centred. */
function clampView(v: MapView, base: Base): MapView {
  const [bx, by, bw, bh] = base;
  const w = clamp(v.w, bw / MAX_ZOOM, bw);
  const h = (w * bh) / bw;
  // No overshoot at 1x (the page must not feel draggable), growing as we zoom in
  const t = Math.min(1, (bw - w) / (bw * 0.5));
  const px = 0.25 * w * t;
  const py = 0.25 * h * t;
  return {
    x: clamp(v.x, bx - px, bx + bw - w + px),
    y: clamp(v.y, by - py, by + bh - h + py),
    w,
    h,
  };
}

/** New view with width nw that keeps the map point under fraction (fx, fy) of the box fixed. */
function zoomedAt(v: MapView, base: Base, fx: number, fy: number, nw: number) {
  const w = clamp(nw, base[2] / MAX_ZOOM, base[2]);
  const h = (w * base[3]) / base[2];
  return clampView(
    { x: v.x + fx * v.w - fx * w, y: v.y + fy * v.h - fy * h, w, h },
    base,
  );
}

const initial = (base: Base): MapView => ({
  x: base[0],
  y: base[1],
  w: base[2],
  h: base[3],
});

interface Options {
  boxRef: RefObject<HTMLElement | null>;
  base: Base;
}

/** Plain-wheel zoom speed: a 100px mouse notch is ~1.3x; trackpads send many small deltas, so it stays smooth. */
const WHEEL_K = 0.0026;
/** ctrl/cmd+wheel (also macOS trackpad pinch) is stronger: pinch deltas are tiny. */
const PINCH_K = 0.01;
const HINT_MS = 1500;

/**
 * Zoom + pan by animating the SVG viewBox. Inputs: buttons (returned handlers), double-click/tap, ctrl/cmd+wheel
 * (also trackpad pinch), two-finger pinch, mouse drag, and one-finger drag on touch only once zoomed.
 * The plain wheel is "click-to-activate": it zooms only after the map was clicked / dragged / pinched / zoomed by
 * button, and the map deactivates when the pointer leaves it or on Escape. While inactive the wheel scrolls the page
 * (and shows a short hint), so a long page is never trapped. One-finger touch at 1x is also left to the browser.
 */
export function useMapZoom({ boxRef, base }: Options) {
  const [bx, by, bw, bh] = base;
  const baseKey = `${bx},${by},${bw},${bh}`;
  const [view, setView] = useState<MapView>(() => initial(base));
  const [dragging, setDragging] = useState(false);
  const [prevKey, setPrevKey] = useState(baseKey);
  const [wheelActive, setWheelActive] = useState(false);
  const [wheelHint, setWheelHint] = useState(false);
  const activeRef = useRef(false);
  const hintTimer = useRef<number | undefined>(undefined);
  const viewRef = useRef(view);
  const baseRef = useRef<Base>(base);
  const animRef = useRef(0);

  // Layout switch (wide <-> compact) changes the map frame: start over
  if (prevKey !== baseKey) {
    setPrevKey(baseKey);
    setView(initial(base));
  }

  useEffect(() => {
    baseRef.current = [bx, by, bw, bh];
    viewRef.current = initial([bx, by, bw, bh]);
  }, [bx, by, bw, bh]);

  const commit = (v: MapView) => {
    const c = clampView(v, baseRef.current);
    viewRef.current = c;
    setView(c);
  };
  const cancelAnim = () => cancelAnimationFrame(animRef.current);
  const animateTo = (target: MapView) => {
    cancelAnim();
    const from = viewRef.current;
    const to = clampView(target, baseRef.current);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      commit(to);
      return;
    }
    const t0 = performance.now();
    const step = (now: number) => {
      const p = Math.min(1, (now - t0) / 220);
      const e = 1 - (1 - p) ** 3;
      // zoom interpolates in log space so in/out feel the same speed
      const w = Math.exp(
        Math.log(from.w) + (Math.log(to.w) - Math.log(from.w)) * e,
      );
      commit({
        x: from.x + (to.x - from.x) * e,
        y: from.y + (to.y - from.y) * e,
        w,
        h: (w * baseRef.current[3]) / baseRef.current[2],
      });
      if (p < 1) animRef.current = requestAnimationFrame(step);
    };
    animRef.current = requestAnimationFrame(step);
  };
  const zoomBy = (factor: number, fx = 0.5, fy = 0.5) =>
    animateTo(
      zoomedAt(
        viewRef.current,
        baseRef.current,
        fx,
        fy,
        viewRef.current.w / factor,
      ),
    );

  /** Animate to a view of width w centred on a map point (clamped like every other view). */
  const zoomTo = (cx: number, cy: number, w: number) => {
    const h = (w * baseRef.current[3]) / baseRef.current[2];
    animateTo({ x: cx - w / 2, y: cy - h / 2, w, h });
  };

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const pts = new Map<number, { x: number; y: number }>();
    let drag: {
      sx: number;
      sy: number;
      v0: MapView;
      moved: boolean;
      touch: boolean;
    } | null = null;
    let pinch: { d0: number; mx: number; my: number; w0: number } | null = null;
    let suppressClick = false;
    let ignoreClickUntil = 0;
    let lastTap = { t: 0, x: 0, y: 0 };
    let lastType = "mouse";

    const setActive = (on: boolean) => {
      if (activeRef.current === on) return;
      activeRef.current = on;
      setWheelActive(on);
      if (on) {
        window.clearTimeout(hintTimer.current);
        setWheelHint(false);
      }
    };
    const showHint = () => {
      setWheelHint(true);
      window.clearTimeout(hintTimer.current);
      hintTimer.current = window.setTimeout(() => setWheelHint(false), HINT_MS);
    };

    const isUi = (t: EventTarget | null) =>
      !!(t as Element | null)?.closest?.("[data-map-ui]");
    const frac = (cx: number, cy: number) => {
      const r = el.getBoundingClientRect();
      return { fx: (cx - r.left) / r.width, fy: (cy - r.top) / r.height, r };
    };
    const zoomed = () => viewRef.current.w < baseRef.current[2] - 0.01;
    const dist = () => {
      const [a, b] = [...pts.values()];
      return {
        d: Math.hypot(a.x - b.x, a.y - b.y),
        cx: (a.x + b.x) / 2,
        cy: (a.y + b.y) / 2,
      };
    };

    const onDown = (e: PointerEvent) => {
      // any press on the map (zoom buttons and cards included) arms the plain wheel
      setActive(true);
      if (isUi(e.target)) return;
      lastType = e.pointerType;
      cancelAnim();
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      suppressClick = false;
      if (pts.size === 2) {
        const { d, cx, cy } = dist();
        const { fx, fy } = frac(cx, cy);
        const v = viewRef.current;
        pinch = { d0: d, mx: v.x + fx * v.w, my: v.y + fy * v.h, w0: v.w };
        drag = null;
        suppressClick = true;
      } else if (
        pts.size === 1 &&
        (e.pointerType !== "mouse" || e.button === 0)
      ) {
        drag = {
          sx: e.clientX,
          sy: e.clientY,
          v0: viewRef.current,
          moved: false,
          touch: e.pointerType !== "mouse",
        };
      }
    };

    const onMove = (e: PointerEvent) => {
      if (!pts.has(e.pointerId)) return;
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pinch && pts.size >= 2) {
        const { d, cx, cy } = dist();
        const { fx, fy } = frac(cx, cy);
        const nw = clamp(
          pinch.w0 / (d / pinch.d0),
          baseRef.current[2] / MAX_ZOOM,
          baseRef.current[2],
        );
        const nh = (nw * baseRef.current[3]) / baseRef.current[2];
        // keep the map point first under the fingers' midpoint under the midpoint now (pinch + pan in one)
        commit({ x: pinch.mx - fx * nw, y: pinch.my - fy * nh, w: nw, h: nh });
        return;
      }
      if (!drag) return;
      const dx = e.clientX - drag.sx;
      const dy = e.clientY - drag.sy;
      if (!drag.moved) {
        if (Math.hypot(dx, dy) < (drag.touch ? 8 : 4)) return;
        // At 1x a touch drag belongs to the page scroll
        if (drag.touch && !zoomed()) {
          drag = null;
          return;
        }
        drag.moved = true;
        suppressClick = true;
        try {
          el.setPointerCapture(e.pointerId);
        } catch {
          /* pointer already gone */
        }
        setDragging(true);
      }
      const r = el.getBoundingClientRect();
      commit({
        x: drag.v0.x - (dx / r.width) * drag.v0.w,
        y: drag.v0.y - (dy / r.height) * drag.v0.h,
        w: drag.v0.w,
        h: drag.v0.h,
      });
    };

    const onUp = (e: PointerEvent) => {
      if (!pts.has(e.pointerId)) return;
      const wasDrag = drag;
      pts.delete(e.pointerId);
      if (pinch && pts.size < 2) {
        pinch = null;
        const rest = [...pts.values()][0];
        // lifting one finger of a pinch carries on as a pan with the other
        drag = rest
          ? {
              sx: rest.x,
              sy: rest.y,
              v0: viewRef.current,
              moved: true,
              touch: true,
            }
          : null;
      } else if (pts.size === 0) {
        drag = null;
      }
      if (pts.size === 0) setDragging(false);
      if (
        e.type === "pointerup" &&
        e.pointerType !== "mouse" &&
        wasDrag &&
        !wasDrag.moved &&
        !suppressClick &&
        // a marker tap is not a zoom gesture (the mouse onDbl skips triggers too)
        !(e.target as Element | null)?.closest?.("[data-popover-trigger]")
      ) {
        const now = Date.now();
        if (
          now - lastTap.t < 320 &&
          Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < 30
        ) {
          const { fx, fy } = frac(e.clientX, e.clientY);
          lastTap = { t: 0, x: 0, y: 0 };
          ignoreClickUntil = now + 400;
          zoomedAnim(fx, fy);
        } else {
          lastTap = { t: now, x: e.clientX, y: e.clientY };
        }
      }
    };

    // 2x per double-click, snapping back to 1x if already at the maximum
    const zoomedAnim = (fx: number, fy: number) => {
      const v = viewRef.current;
      const atMax = v.w <= baseRef.current[2] / MAX_ZOOM + 0.01;
      animateTo(
        atMax
          ? initial(baseRef.current)
          : zoomedAt(v, baseRef.current, fx, fy, v.w / 2),
      );
    };

    const onDbl = (e: MouseEvent) => {
      if (lastType === "touch" || lastType === "pen") return;
      if (
        (e.target as Element | null)?.closest?.(
          "[data-map-ui],[data-popover-trigger]",
        )
      )
        return;
      const { fx, fy } = frac(e.clientX, e.clientY);
      zoomedAnim(fx, fy);
    };

    const onClickCapture = (e: MouseEvent) => {
      if (suppressClick || Date.now() < ignoreClickUntil) {
        e.preventDefault();
        e.stopPropagation();
        suppressClick = false;
      }
    };

    // Native + non-passive: React's wheel listener is passive and cannot preventDefault
    const onWheel = (e: WheelEvent) => {
      const pinchKey = e.ctrlKey || e.metaKey;
      if (!pinchKey) {
        if (Math.abs(e.deltaY) < Math.abs(e.deltaX)) return; // horizontal swipe: not ours
        if (!activeRef.current) {
          showHint(); // no preventDefault: the page keeps scrolling
          return;
        }
        // Already fully zoomed out and wheeling out: hand the scroll back to the page
        if (e.deltaY > 0 && !zoomed()) return;
      }
      e.preventDefault();
      cancelAnim();
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
      const d = pinchKey
        ? clamp(e.deltaY * unit, -50, 50) * PINCH_K
        : clamp(e.deltaY * unit, -240, 240) * WHEEL_K;
      const { fx, fy } = frac(e.clientX, e.clientY);
      const v = viewRef.current;
      commit(zoomedAt(v, baseRef.current, fx, fy, v.w * Math.exp(d)));
    };
    const onLeave = (e: PointerEvent) => {
      if (e.pointerType === "mouse" && pts.size === 0) setActive(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setActive(false);
    };
    // keyboard activation of a zoom button has no pointerdown
    const onClickAny = () => setActive(true);

    // touch-action cannot be switched mid-gesture: stop the browser from claiming a second finger as scroll
    const onTouch = (e: TouchEvent) => {
      if (e.touches.length >= 2 && e.cancelable && !isUi(e.target))
        e.preventDefault();
    };

    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    el.addEventListener("dblclick", onDbl);
    el.addEventListener("click", onClickCapture, true);
    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("pointerleave", onLeave);
    el.addEventListener("click", onClickAny);
    document.addEventListener("keydown", onKey);
    el.addEventListener("touchstart", onTouch, { passive: false });
    el.addEventListener("touchmove", onTouch, { passive: false });
    return () => {
      cancelAnim();
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
      el.removeEventListener("dblclick", onDbl);
      el.removeEventListener("click", onClickCapture, true);
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("pointerleave", onLeave);
      el.removeEventListener("click", onClickAny);
      document.removeEventListener("keydown", onKey);
      window.clearTimeout(hintTimer.current);
      el.removeEventListener("touchstart", onTouch);
      el.removeEventListener("touchmove", onTouch);
    };
    // handlers read everything through refs; commit/animateTo only touch refs + a stable setter
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boxRef]);

  const zoom = bw / view.w;
  return {
    view,
    zoom,
    dragging,
    wheelActive,
    wheelHint,
    canIn: zoom < MAX_ZOOM - 0.01,
    canOut: zoom > 1.01,
    zoomIn: () => zoomBy(2),
    zoomOut: () => zoomBy(0.5),
    reset: () => animateTo(initial(baseRef.current)),
    zoomTo,
    // pan-y: one finger scrolls the page at 1x; none: we own every gesture once zoomed
    touchAction: (zoom > 1.01 ? "none" : "pan-y") as "none" | "pan-y",
  };
}
