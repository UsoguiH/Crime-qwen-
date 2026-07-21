/* Entrance choreography — dependency-free spring engine ported verbatim from
   the ChatGPT-style template (chat-ui-template.html). Springs are pre-sampled
   at 60 fps into WAAPI keyframes (fill: both covers the delay so "from"
   states apply before start). Each wave cancels its animations once settled,
   returning elements to stylesheet values — plus a hard deadline failsafe. */

export const GLIDE = { stiffness: 190, damping: 26, mass: 1 };
export const SETTLE = { stiffness: 150, damping: 19, mass: 1.05 };
export const POP = { stiffness: 400, damping: 24, mass: 0.9 };

type Spring = typeof GLIDE;
type Pair = [number, number];
export interface SpringProps {
  x?: Pair; y?: Pair; scale?: Pair; rotate?: Pair; opacity?: Pair; blur?: Pair;
}

const reducedMotion = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const sampleCache = new Map<Spring, number[]>();

function springSamples(sp: Spring): number[] {
  const hit = sampleCache.get(sp);
  if (hit) return hit;
  const { stiffness: k, damping: c, mass: m } = sp;
  const dt = 1 / 60;
  const out = [0];
  let x = 0, v = 0;
  for (let i = 0; i < 300; i++) {
    v += ((-k * (x - 1) - c * v) / m) * dt;
    x += v * dt;
    out.push(x);
    if (Math.abs(1 - x) < 0.001 && Math.abs(v) < 0.001) break;
  }
  out.push(1);
  sampleCache.set(sp, out);
  return out;
}

function springAnim(el: Element, props: SpringProps, sp: Spring,
                    delayMs = 0): Animation {
  const samples = springSamples(sp);
  const frames = samples.map((p) => {
    const lerp = (pair: Pair) => pair[0] + (pair[1] - pair[0]) * p;
    const tr: string[] = [];
    if (props.x) tr.push(`translateX(${lerp(props.x)}px)`);
    if (props.y) tr.push(`translateY(${lerp(props.y)}px)`);
    if (props.scale) tr.push(`scale(${lerp(props.scale)})`);
    if (props.rotate) tr.push(`rotate(${lerp(props.rotate)}deg)`);
    const f: Keyframe = {};
    if (tr.length) f.transform = tr.join(" ");
    if (props.opacity) f.opacity = String(Math.min(1, Math.max(0, lerp(props.opacity))));
    if (props.blur) f.filter = `blur(${Math.max(0, lerp(props.blur))}px)`;
    return f;
  });
  return el.animate(frames, {
    duration: samples.length * (1000 / 60),
    delay: delayMs,
    easing: "linear",
    fill: "both",
  });
}

type Runner = (el: Element | null, props: SpringProps, sp: Spring,
               delay?: number) => void;

/* one wave: run animations, then cancel them all (elements return to
   stylesheet values) once settled — with a hard deadline failsafe */
export function wave(ttl: number, build: (run: Runner) => void): void {
  if (reducedMotion()) return;
  const anims: Animation[] = [];
  try {
    build((el, props, sp, delay = 0) => {
      if (el) anims.push(springAnim(el, props, sp, delay));
    });
  } catch { /* never block the UI on animation errors */ }
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    anims.forEach((a) => { try { a.cancel(); } catch { /* detached */ } });
  };
  void Promise.all(anims.map((a) => a.finished.catch(() => undefined)))
    .then(finish, finish);
  setTimeout(finish, ttl);
}

const q = (sel: string, root: ParentNode): Element[] =>
  Array.prototype.slice.call(root.querySelectorAll(sel));
const shown = (el: Element | null): boolean =>
  !!el && (el as HTMLElement).getClientRects().length > 0;

/* ------------------------------------------------- page entrance
   Declarative hooks, applied per route change:
     data-anim="title"  → hero text: rises with a blur-settle (greeting spec)
     data-anim="rise"   → header rows: drop in, stagger 80ms from 50ms
     data-anim="hero"   → main surface: y 44→0 scale .96→1 settle (composer spec)
     data-anim="pop"    → round/primary controls: scale 0→1 pop, stagger 60ms
     data-anim="chip"   → pills: y 18→0 scale .86→1 pop, stagger 70ms from 580ms
   Card lists animate via CSS (.anim-list) so late-mounting query results
   still get their entrance. */
export function runEntrance(scope: ParentNode): void {
  wave(2600, (run) => {
    q('[data-anim="title"]', scope).filter(shown).forEach((el, i) =>
      run(el, { opacity: [0, 1], y: [26, 0], blur: [8, 0] }, SETTLE, 120 + i * 85));
    q('[data-anim="rise"]', scope).filter(shown).forEach((el, i) =>
      run(el, { opacity: [0, 1], y: [-16, 0] }, GLIDE, 50 + i * 80));
    q('[data-anim="hero"]', scope).filter(shown).forEach((el, i) =>
      run(el, { opacity: [0, 1], y: [44, 0], scale: [0.96, 1] }, SETTLE, 260 + i * 90));
    q('[data-anim="pop"]', scope).filter(shown).forEach((el, i) =>
      run(el, { scale: [0, 1] }, POP, 500 + i * 60));
    q('[data-anim="chip"]', scope).filter(shown).forEach((el, i) =>
      run(el, { opacity: [0, 1], y: [18, 0], scale: [0.86, 1] }, POP, 580 + i * 70));
  });
}

/* ------------------------------------------------- sidebar entrance
   Template spec, RTL-adapted (slides from the start edge): sidebar x 46→0
   GLIDE, its items x 22→0 stagger 40ms from 100ms, logo pop at 150ms. */
export function runSidebarEntrance(aside: HTMLElement): void {
  const rtl = getComputedStyle(aside).direction === "rtl";
  const edge = rtl ? 46 : -46;
  const item = rtl ? 22 : -22;
  wave(2200, (run) => {
    run(aside, { opacity: [0, 1], x: [edge, 0] }, GLIDE, 0);
    q("[data-anim-item]", aside).filter(shown).forEach((el, i) =>
      run(el, { opacity: [0, 1], x: [item, 0] }, GLIDE, 100 + i * 40));
    const logo = aside.querySelector("[data-anim-logo]");
    if (shown(logo)) run(logo, { scale: [0.3, 1], rotate: [-20, 0] }, POP, 150);
  });
}
