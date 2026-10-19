// Records the Parakeet AI Resume Maker demo creators play while filming (like the JobStep videos: upload the CV →
// low score → paste the job ad → the AI rewrites it, change by change → new high score), as a screen recording of
// one device: out/parakeet-ai-demo-<device>-<lang>.mp4. See README.md.
//
//   node record.mjs --device mac|windows|phone|android --lang fr|es|sl [--app http://localhost:3557] [--debug]
//
// It records the real app: the local copy of ParakeetAI's prod branch (`main`) whose creator demo
// (/resumeMaker/demo) answers every server call in the browser – no account, no AI (~/dev/parakeetai-demo).
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { SAMPLES, cvHtml } from "./samples.mjs";

const HERE = path.dirname(new URL(import.meta.url).pathname);
const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 ? process.argv[i + 1] : fallback;
};
const DEVICE = arg("device", "mac");
const LANG = arg("lang", "fr");
const APP = arg("app", "http://localhost:3557");
const PARAKEET = arg("parakeet", path.join(os.homedir(), "dev/parakeetai-demo"));
const DEBUG = process.argv.includes("--debug");
const OUT = arg("out", path.join(HERE, "out"));
/** Matched to how long each format's JobStep example shows the app (measured 19 Oct 2026, demo/README.md):
 *  short ≈ 12 s (two jump cuts, all 4 changes accepted), standard ≈ 20–24 s (the whole flow), long ≈ 40 s (all 8
 *  changes + the AI's question). */
const LENGTH = arg("length", "standard");
if (!["standard", "short", "long"].includes(LENGTH)) throw new Error(`unknown --length ${LENGTH} (short, standard or long)`);
/** For an exact length (make_targets.mjs): which parts are jump-cut, what the AI shows, and how long every look lasts.
 *  variant: full | designcut (plan/template/colour cut) | medium (plan … rewriting cut) | short (that + the end cut);
 *  content: standard (4 changes) | long (8 changes + the AI's question); pace: every look × pace. */
const VARIANT = arg("variant", LENGTH === "short" ? "short" : "full");
const CONTENT = arg("content", LENGTH === "long" ? "long" : "standard");
const PACE = Number(arg("pace", 1));
const NAME = arg("name", LENGTH === "standard" ? "" : LENGTH);
if (!["full", "designcut", "medium", "short"].includes(VARIANT)) throw new Error(`unknown --variant ${VARIANT}`);
const SHORT = VARIANT === "short";
const LONG = CONTENT === "long";
const CUT_DESIGN = VARIANT !== "full";
const CUT_JOB = VARIANT === "medium" || SHORT;
const FRAMES = path.join(HERE, "frames", `${DEVICE}-${LANG}-${VARIANT}-${CONTENT}-${PACE}`);
const ANDROID = DEVICE === "android";
const PHONE = DEVICE === "phone" || ANDROID;
const SAMPLE = SAMPLES[LANG];
if (!SAMPLE) throw new Error(`unknown --lang ${LANG} (fr, es or sl)`);

// Screen = what the video shows. The page gets the screen minus the fake browser bars drawn around it.
const SCREEN = {
  mac: { w: 1728, h: 1117, top: 44, bottom: 0, dsf: 1.15, outW: 1920 }, // MacBook Pro 16", default scaling (drawn at 1.15×: enough for a 1920 video, 2× slows the page down)
  windows: { w: 1920, h: 1080, top: 80, bottom: 0, dsf: 1, outW: 1920 }, // 1080p laptop at 100 %
  phone: { w: 393, h: 852, top: 54, bottom: 78, dsf: 3, outW: 1080 }, // iPhone 15/16, Safari
  android: { w: 360, h: 780, top: 84, bottom: 18, dsf: 3, outW: 1080 }, // Samsung Galaxy S, Chrome
}[DEVICE];
if (!SCREEN) throw new Error(`unknown --device ${DEVICE} (mac, windows, phone or android)`);
const VIEW = { width: SCREEN.w, height: SCREEN.h - SCREEN.top - SCREEN.bottom };
/** Screencast frame width: no bigger than the video needs (a 2× laptop screen at full size slows the page down). */
const CAPTURE_W = Math.round(Math.min(VIEW.width * SCREEN.dsf, SCREEN.outW * 1.15));

// ---------------------------------------------------------------- the app's own words (prod copy, per language)
const COPY = Object.values(
  await import(path.join(PARAKEET, `apps/web/src/components/resumeMaker/onboarding/onboardingCopy.${LANG}.ts`)),
)[0];

// ---------------------------------------------------------------- page helpers
const MAC_CURSOR = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="24" viewBox="0 0 26 34"><path d="M2 2 L2 27 L8.2 21.2 L12.4 31 L16.6 29.2 L12.5 19.6 L21 19.6 Z" fill="#000" stroke="#fff" stroke-width="2" stroke-linejoin="round"/></svg>`;
const WINDOWS_CURSOR = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="21" viewBox="0 0 22 32"><path d="M1.5 1.5 L1.5 25 L7 19.8 L11 28.6 L14.4 27.1 L10.5 18.5 L18 18.5 Z" fill="#fff" stroke="#000" stroke-width="1.4" stroke-linejoin="miter"/></svg>`;
const CURSOR_SVG = DEVICE === "windows" ? WINDOWS_CURSOR : MAC_CURSOR;

function initScript({ cursorSvg, laptop }) {
  const style = document.createElement("style");
  // The dev server's badges never belong in a recording; the real cursor is drawn by #demo-cursor.
  style.textContent = `nextjs-portal,.tsqd-parent-container{display:none!important}
    #demo-cursor{position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;will-change:transform;
      transition:none;filter:drop-shadow(0 1px 2px rgba(0,0,0,.35))}
    #demo-cursor svg{display:block;transform-origin:1px 1px;transition:transform .09s ease}
    #demo-cursor.down svg{transform:scale(.82)}
    html{scrollbar-width:none} ::-webkit-scrollbar{display:none}
    textarea,input{caret-color:#1d1d1f}`;
  const mount = () => {
    document.head.appendChild(style);
    if (!laptop || document.getElementById("demo-cursor")) return;
    const c = document.createElement("div");
    c.id = "demo-cursor";
    c.innerHTML = cursorSvg;
    const p = JSON.parse(sessionStorage.getItem("demo-cursor") || `[${Math.round(innerWidth * 0.62)},${Math.round(innerHeight * 0.7)}]`);
    c.style.transform = `translate(${p[0]}px,${p[1]}px)`;
    c.dataset.x = p[0];
    c.dataset.y = p[1];
    document.body.appendChild(c);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
  new MutationObserver(() => {
    if (laptop && document.body && !document.getElementById("demo-cursor")) mount();
  }).observe(document, { childList: true, subtree: true });
}

let page;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const vis = (loc) => loc.filter({ visible: true }).first();
const byText = (text, exact = true) => vis(page.getByText(text, { exact }));
const button = (name) => vis(page.getByRole("button", { name, exact: true }));
/** The step's way on: the footer's last button (Continue, Accept, Improve my resume …). */
const next = () => page.locator("footer button").filter({ visible: true }).last();
let step = 0;
let chapterClock = null;
const chapters = [];
/** Marks where a part of the demo starts, so creators know where to film. */
function chapter(name) {
  if (chapterClock) chapters.push([(Date.now() - chapterClock) / 1000, name]);
}
/** A waiting screen (reading, rewriting, rescoring – the app holds each at least 5 s) plays sped up, so it lasts
 *  about `seconds` in the video: it reads as a quick progress bar, like JobStep's demos, and never drags. */
const warps = [];
async function fastTo(fn, seconds) {
  seconds = Math.max(0.5, seconds * PACE);
  const a = chapterClock ? (Date.now() - chapterClock) / 1000 : null;
  await fn();
  if (a == null) return;
  const b = (Date.now() - chapterClock) / 1000;
  warps.push([a, b, Math.max(1, (b - a) / seconds)]);
  scal.push([a, b]);
}
/** The parts of the take that `--pace` stretches (looks, holds, waiting screens), for make_targets.mjs's maths. */
const scal = [];
async function scaled(fn) {
  const a = chapterClock ? (Date.now() - chapterClock) / 1000 : null;
  await fn();
  if (a != null) scal.push([a, (Date.now() - chapterClock) / 1000]);
}
const P = (ms) => Math.round(ms * PACE);
/** A jump cut: what `fn` does happens, but is left out of the video (the short version's way past the middle). */
async function cut(fn) {
  const a = chapterClock ? (Date.now() - chapterClock) / 1000 : null;
  await fn();
  if (a == null) return;
  const b = (Date.now() - chapterClock) / 1000;
  // a speed-up inside the cut is part of it
  for (let i = warps.length - 1; i >= 0; i--) if (warps[i][0] >= a && warps[i][1] <= b) warps.splice(i, 1);
  warps.push([a, b, 1e6]);
  cuts.push([a, b]);
  await freshFrame();
}
const cuts = [];
/** The screencast only sends a frame when the screen changes: a 2 px tick in a corner makes one right after a cut,
 *  so the picture after the cut is the one shown (the frames inside a cut are dropped in encode). */
async function freshFrame() {
  await page.evaluate(
    () =>
      new Promise((done) => {
        let el = document.getElementById("demo-tick");
        if (!el) {
          el = document.createElement("div");
          el.id = "demo-tick";
          el.style.cssText = "position:fixed;right:0;bottom:0;width:2px;height:2px;z-index:2147483647;pointer-events:none";
          document.body.appendChild(el);
        }
        let n = 0;
        const step = () => {
          el.style.background = n % 2 ? "rgba(255,255,255,.02)" : "rgba(255,255,255,.04)";
          if (++n < 6) requestAnimationFrame(step);
          else done();
        };
        requestAnimationFrame(step);
      }),
  );
}
/** Recording time → video time. */
function videoTime(t) {
  let out = t;
  for (const [a, b, f] of warps) out -= (Math.min(Math.max(t, a), b) - a) * (1 - 1 / f);
  return out;
}
async function snap(name) {
  if (DEBUG) await page.screenshot({ path: path.join(OUT, `debug-${DEVICE}-${LANG}-${String(step++).padStart(2, "0")}-${name}.png`) });
}

const rand = (a, b) => a + Math.random() * (b - a);

/** Moves the drawn cursor like a hand on a trackpad: a slightly curved path (bending either way), fast in the
 *  middle and slow at the ends, a small overshoot on longer moves that settles back onto the target. */
async function cursorTo(x, y, ms) {
  const [x0, y0] = await cursorPos();
  const dist = Math.hypot(x - x0, y - y0);
  ms = Math.round(ms * rand(0.85, 1.15));
  const over = dist > 160 ? Math.min(16, dist * 0.035) : 0;
  const ux = dist ? (x - x0) / dist : 0, uy = dist ? (y - y0) / dist : 0;
  await page.evaluate(
    ([x, y, ms, over, ux, uy, bend, skew]) =>
      new Promise((resolve) => {
        const c = document.getElementById("demo-cursor");
        if (!c) return resolve();
        const x0 = Number(c.dataset.x), y0 = Number(c.dataset.y);
        const t0 = performance.now();
        const ease = (t) => 1 - Math.pow(1 - Math.pow(t, skew), 3);
        const tx = x + ux * over, ty = y + uy * over;
        const settle = over ? 140 : 0;
        const frame = (now) => {
          const el = now - t0;
          let cx, cy;
          if (el < ms) {
            const e = ease(el / ms);
            const arc = Math.sin(Math.PI * e) * bend;
            cx = x0 + (tx - x0) * e - uy * arc;
            cy = y0 + (ty - y0) * e + ux * arc;
          } else {
            const k = Math.min(1, (el - ms) / Math.max(1, settle));
            const e = 1 - Math.pow(1 - k, 2);
            cx = tx + (x - tx) * e;
            cy = ty + (y - ty) * e;
          }
          c.style.transform = `translate(${cx}px,${cy}px)`;
          if (el < ms + settle) requestAnimationFrame(frame);
          else {
            c.style.transform = `translate(${x}px,${y}px)`;
            c.dataset.x = x;
            c.dataset.y = y;
            sessionStorage.setItem("demo-cursor", JSON.stringify([x, y]));
            resolve();
          }
        };
        requestAnimationFrame(frame);
      }),
    [x, y, ms, over, ux, uy, (Math.random() < 0.5 ? -1 : 1) * Math.min(55, dist * rand(0.05, 0.12)), rand(0.75, 0.95)],
  );
  await page.mouse.move(x, y);
}

async function cursorPos() {
  return page.evaluate(() => {
    const c = document.getElementById("demo-cursor");
    return c ? [Number(c.dataset.x), Number(c.dataset.y)] : [0, 0];
  });
}

/** Moves to an element and clicks (laptop) or taps it (phone), like a person would. */
let waitLimit = 15000;
async function click(loc, { dx = 0, dy = 0, pause = PHONE ? 110 : 75, move, timeout = waitLimit } = {}) {
  await loc.waitFor({ state: "visible", timeout });
  await loc.scrollIntoViewIfNeeded();
  const b = await loc.boundingBox();
  const x = Math.round(b.x + b.width / 2 + dx + rand(-0.12, 0.12) * Math.min(b.width, 60)),
    y = Math.round(b.y + b.height / 2 + dy + rand(-0.12, 0.12) * Math.min(b.height, 24));
  if (PHONE) {
    await sleep(pause * rand(0.8, 1.6));
    await page.touchscreen.tap(x, y);
    return;
  }
  const [x0, y0] = await cursorPos();
  const dist = Math.hypot(x - x0, y - y0);
  await cursorTo(x, y, move ?? Math.round(Math.min(420, Math.max(190, dist * 0.38))));
  await sleep(pause * rand(0.8, 1.5));
  await page.evaluate(() => document.getElementById("demo-cursor")?.classList.add("down"));
  await page.mouse.down();
  await sleep(rand(50, 90));
  await page.mouse.up();
  await page.evaluate(() => document.getElementById("demo-cursor")?.classList.remove("down"));
}

/** Rests the cursor on an element for a moment, the way you point at something you're looking at. */
async function hover(loc, ms = 900, { fx = 0.45, fy = 0.5 } = {}) {
  await loc.waitFor({ state: "visible", timeout: waitLimit });
  if (PHONE) return sleep(ms);
  const b = await loc.boundingBox();
  const [x0, y0] = await cursorPos();
  const x = Math.round(b.x + b.width * fx), y = Math.round(b.y + b.height * fy);
  await cursorTo(x, y, Math.round(Math.min(700, Math.max(320, Math.hypot(x - x0, y - y0) * 0.7))));
  await sleep(ms);
}

/** A hand on a trackpad is never perfectly still: small drifts while you look at the screen. */
async function idle(ms) {
  if (PHONE || ms < 700) return sleep(ms);
  const end = Date.now() + ms;
  while (Date.now() < end - 500) {
    const [x, y] = await cursorPos();
    const nx = Math.max(20, Math.min(VIEW.width - 20, x + Math.round((Math.random() - 0.5) * 70)));
    const ny = Math.max(20, Math.min(VIEW.height - 20, y + Math.round((Math.random() - 0.5) * 40)));
    const stepMs = Math.min(900, end - Date.now() - 300);
    if (stepMs < 300) break;
    await cursorTo(nx, ny, stepMs);
    await sleep(Math.min(400, Math.max(0, end - Date.now() - 200)));
  }
  await sleep(Math.max(0, end - Date.now()));
}


/** A finger swipe on a phone (the template carousel): quick, slightly curved, released while moving. */
async function swipe(x0, y0, dx) {
  x0 = Math.round(x0 + rand(-8, 8));
  y0 = Math.round(y0 + rand(-12, 12));
  const cdp = await page.context().newCDPSession(page);
  const touch = (type, x, y) =>
    cdp.send("Input.dispatchTouchEvent", { type, touchPoints: type === "touchEnd" ? [] : [{ x, y }] });
  await touch("touchStart", x0, y0);
  const ms = rand(180, 240), t0 = Date.now();
  for (;;) {
    const t = Math.min(1, (Date.now() - t0) / ms);
    await touch("touchMove", x0 + dx * Math.pow(t, 1.4), y0 - 6 * Math.sin(Math.PI * t));
    if (t >= 1) break;
    await sleep(14);
  }
  await touch("touchEnd");
  await cdp.detach();
}


/** What the demo person answers on the AI's question card (long demo, laptops). */
const ANSWER = { fr: "+1 200 abonnés en 5 mois", es: "+1.200 seguidores en 5 meses", sl: "+1.200 sledilcev v 5 mesecih" }[LANG];

/** Types like a person on a laptop keyboard. */
async function type(text, perChar = 45) {
  for (const ch of text) {
    await page.keyboard.type(ch);
    await sleep(perChar + (/[ ,.]/.test(ch) ? 40 : Math.random() * 35));
  }
}

/** A step that may be missing on some screen size/language: log and go on instead of failing the take. */
async function soft(name, fn) {
  waitLimit = 4000;
  try {
    await fn();
  } catch (e) {
    console.warn(`  (skipped ${name}: ${e.message.split("\n")[0]})`);
  } finally {
    waitLimit = 15000;
  }
}

// ---------------------------------------------------------------- the walkthrough (JobStep's demo, in Parakeet AI)
// About 20 s, like the app part of the JobStep videos (measured 19 Oct 2026 on 8 top videos: 10–26 s, ~20 typical).

/** Before the recording starts: the flow's opening screen, on to the upload. */
async function preroll() {
  await byText(COPY.intake.trajectory.titles.yes.key).waitFor({ timeout: 20000 });
  await sleep(500);
  await next().click();
  await byText(COPY.upload.title).waitFor();
  await sleep(700);
}

/** A short look between two actions: a phone's taps need the full beat, a laptop's cursor travel already takes part of it. */
const beat = (ms) => scaled(() => idle(Math.round(ms * PACE * (LONG ? 1.8 : 1) * (PHONE ? 1 : 0.55))));

/** Accepts up to `count` change cards (stops at "review complete"), each after a look of `pauses[i]` ms. */
async function reviewCards(pauses, count) {
  const C = COPY;
  for (let i = 0; i < count; i++) {
    const accept = button(C.rewrite.deck.accept);
    const field = vis(page.locator("main input[type=text], main input:not([type]), main textarea"));
    await Promise.race([
      accept.waitFor({ timeout: 8000 }).catch(() => {}),
      field.waitFor({ timeout: 8000 }).catch(() => {}),
      byText(C.rewrite.deck.doneTitle).waitFor({ timeout: 8000 }).catch(() => {}),
    ]);
    if (await byText(C.rewrite.deck.doneTitle).isVisible().catch(() => false)) break;
    if (i === 0) await snap("review");
    if (await field.isVisible().catch(() => false)) {
      // the AI's question (long demo): answered on a laptop; on a phone (no keyboard in the recording) passed
      await scaled(() => idle(P(PHONE ? 1300 : 900)));
      await snap("question");
      if (PHONE) {
        await click(page.locator("footer button").filter({ visible: true }).nth(-2));
      } else {
        await click(field);
        await sleep(300);
        await type(ANSWER);
        await scaled(() => idle(P(450)));
        await click(button(C.rewrite.deck.add));
      }
      await sleep(500);
      continue;
    }
    await scaled(() => idle(Math.round((pauses[i] ?? 350) * PACE * (PHONE ? 1 : 0.8))));
    await click(accept, { pause: 60 });
    await sleep(90);
  }
}

async function scenes() {
  const C = COPY;
  // 1. Upload the CV (the file picker is answered with the made-up CV)
  chapter("upload");
  await beat(450);
  await snap("upload");
  await click(PHONE ? byText(C.upload.dropTitlePhone) : byText(C.upload.browse));

  // 2. Reading + scoring
  await fastTo(() => byText(C.score.title).waitFor({ timeout: 40000 }), LONG ? 2 : 1.1);

  // 3. The low score
  chapter("low score");
  await scaled(() => sleep(Math.max(1100, P(PHONE ? 1500 : 1300)))); // the gauge fills
  await snap("score");
  if (LONG && !PHONE)
    await soft("score bars", async () => {
      const bars = page.locator("main").getByText(/\d+\s*\/\s*(20|15)$/).filter({ visible: true });
      await hover(bars.first(), P(650), { fx: 0.2 });
      await hover(bars.last(), P(550), { fx: 0.2 });
    });
  await beat(700);
  await click(next());

  // 4. The plan, a template (Modern, coloured header), its colour (green) – cut in the shorter versions
  const design = async () => {
    await byText(C.plan.title).waitFor();
    await beat(350);
    await click(next());
    chapter("template");
    await byText(C.template.title).waitFor();
    await beat(250);
    if (PHONE) {
      await soft("template swipe", () => swipe(VIEW.width * 0.74, VIEW.height * 0.45, -VIEW.width * 0.5));
      await sleep(450);
      if (!(await page.getByText("Modern", { exact: true }).filter({ visible: true }).count()))
        await soft("template pick", () => click(button("Modern")));
    } else {
      await click(vis(page.locator("main").getByText("Modern", { exact: true })));
    }
    await beat(350);
    await snap("template");
    await click(next());
    await byText(C.color.title).waitFor();
    await beat(200);
    await click(button("Forest"));
    await beat(300);
    await click(next());
  };
  // 5. Paste the job ad, rewrite for it – cut in the medium and short versions
  const job = async () => {
    chapter("job ad");
    await byText(C.job.title).waitFor();
    await beat(200);
    await click(vis(page.locator("textarea")));
    await sleep(250);
    await page.keyboard.insertText(SAMPLE.job);
    await beat(450);
    await snap("job");
    await click(next());
    await fastTo(() => button(C.rewrite.deck.accept).waitFor({ timeout: 40000 }), LONG ? 2.2 : 1.2);
  };
  if (CUT_JOB) await cut(async () => (await design(), await job()));
  else {
    if (CUT_DESIGN) await cut(design);
    else await design();
    await job();
  }

  // 6. The AI's changes, card by card (the CV on the right changes with each); all of them, quicker in the short version
  chapter("review");
  const pauses = SHORT ? [750, 700, 400, 400] : LONG ? [1100, 1300, 900, 550, 450, 400, 400, 450, 450] : [800, 850, 400, 400, 400, 400];
  await reviewCards(pauses, 12);
  // 7. The rest of the cards, review done, page fit, rescoring – cut in the short version
  const end = async () => {
    await reviewCards([], 12);
    await byText(C.rewrite.deck.doneTitle).waitFor({ timeout: 15000 });
    chapter("review done");
    await beat(350);
    await snap("done");
    await click(next());

    // page fit, then rescoring
    await fastTo(() => byText(C.fit.title).waitFor({ timeout: 40000 }), LONG ? 1.5 : 0.4);
    chapter("fit");
    await beat(250);
    await click(next());
    await vis(page.getByText(new RegExp(`^(${escapeRe(C.fit.fittedTitle(1))}|${escapeRe(C.fit.alreadyTitle)})`))).waitFor({ timeout: 15000 }).catch(() => {});
    await beat(300);
    await snap("fit");
    await click(next());
    chapter("rescoring");
    await fastTo(() => vis(page.getByText(new RegExp(`^(${escapeRe(C.result.topShape)}|${escapeRe(C.result.ready)})$`))).waitFor({ timeout: 40000 }), LONG ? 2.2 : 1.3);
  };
  if (SHORT) await cut(end);
  else await end();

  // 8. The new score
  chapter("new score");
  await scaled(() => sleep(Math.max(1900, P(2000)))); // the gauge climbs from the first score
  await snap("result");
  if (PHONE) await scaled(() => sleep(P(LONG ? 2400 : 900)));
  else await scaled(() => soft("download hover", () => hover(button(new RegExp(`^${escapeRe(COPY_DOWNLOAD())}`)), P(LONG ? 1200 : 450))));
  if (LONG) await scaled(() => idle(P(PHONE ? 600 : 800)));
}
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** The result's download button label, from the resume maker's own messages (the copy file has no key for it). */
const COPY_DOWNLOAD = () => ({ fr: "Télécharger", es: "Descargar", sl: "Prenesi" })[LANG];

// ---------------------------------------------------------------- capture
async function run({ capture }) {
  // A real device scale factor (not Playwright's emulated one): the screencast then sends full-resolution frames.
  const browser = await chromium.launch({
    args: [
      "--force-color-profile=srgb",
      "--hide-scrollbars",
      `--force-device-scale-factor=${SCREEN.dsf}`,
      `--window-size=${VIEW.width},${VIEW.height}`,
    ],
  });
  const ctx = await browser.newContext({
    viewport: null,
    hasTouch: PHONE,
    colorScheme: "light",
    locale: LANG,
    userAgent: ANDROID
      ? "Mozilla/5.0 (Linux; Android 15; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36"
      : PHONE
        ? "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
        : DEVICE === "windows"
          ? "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
          : "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15",
  });
  await ctx.addCookies([{ name: "pk_chosen_lang", value: LANG, url: APP }]);
  await ctx.addInitScript(initScript, { cursorSvg: CURSOR_SVG, laptop: !PHONE });
  // "The PDF you uploaded" beside the first score: the made-up CV, drawn as its page.
  await ctx.route("**/api/secure-file/**", (route) =>
    route.fulfill({
      contentType: "text/html; charset=utf-8",
      body: cvHtml(SAMPLE).replace(
        "</body>",
        `<script>document.documentElement.style.zoom = innerWidth / 794;</script><style>html,body{overflow:hidden}</style></body>`,
      ),
    }),
  );
  page = await ctx.newPage();
  page.on("filechooser", (chooser) => chooser.setFiles(path.join(HERE, "assets", SAMPLE.file)));
  page.on("pageerror", (e) => console.warn(`  page error: ${e.message.split("\n")[0]}`));
  await page.goto(`${APP}/resumeMaker/demo${LONG ? "?long=1" : ""}`, { waitUntil: "networkidle" });
  await sleep(1500); // fonts, hydration, entrance
  await preroll();

  const frames = [];
  let cdp;
  if (capture) {
    fs.rmSync(FRAMES, { recursive: true, force: true });
    fs.mkdirSync(FRAMES, { recursive: true });
    cdp = await ctx.newCDPSession(page);
    cdp.on("Page.screencastFrame", async ({ data, metadata, sessionId }) => {
      const file = path.join(FRAMES, `${String(frames.length).padStart(6, "0")}.jpg`);
      frames.push({ t: metadata.timestamp, file });
      fs.writeFile(file, Buffer.from(data, "base64"), () => {});
      try {
        await cdp.send("Page.screencastFrameAck", { sessionId });
      } catch {}
    });
    await cdp.send("Page.startScreencast", {
      format: "jpeg",
      quality: 90,
      everyNthFrame: 1,
      maxWidth: CAPTURE_W,
      maxHeight: Math.round((VIEW.height * CAPTURE_W) / VIEW.width),
    });
  }
  const t0 = Date.now();
  if (capture) chapterClock = t0;
  await scenes();
  await sleep(250);
  const seconds = (Date.now() - t0) / 1000;
  if (capture) await cdp.send("Page.stopScreencast");
  await sleep(500);
  await browser.close();
  return { frames, seconds };
}

// ---------------------------------------------------------------- the device's own bars around the page
const FONT = `-apple-system,BlinkMacSystemFont,'SF Pro Text','Helvetica Neue',Helvetica,Arial,sans-serif`;
const DOMAIN = "parakeet-ai.com";
const barsFile = () => path.join(HERE, "frames", `bars-${DEVICE}.png`);

async function drawBars() {
  const browser = await chromium.launch();
  const p = await browser.newPage({ viewport: { width: SCREEN.w, height: SCREEN.h }, deviceScaleFactor: SCREEN.dsf });
  await p.setContent({ mac: macBarsHtml, windows: windowsBarsHtml, phone: phoneBarsHtml, android: androidBarsHtml }[DEVICE]());
  await p.screenshot({ path: barsFile(), omitBackground: true });
  await browser.close();
}

function macBarsHtml() {
  return `<html><body style="margin:0;background:transparent;font-family:${FONT}">
  <div style="height:${SCREEN.top}px;background:#f6f6f7;border-bottom:1px solid #dcdce0;display:flex;align-items:center;padding:0 16px;gap:18px;box-sizing:border-box">
    <div style="display:flex;gap:8px">${["#ff5f57", "#febc2e", "#28c840"].map((c) => `<span style="width:11px;height:11px;border-radius:50%;background:${c};display:block"></span>`).join("")}</div>
    <div style="display:flex;gap:14px;color:#8a8a8e;font-size:18px;margin-left:10px">&#x2039;&nbsp;&nbsp;&#x203A;</div>
    <div style="flex:1;display:flex;justify-content:center">
      <div style="width:440px;height:28px;border-radius:8px;background:#e9e9ec;display:flex;align-items:center;justify-content:center;gap:7px;color:#1d1d1f;font-size:13px">
        <svg width="11" height="13" viewBox="0 0 11 13"><rect x="1" y="5.5" width="9" height="7" rx="1.6" fill="#6e6e73"/><path d="M3 5.6V4a2.5 2.5 0 0 1 5 0v1.6" stroke="#6e6e73" stroke-width="1.5" fill="none"/></svg>
        ${DOMAIN}</div></div>
    <div style="width:96px;display:flex;justify-content:flex-end;gap:16px;color:#8a8a8e;font-size:17px">&#x2B06;&#xFE0E;&nbsp;&#xFF0B;</div>
  </div></body></html>`;
}
const FAVICON = () => `data:image/png;base64,${fs.readFileSync(path.join(HERE, "assets", "parakeet-favicon.png")).toString("base64")}`;
function windowsBarsHtml() {
  const icon = (d, size = 16) =>
    `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="#474747" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
  return `<html><body style="margin:0;background:transparent;font-family:'Segoe UI Variable','Segoe UI',${FONT}">
  <div style="height:${SCREEN.top}px;display:flex;flex-direction:column">
    <div style="height:40px;background:#dfe3e8;display:flex;align-items:flex-end;padding-left:8px">
      <div style="width:240px;height:34px;background:#fff;border-radius:9px 9px 0 0;display:flex;align-items:center;gap:9px;padding:0 10px;box-sizing:border-box;font-size:12px;color:#1f1f1f">
        <img src="${FAVICON()}" style="width:16px;height:16px"><span style="flex:1">ParakeetAI</span><span style="color:#5f6368;font-size:13px">&#x2715;</span></div>
      <div style="width:34px;height:34px;display:flex;align-items:center;justify-content:center;color:#474747;font-size:18px">+</div>
      <div style="flex:1"></div>
      ${["&#x2014;", "&#x25A2;", "&#x2715;"].map((g) => `<div style="width:46px;height:40px;display:flex;align-items:center;justify-content:center;color:#1f1f1f;font-size:13px;align-self:flex-start">${g}</div>`).join("")}
    </div>
    <div style="height:40px;background:#fff;border-bottom:1px solid #e3e3e3;display:flex;align-items:center;gap:16px;padding:0 14px;box-sizing:border-box">
      ${icon('<path d="M19 12H5M12 19l-7-7 7-7"/>')}${icon('<path d="M5 12h14M12 5l7 7-7 7"/>', 16).replace('stroke="#474747"', 'stroke="#b4b4b4"')}${icon('<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>')}
      <div style="flex:1;height:30px;border-radius:15px;background:#eef1f5;display:flex;align-items:center;gap:10px;padding:0 14px;font-size:14px;color:#1f1f1f">
        ${icon('<path d="M4 7h10M4 17h16M18 7h2M8 17"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>', 14)}${DOMAIN}<span style="color:#5f6368">/resumeMaker/start</span></div>
      ${icon('<path d="M12 3l2.7 5.6 6.2.9-4.5 4.4 1 6.1L12 17.1 6.6 20l1-6.1L3.1 9.5l6.2-.9z"/>')}
      <div style="width:24px;height:24px;border-radius:50%;background:#c9b8f5"></div>
      <div style="color:#474747;font-size:18px;line-height:1">&#x22EE;</div>
    </div>
  </div></body></html>`;
}
function androidBarsHtml() {
  const ROBOTO = `'Roboto','Google Sans',${FONT}`;
  const i = (d, w = 16, h = 16, vb = "0 0 24 24") => `<svg width="${w}" height="${h}" viewBox="${vb}">${d}</svg>`;
  return `<html><body style="margin:0;background:transparent;font-family:${ROBOTO}">
  <div style="position:absolute;top:0;left:0;right:0;height:${SCREEN.top}px;background:#fff">
    <div style="height:28px;display:flex;align-items:center;justify-content:space-between;padding:0 16px 0 18px;font-size:13.5px;color:#1f1f1f;font-weight:500">
      <span>12:41</span>
      <span style="display:flex;align-items:center;gap:5px">
        ${i('<path d="M12 18.5 9.2 15.6a4 4 0 0 1 5.6 0zM5.6 12a9.1 9.1 0 0 1 12.8 0l-1.8 1.8a6.6 6.6 0 0 0-9.2 0zM2 8.4a14.2 14.2 0 0 1 20 0l-1.8 1.8a11.6 11.6 0 0 0-16.4 0z" fill="#1f1f1f"/>', 15, 15)}
        ${i('<path d="M2 21h3v-5H2zm5 0h3V12H7zm5 0h3V8h-3zm5 0h3V3h-3z" fill="#1f1f1f"/>', 14, 14)}
        <span style="display:flex;align-items:center;gap:2px">${i('<rect x="1" y="5" width="18" height="11" rx="2.5" fill="none" stroke="#1f1f1f" stroke-width="1.6"/><rect x="3" y="7" width="12" height="7" rx="1.2" fill="#1f1f1f"/><rect x="20" y="8.5" width="2" height="4" rx=".8" fill="#1f1f1f"/>', 20, 14, "0 0 23 20")}<span style="font-size:12px">78%</span></span>
      </span>
    </div>
    <div style="height:56px;display:flex;align-items:center;gap:12px;padding:0 10px 0 12px;box-sizing:border-box">
      ${i('<path d="M3 11.5 12 4l9 7.5M5.5 10v9.5h13V10" fill="none" stroke="#444746" stroke-width="2" stroke-linejoin="round"/>', 22, 22)}
      <div style="flex:1;height:44px;border-radius:22px;background:#eef1f6;display:flex;align-items:center;gap:10px;padding:0 14px;font-size:16px;color:#1f1f1f">
        ${i('<path d="M4 7h10M18 7h2M4 17h4M12 17h8" stroke="#444746" stroke-width="2" stroke-linecap="round"/><circle cx="16" cy="7" r="2.2" fill="none" stroke="#444746" stroke-width="2"/><circle cx="10" cy="17" r="2.2" fill="none" stroke="#444746" stroke-width="2"/>', 18, 18)}${DOMAIN}</div>
      <div style="width:20px;height:20px;border:2px solid #444746;border-radius:5px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#444746;box-sizing:border-box">1</div>
      <div style="color:#444746;font-size:20px;line-height:1">&#x22EE;</div>
    </div>
  </div>
  <div style="position:absolute;bottom:0;left:0;right:0;height:${SCREEN.bottom}px;background:#fff;display:flex;align-items:center;justify-content:center">
    <div style="width:108px;height:4px;border-radius:2px;background:#1f1f1f;opacity:.85"></div>
  </div></body></html>`;
}
function phoneBarsHtml() {
  return `<html><body style="margin:0;background:transparent;font-family:${FONT}">
  <div style="position:absolute;top:0;left:0;right:0;height:${SCREEN.top}px;background:#fff;display:flex;align-items:flex-end;justify-content:space-between;padding:0 30px 10px 44px;box-sizing:border-box">
    <span style="font-weight:600;font-size:17px;color:#000">9:41</span>
    <span style="display:flex;gap:6px;align-items:center">
      <svg width="18" height="12" viewBox="0 0 18 12">${[0, 1, 2, 3].map((i) => `<rect x="${i * 4.8}" y="${9 - i * 3}" width="3.2" height="${3 + i * 3}" rx="1" fill="#000"/>`).join("")}</svg>
      <svg width="16" height="12" viewBox="0 0 16 12"><path d="M8 11.5 5.6 9a3.4 3.4 0 0 1 4.8 0zM3.4 6.8a6.5 6.5 0 0 1 9.2 0l-1.4 1.4a4.5 4.5 0 0 0-6.4 0zM1.1 4.5a9.8 9.8 0 0 1 13.8 0l-1.4 1.4a7.8 7.8 0 0 0-11 0z" fill="#000"/></svg>
      <svg width="27" height="13" viewBox="0 0 27 13"><rect x=".5" y=".5" width="23" height="12" rx="3.6" fill="none" stroke="#000" opacity=".4"/><rect x="2" y="2" width="17" height="9" rx="2.2" fill="#000"/><path d="M25 4.5v4a2 2 0 0 0 0-4" fill="#000" opacity=".5"/></svg>
    </span>
  </div>
  <div style="position:absolute;bottom:0;left:0;right:0;height:${SCREEN.bottom}px;background:rgba(255,255,255,.96);border-top:1px solid #e3e3e6;display:flex;justify-content:center;padding-top:9px;box-sizing:border-box">
    <div style="width:350px;height:40px;border-radius:20px;background:#ececef;display:flex;align-items:center;justify-content:space-between;padding:0 14px;box-sizing:border-box;color:#1d1d1f;font-size:16px">
      <span style="font-size:15px;color:#3a3a3c">aA</span>
      <span style="display:flex;align-items:center;gap:6px"><svg width="10" height="12" viewBox="0 0 11 13"><rect x="1" y="5.5" width="9" height="7" rx="1.6" fill="#6e6e73"/><path d="M3 5.6V4a2.5 2.5 0 0 1 5 0v1.6" stroke="#6e6e73" stroke-width="1.5" fill="none"/></svg>${DOMAIN}</span>
      <span style="font-size:16px;color:#3a3a3c">&#x21BB;</span>
    </div>
  </div></body></html>`;
}

function encode(frames, seconds) {
  fs.mkdirSync(OUT, { recursive: true });
  // Screencast timestamps are wall-clock seconds; chapterClock started at the same moment as the scenes.
  const base = chapterClock / 1000;
  const vt = (t) => videoTime(t - base);
  const end = base + seconds + 0.2;
  // nothing captured inside a jump cut is shown
  frames = frames.filter((f) => !cuts.some(([a, b]) => f.t - base > a && f.t - base <= b));
  const lines = ["ffconcat version 1.0"];
  frames.forEach((f, i) => {
    const nextT = i + 1 < frames.length ? frames[i + 1].t : end;
    lines.push(`file '${f.file}'`, `duration ${Math.max(0.001, vt(nextT) - vt(f.t)).toFixed(4)}`);
  });
  lines.push(`file '${frames.at(-1).file}'`);
  const list = path.join(FRAMES, "list.txt");
  fs.writeFileSync(list, lines.join("\n"));
  const outFile = path.join(OUT, `parakeet-ai-demo-${DEVICE}-${LANG}${NAME ? `-${NAME}` : ""}.mp4`);
  const px = (v) => Math.round(v * SCREEN.dsf);
  const W = px(SCREEN.w), H = px(SCREEN.h);
  const filter =
    `[0:v]format=rgb24,scale=${W}:${H - px(SCREEN.top) - px(SCREEN.bottom)}:flags=lanczos,format=rgb24,pad=${W}:${H}:0:${px(SCREEN.top)}:white,fps=60[page];` +
    `[page][1:v]overlay=0:0,scale=${SCREEN.outW}:-2:flags=lanczos,format=yuv420p[v]`;
  execFileSync("ffmpeg", [
    "-v", "error", "-y",
    "-f", "concat", "-safe", "0", "-i", list,
    "-loop", "1", "-i", barsFile(),
    "-filter_complex", filter, "-map", "[v]",
    "-t", String(videoTime(seconds)),
    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-movflags", "+faststart",
    outFile,
  ], { stdio: "inherit" });
  return outFile;
}

if (!process.argv.includes("--no-warm")) {
  console.log("warm-up run (compiles every screen once)…");
  await run({ capture: false });
}
console.log(`recording ${DEVICE} ${LANG}…`);
const { frames, seconds } = await run({ capture: true });
console.log(`${frames.length} frames in ${seconds.toFixed(1)} s (${(frames.length / seconds).toFixed(1)} fps)`);
await drawBars();
const video = encode(frames, seconds);
console.log(`wrote ${video} (${videoTime(seconds).toFixed(1)} s)`);
console.log(`chapters: ${chapters.map(([t, n]) => `${videoTime(t).toFixed(1)}s ${n}`).join(", ")}`);
// for make_targets.mjs: the video's length and the part of it --pace stretches
const stretchable = scal.reduce((sum, [a, b]) => sum + videoTime(b) - videoTime(a), 0);
console.log(`CALIBRATION ${JSON.stringify({ D: +videoTime(seconds).toFixed(2), B: +stretchable.toFixed(2), variant: VARIANT, content: CONTENT, pace: PACE })}`);
