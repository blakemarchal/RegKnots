/* RegKnot ad stage. Every frame is a pure function of t: window.seek(t). */
(() => {
'use strict';

// ── helpers ────────────────────────────────────────────────────────────────
const SVGNS = 'http://www.w3.org/2000/svg';
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'style') el.style.cssText = v;
    else if (k === 'html') el.innerHTML = v;
    else el.setAttribute(k, v);
  }
  for (const c of kids) el.append(c);
  return el;
}
function sv(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  for (const c of kids) el.append(c);
  return el;
}
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const prog = (t, a, b) => clamp((t - a) / (b - a));
const lerp = (a, b, e) => a + (b - a) * e;
const E = {
  lin: x => x,
  inQ: x => x * x,
  outQ: x => 1 - (1 - x) * (1 - x),
  inC: x => x * x * x,
  outC: x => 1 - Math.pow(1 - x, 3),
  ioC: x => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
  outQu: x => 1 - Math.pow(1 - x, 4),
  outX: x => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)),
  ioX: x => (x <= 0 ? 0 : x >= 1 ? 1 : x < 0.5 ? Math.pow(2, 20 * x - 10) / 2 : (2 - Math.pow(2, -20 * x + 10)) / 2),
  ioS: x => -(Math.cos(Math.PI * x) - 1) / 2,
  outB: x => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); },
  outB2: x => { const c1 = 2.4, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); },
};
// Scalar keyframes: [[t, v], [t, v, ease], ...]
function trk(t, keys) {
  if (t <= keys[0][0]) return keys[0][1];
  for (let i = 1; i < keys.length; i++) {
    const [t1, v1, e = 'ioC'] = keys[i];
    if (t < t1) {
      const [t0, v0] = keys[i - 1];
      return lerp(v0, v1, E[e](prog(t, t0, t1)));
    }
  }
  return keys[keys.length - 1][1];
}
// Object keyframes: [{t, v: {...}, e}]
function trkO(t, keys) {
  if (t <= keys[0].t) return { ...keys[0].v };
  for (let i = 1; i < keys.length; i++) {
    const k1 = keys[i];
    if (t < k1.t) {
      const k0 = keys[i - 1], p = E[k1.e || 'ioC'](prog(t, k0.t, k1.t)), o = {};
      for (const key of Object.keys(k1.v)) o[key] = lerp(k0.v[key] ?? k1.v[key], k1.v[key], p);
      return o;
    }
  }
  return { ...keys[keys.length - 1].v };
}
// in/out envelope: 0 before a, ramps to 1 over ina, holds, ramps down to 0 ending at b.
function env(t, a, b, ina = 0.3, outa = 0.3, ei = 'outC', eo = 'inC') {
  if (t < a || t > b) return 0;
  return Math.min(E[ei](prog(t, a, a + ina)), 1 - E[eo](prog(t, b - outa, b)));
}
const px = v => `${v.toFixed(2)}px`;

// ── config ─────────────────────────────────────────────────────────────────
const params = new URLSearchParams(location.search);
const CUT = params.get('cut') || 'main';
const DEBUG = params.has('debug');
const ASSETS = params.get('assets') || 'assets/';
const W = 1080, H = 1920;
const stage = document.getElementById('stage');
const EVENTS = [];
const ev = (t, type, extra = {}) => EVENTS.push({ t: +t.toFixed(3), type, ...extra });
const scenes = [];
const updaters = [];         // global per-frame updaters (run after scenes)
function addScene(t0, t1, el, update, z = 10) {
  el.classList.add('layer');
  el.style.zIndex = z;
  stage.append(el);
  scenes.push({ t0, t1, el, update });
}

const Q1 = 'Does a new deckhand need a safety orientation before we get underway?';
const Q2 = 'What records does a Subchapter M towboat have to keep?';

// ── global background ──────────────────────────────────────────────────────
const bg = h('div', { id: 'bg', class: 'layer' });
const grid = h('div', { id: 'grid', class: 'layer' });
stage.append(bg, grid);

// Depth-contour blobs, drifting slowly.
const contours = sv('svg', { id: 'contours', class: 'layer', width: W, height: H + 400, viewBox: `0 0 ${W} ${H + 400}` });
(() => {
  const r = rng(11);
  const blob = (cx, cy, rad, scale) => {
    const pts = [];
    const n = 14;
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      const rr = rad * scale * (0.78 + 0.44 * r());
      pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr * 0.8]);
    }
    let d = '';
    for (let i = 0; i < n; i++) {
      const p0 = pts[(i - 1 + n) % n], p1 = pts[i], p2 = pts[(i + 1) % n], p3 = pts[(i + 2) % n];
      if (i === 0) d += `M${p1[0].toFixed(1)},${p1[1].toFixed(1)}`;
      const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
      const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
      d += `C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
    }
    return d + 'Z';
  };
  for (const [cx, cy, rad] of [[140, 380, 260], [980, 900, 300], [260, 1500, 280], [900, 1960, 260], [520, 2150, 200]]) {
    for (const [sc, op] of [[1, 0.09], [0.72, 0.075], [0.46, 0.06], [0.22, 0.05]]) {
      contours.append(sv('path', { d: blob(cx, cy, rad, sc), fill: 'none', stroke: '#2dd4bf', 'stroke-width': 1.6, opacity: op }));
    }
  }
})();
stage.append(contours);
updaters.push(t => { contours.style.transform = `translateY(${px(-t * 7)})`; });

// ── captions ───────────────────────────────────────────────────────────────
const capLayer = h('div', { class: 'layer', style: 'z-index:60' });
stage.append(capLayer);
const capItems = [];
function caption(a, b, text, y = 300, size = 88) {
  const el = h('div', { class: 'cap', style: `top:${y}px; font-size:${size}px` });
  const words = [];
  for (const line of text.split('|')) {
    if (words.length) el.append(h('br'));
    let hl = false;
    for (const raw of line.split(' ')) {
      if (!raw) continue;
      let w = raw;
      const start = w.startsWith('*');
      if (start) { hl = true; w = w.slice(1); }
      const end = w.endsWith('*') || w.endsWith('*,') || w.endsWith('*.');
      if (end) w = w.replace('*', '');
      const span = h('span', { class: 'w' + (hl ? ' hl' : '') });
      span.textContent = w;
      el.append(span, document.createTextNode(' '));
      words.push(span);
      if (end) hl = false;
    }
  }
  capLayer.append(el);
  capItems.push({ a, b, el, words });
}
updaters.push(t => {
  for (const c of capItems) {
    const vis = t >= c.a - 0.02 && t <= c.b;
    c.el.classList.toggle('hide', !vis);
    if (!vis) continue;
    const q = E.inC(prog(t, c.b - 0.2, c.b));
    c.words.forEach((w, i) => {
      const p = E.outC(prog(t, c.a + i * 0.045, c.a + i * 0.045 + 0.32));
      w.style.opacity = (p * (1 - q)).toFixed(3);
      w.style.transform = `translateY(${px((1 - p) * 40 - q * 26)})`;
      w.style.filter = p < 1 ? `blur(${px((1 - p) * 9)})` : 'none';
    });
  }
});

// Top scrim so captions stay readable when the phone rises into their zone.
const scrim = h('div', { class: 'layer', style: 'z-index:55; background:linear-gradient(180deg, rgba(8,11,21,0.96) 0px, rgba(8,11,21,0.88) 330px, rgba(8,11,21,0) 470px); opacity:0' });
stage.append(scrim);
const scrimKeys = [];
updaters.push(t => { scrim.style.opacity = scrimKeys.reduce((m, [a, b]) => Math.max(m, env(t, a, b, 0.35, 0.35)), 0).toFixed(3); });

// "Real answer · sped up" — honest labelling of the screen footage.
const realChip = h('div', { class: 'realchip', style: 'left:0; top:0; z-index:62' }, h('b'), document.createTextNode('REAL ANSWER'), h('span', {}, '· SPED UP'));
stage.append(realChip);
const realKeys = [];
updaters.push(t => {
  const o = realKeys.reduce((m, [a, b]) => Math.max(m, env(t, a, b, 0.3, 0.3)), 0);
  realChip.style.opacity = o.toFixed(3);
  realChip.style.display = o > 0 ? 'flex' : 'none';
  realChip.style.left = '50%';
  realChip.style.top = '138px';
  realChip.style.transform = 'translateX(-50%)';
});

// ── overlays: vignette, grain, flash ───────────────────────────────────────
const vignette = h('div', { id: 'vignette', class: 'layer', style: 'z-index:80' });
const grainC = h('canvas', { id: 'grain', width: 540, height: 960, style: 'z-index:81' });
const flash = h('div', { id: 'flash', class: 'layer', style: 'z-index:82' });
stage.append(vignette, grainC, flash);
const gctx = grainC.getContext('2d');
const grainFrames = [];
(() => {
  const r = rng(99);
  for (let f = 0; f < 6; f++) {
    const img = gctx.createImageData(540, 960);
    for (let i = 0; i < img.data.length; i += 4) {
      const v = 128 + (r() - 0.5) * 255;
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
      img.data[i + 3] = 255;
    }
    grainFrames.push(img);
  }
})();
const flashes = [];
const flashAt = (t, dur = 0.3, peak = 0.3) => flashes.push([t, dur, peak]);
updaters.push((t, f) => {
  gctx.putImageData(grainFrames[f % grainFrames.length], 0, 0);
  let o = 0;
  for (const [a, d, p] of flashes) if (t >= a && t < a + d) o = Math.max(o, p * (1 - E.outC(prog(t, a, a + d))));
  flash.style.opacity = o.toFixed(3);
});

// ── icons ──────────────────────────────────────────────────────────────────
const ICON = {
  mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="1" width="6" height="14" rx="3"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>',
  clip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>',
  anchor: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="5" r="3"/><line x1="12" y1="22" x2="12" y2="8"/><path d="M5 12H2a10 10 0 0 0 20 0h-3"/></svg>',
  chev: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" style="width:24px;height:24px;opacity:.7"><polyline points="6 9 12 15 18 9"/></svg>',
  lines: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="16" y2="12"/><line x1="4" y1="17" x2="12" y2="17"/></svg>',
};
const MARK_SVG = (() => {
  // Brand mark (apps/web/public/brand/logo-mark-teal-transparent.svg), split so parts can animate.
  return `<svg viewBox="0 0 120 120" fill="none" style="width:100%;height:100%;overflow:visible">
  <g class="m-ring" style="transform-origin:60px 60px" stroke="#2dd4bf"><circle cx="60" cy="60" r="56" stroke-width="0.5" stroke-dasharray="3 7"/></g>
  <g class="m-grid" stroke="#2dd4bf">
    <circle cx="60" cy="60" r="34" stroke-width="0.5"/>
    <line x1="60" y1="4" x2="60" y2="116" stroke-width="0.5"/><line x1="4" y1="60" x2="116" y2="60" stroke-width="0.5"/>
    <line x1="20" y1="20" x2="100" y2="100" stroke-width="0.3"/><line x1="100" y1="20" x2="20" y2="100" stroke-width="0.3"/>
  </g>
  <g class="m-star" style="transform-origin:60px 60px">
    <path d="M60 6 L65 52 L60 57 L55 52 Z" fill="#2dd4bf"/>
    <path d="M60 114 L65 68 L60 63 L55 68 Z" fill="#2dd4bf" fill-opacity="0.45"/>
    <path d="M114 60 L68 65 L63 60 L68 55 Z" fill="#2dd4bf" fill-opacity="0.45"/>
    <path d="M6 60 L52 65 L57 60 L52 55 Z" fill="#2dd4bf" fill-opacity="0.45"/>
    <path d="M98 22 L68 56 L64 52 L71 45 Z" fill="#2dd4bf" fill-opacity="0.25"/>
    <path d="M22 22 L52 56 L56 52 L49 45 Z" fill="#2dd4bf" fill-opacity="0.25"/>
    <path d="M98 98 L68 64 L64 68 L71 75 Z" fill="#2dd4bf" fill-opacity="0.25"/>
    <path d="M22 98 L52 64 L56 68 L49 75 Z" fill="#2dd4bf" fill-opacity="0.25"/>
  </g>
  <g class="m-core"><circle cx="60" cy="60" r="4" fill="#2dd4bf"/><circle cx="60" cy="60" r="9" stroke="#2dd4bf" stroke-width="0.8"/></g>
  <text x="60" y="3.5" text-anchor="middle" font-size="7" fill="#2dd4bf" font-weight="700" font-family="'Barlow Condensed', sans-serif">N</text>
</svg>`;
})();

// ══════════════════════════════════════════════════════════════════════════
// SCENE: radar opener
// ══════════════════════════════════════════════════════════════════════════
function radarScene({ t0, t1, top = 470, heroAt = null, heroLines = null, dimAt = null, stack = null, readouts = true }) {
  const root = h('div', { id: 'radarWrap' });
  const cv = h('canvas', { id: 'radar', width: 1020, height: 1020, style: `top:${top}px` });
  root.append(cv);
  const ro1 = h('div', { class: 'readout', style: `left:70px; top:${top - 10}px` }, '04:52  UNDERWAY');
  const ro2 = h('div', { class: 'readout', style: `right:70px; top:${top - 10}px; text-align:right` }, 'HDG 358°\nSOG 5.8 KN');
  const ro3 = h('div', { class: 'readout', style: `left:70px; top:${top + 960}px` }, 'RNG 0.75 NM');
  const ro4 = h('div', { class: 'readout', style: `right:70px; top:${top + 960}px; text-align:right` }, 'M/V BAY PIONEER');
  if (readouts) root.append(ro1, ro2, ro3, ro4);
  let hero = null;
  if (heroLines) {
    hero = h('div', { class: 'hero', style: 'top:880px' });
    heroLines.forEach(l => { const s = h('span', { class: 'line', html: l }); hero.append(s); });
    root.append(hero);
  }
  let stackEls = [];
  if (stack) {
    stack.forEach(([text, at, y, size]) => {
      const el = h('div', { class: 'hero', style: `top:${y}px; font-size:${size}px`, html: text });
      root.append(el);
      stackEls.push({ el, at });
    });
  }

  const ctx = cv.getContext('2d');
  const C = 510, R = 450;
  const r = rng(5);
  // Returns: riverbanks, buoys, one oncoming target.
  const blips = [];
  for (let i = 0; i < 520; i++) {
    const side = i % 2 ? 1 : -1;
    const yy = -1.05 + r() * 2.1;
    const bank = 0.3 + 0.07 * Math.sin(yy * 2.6 + side) + 0.03 * Math.sin(yy * 9.1);
    const xx = side * (bank + Math.pow(r(), 2.2) * 0.55);
    if (xx * xx + yy * yy > 0.98) continue;
    blips.push({ x: xx, y: yy, s: 2.5 + r() * 5.5, b: 0.35 + r() * 0.6 });
  }
  for (let k = 0; k < 7; k++) {
    const yy = -0.85 + k * 0.26;
    blips.push({ x: -0.22 + 0.02 * Math.sin(k), y: yy, s: 6, b: 1, buoy: true });
    blips.push({ x: 0.23 + 0.02 * Math.cos(k), y: yy + 0.13, s: 6, b: 1, buoy: true });
  }
  const target = { x: 0.07, y: -0.62, s: 9, b: 1 };
  blips.push(target);
  const PERIOD = 2.4, A0 = -0.35;               // sweep reaches the bow at ~t=0.2
  const ang = (x, y) => (Math.atan2(x, -y) + Math.PI * 2) % (Math.PI * 2);

  function draw(t) {
    ctx.clearRect(0, 0, 1020, 1020);
    const sweep = ((t / PERIOD) * Math.PI * 2 + A0 + Math.PI * 4) % (Math.PI * 2);
    ctx.save();
    ctx.beginPath(); ctx.arc(C, C, R, 0, Math.PI * 2); ctx.clip();
    const g = ctx.createRadialGradient(C, C, 0, C, C, R);
    g.addColorStop(0, 'rgba(6,34,36,0.96)'); g.addColorStop(1, 'rgba(3,14,20,0.96)');
    ctx.fillStyle = g; ctx.fillRect(0, 0, 1020, 1020);
    // afterglow wedges
    const trail = 1.1, steps = 48;
    for (let i = 0; i < steps; i++) {
      const a1 = sweep - (i / steps) * trail, a0 = sweep - ((i + 1) / steps) * trail;
      ctx.beginPath(); ctx.moveTo(C, C);
      ctx.arc(C, C, R, a0 - Math.PI / 2, a1 - Math.PI / 2);
      ctx.closePath();
      ctx.fillStyle = `rgba(45,212,191,${(0.2 * Math.pow(1 - i / steps, 1.8)).toFixed(4)})`;
      ctx.fill();
    }
    // blips
    for (const b of blips) {
      const a = ang(b.x, b.y);
      const d = (sweep - a + Math.PI * 4) % (Math.PI * 2);
      const fresh = Math.exp(-d / 1.9);
      const lum = b.buoy ? 0.25 + 0.75 * fresh : b.b * (0.12 + 0.88 * fresh);
      const x = C + b.x * R, y = C + b.y * R;
      ctx.fillStyle = b.buoy ? `rgba(255,226,140,${lum.toFixed(3)})` : `rgba(94,234,212,${lum.toFixed(3)})`;
      ctx.beginPath(); ctx.arc(x, y, b.s * (b === target ? 1 : 0.8), 0, Math.PI * 2); ctx.fill();
    }
    // target vector + ARPA box
    const tx = C + target.x * R, ty = C + target.y * R;
    ctx.strokeStyle = 'rgba(94,234,212,0.85)'; ctx.lineWidth = 2;
    ctx.strokeRect(tx - 16, ty - 16, 32, 32);
    ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(tx - 12, ty + 90); ctx.stroke();
    // rings + bearing lines
    ctx.lineWidth = 1.5;
    for (let k = 1; k <= 4; k++) {
      ctx.strokeStyle = `rgba(45,212,191,${k === 4 ? 0.35 : 0.16})`;
      ctx.setLineDash(k === 4 ? [] : [6, 8]);
      ctx.beginPath(); ctx.arc(C, C, (R * k) / 4, 0, Math.PI * 2); ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.strokeStyle = 'rgba(45,212,191,0.12)';
    for (let k = 0; k < 12; k++) {
      const a = (k / 12) * Math.PI * 2;
      ctx.beginPath(); ctx.moveTo(C, C); ctx.lineTo(C + Math.sin(a) * R, C - Math.cos(a) * R); ctx.stroke();
    }
    ctx.strokeStyle = 'rgba(160,255,240,0.55)'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(C, C); ctx.lineTo(C, C - R); ctx.stroke();       // heading line
    // own tow: towboat + 3x2 barges ahead
    ctx.strokeStyle = 'rgba(230,255,250,0.95)'; ctx.fillStyle = 'rgba(45,212,191,0.35)'; ctx.lineWidth = 2.2;
    const bw = 24, bl = 58;
    for (let row = 0; row < 3; row++) for (let col = 0; col < 2; col++) {
      const x = C - bw + col * bw, y = C - 26 - (row + 1) * bl;
      ctx.fillRect(x + 1, y + 1, bw - 2, bl - 2); ctx.strokeRect(x + 1, y + 1, bw - 2, bl - 2);
    }
    ctx.beginPath();
    ctx.moveTo(C - 16, C - 24); ctx.lineTo(C + 16, C - 24); ctx.lineTo(C + 16, C + 18);
    ctx.quadraticCurveTo(C, C + 34, C - 16, C + 18); ctx.closePath(); ctx.fill(); ctx.stroke();
    // sweep line
    ctx.shadowColor = 'rgba(94,234,212,0.9)'; ctx.shadowBlur = 16;
    ctx.strokeStyle = 'rgba(170,255,240,0.95)'; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(C, C); ctx.lineTo(C + Math.sin(sweep) * R, C - Math.cos(sweep) * R); ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.restore();
    // bezel ticks + labels
    ctx.strokeStyle = 'rgba(45,212,191,0.55)';
    for (let d = 0; d < 360; d += 5) {
      const a = (d * Math.PI) / 180, len = d % 30 === 0 ? 18 : d % 10 === 0 ? 11 : 6;
      ctx.lineWidth = d % 30 === 0 ? 2 : 1;
      ctx.beginPath();
      ctx.moveTo(C + Math.sin(a) * (R + 4), C - Math.cos(a) * (R + 4));
      ctx.lineTo(C + Math.sin(a) * (R + 4 + len), C - Math.cos(a) * (R + 4 + len));
      ctx.stroke();
    }
    ctx.fillStyle = 'rgba(45,212,191,0.75)'; ctx.font = '500 22px "IBM Plex Mono"'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    for (let d = 0; d < 360; d += 30) {
      const a = (d * Math.PI) / 180;
      ctx.fillText(String(d).padStart(3, '0'), C + Math.sin(a) * (R + 42), C - Math.cos(a) * (R + 42));
    }
  }

  addScene(t0, t1, root, t => {
    draw(t);
    const lt = t - t0;
    const inP = E.outC(prog(lt, 0, 0.7));
    let dim = 1, blur = 0;
    if (dimAt != null) { const d = E.outC(prog(t, dimAt, dimAt + 0.35)); dim = 1 - 0.55 * d; blur = 3 * d; }
    const outP = E.inC(prog(t, t1 - 0.45, t1));
    cv.style.opacity = (inP * dim * (1 - outP)).toFixed(3);
    cv.style.transform = `scale(${(1.08 - 0.08 * inP + 0.25 * outP).toFixed(4)}) rotate(${(outP * 25).toFixed(2)}deg)`;
    cv.style.filter = blur > 0.05 ? `blur(${px(blur)})` : 'none';
    for (const [i, el] of [ro1, ro2, ro3, ro4].entries()) {
      const p = E.outC(prog(lt, 0.3 + i * 0.12, 0.7 + i * 0.12));
      el.style.opacity = (p * 0.9 * dim * (1 - outP)).toFixed(3);
      const txt = el.dataset.full || (el.dataset.full = el.textContent);
      el.textContent = txt.slice(0, Math.round(txt.length * E.lin(prog(lt, 0.3 + i * 0.12, 0.9 + i * 0.12))));
    }
    if (hero) {
      const p = E.outX(prog(t, heroAt, heroAt + 0.32));
      const q = E.inC(prog(t, t1 - 0.4, t1 - 0.05));
      const shake = t >= heroAt && t < heroAt + 0.45 ? (1 - prog(t, heroAt, heroAt + 0.45)) * 10 : 0;
      hero.style.opacity = (p * (1 - q)).toFixed(3);
      hero.style.transform = `translate(${px(Math.sin(t * 91) * shake)}, ${px(Math.cos(t * 73) * shake)}) scale(${(1.3 - 0.3 * p + 0.35 * q).toFixed(4)})`;
      hero.style.filter = p < 1 || q > 0 ? `blur(${px((1 - p) * 16 + q * 12)})` : 'none';
    }
    for (const { el, at } of stackEls) {
      const p = E.outX(prog(t, at, at + 0.3));
      const q = E.inC(prog(t, t1 - 0.35, t1 - 0.05));
      el.style.opacity = (p * (1 - q)).toFixed(3);
      el.style.transform = `translateY(${px((1 - p) * 60 - q * 40)}) scale(${(1.12 - 0.12 * p).toFixed(4)})`;
      el.style.filter = p < 1 || q > 0 ? `blur(${px((1 - p) * 12 + q * 10)})` : 'none';
    }
  }, 20);
  if (heroAt != null) { flashAt(heroAt, 0.28, 0.16); ev(heroAt, 'impact'); }
  ev(t0 + 0.2, 'ping'); ev(t0 + 0.2 + PERIOD, 'ping', { gain: 0.6 });
  if (!window.VO) for (const s of stackEls) ev(s.at, 'hit');   // voiced versions: the voice carries these words
}

// ══════════════════════════════════════════════════════════════════════════
// SCENE: wall of real regulation titles + counter
// ══════════════════════════════════════════════════════════════════════════
function wallScene({ t0, t1, revealDur = 0.6, count = 93702, countFrom, countTo }) {
  const root = h('div', { id: 'wall' });
  const plane = h('div', { id: 'wallPlane' });
  const regs = window.REGS;
  const cols = [];
  for (let c = 0; c < 3; c++) {
    const col = h('div', { class: 'wcol', style: `left:${40 + c * 560}px` });
    const list = regs.filter((_, i) => i % 3 === c);
    for (let rep = 0; rep < 2; rep++) for (const [sec, ttl] of list) {
      const key = sec === '46 CFR 140.410' || sec === '46 CFR 140.915';
      col.append(h('div', { class: 'wrow' + (key ? ' key' : '') }, h('span', { class: 'sec' }, sec), h('span', { class: 'ttl' }, ttl)));
    }
    plane.append(col);
    cols.push({ col, n: list.length });
  }
  root.append(plane);
  const scrimEl = h('div', { id: 'wallScrim', class: 'layer' });
  const num = h('div', { id: 'counter' }, '0');
  const lab = h('div', { id: 'counterLabel' }, 'passages of regulation');
  const chips = h('div', { id: 'srcChips' });
  const chipEls = ['46 CFR', '33 CFR', 'SOLAS', 'MARPOL', 'STCW'].map(s => { const c = h('div', { class: 'schip' }, s); chips.append(c); return c; });
  const more = h('div', { id: 'srcMore' }, '+ 60 more sources');
  root.append(scrimEl, num, lab, chips, more);

  addScene(t0, t1, root, t => {
    const lt = t - t0;
    // radar-sweep reveal
    // Continues the radar's sweep (period 2.4 s, centre 540,980) into the wall.
    const from = (((t0 / 2.4) * 360 - 20.05) % 360 + 360) % 360;
    const a = E.ioS(prog(lt, 0, revealDur)) * 360;
    root.style.webkitMaskImage = a < 359.9 ? `conic-gradient(from ${from.toFixed(1)}deg at 540px 980px, #000 0deg, #000 ${a.toFixed(1)}deg, transparent ${(a + 0.1).toFixed(1)}deg)` : 'none';
    const zoom = 1 + 0.04 * lt;
    plane.style.transform = `perspective(1800px) rotateX(20deg) rotateZ(-7deg) scale(${(1.0 * zoom).toFixed(4)})`;
    plane.style.opacity = '0.8';
    cols.forEach(({ col, n }, i) => {
      const hgt = n * 62, speed = [210, 300, 250][i];
      const y = -(((lt + 3) * speed) % hgt);
      col.style.transform = `translateY(${px(y)})`;
    });
    const out = E.inC(prog(t, t1 - 0.45, t1));
    root.style.opacity = (1 - out).toFixed(3);
    plane.style.filter = out > 0 ? `blur(${px(out * 10)})` : 'none';
    // counter
    const cp = E.outX(prog(t, countFrom, countTo));
    num.textContent = Math.round(count * cp).toLocaleString('en-US');
    const np = E.outB(prog(t, countFrom - 0.1, countFrom + 0.35));
    num.style.opacity = clamp(np * 1.3).toFixed(3);
    num.style.transform = `scale(${(0.7 + 0.3 * np).toFixed(4)})`;
    lab.style.opacity = E.outC(prog(t, countFrom + 0.25, countFrom + 0.6)).toFixed(3);
    lab.style.letterSpacing = px(7 + 10 * (1 - E.outC(prog(t, countFrom + 0.25, countFrom + 0.9))));
    chipEls.forEach((c, i) => {
      const p = E.outB2(prog(t, countTo - 0.9 + i * 0.12, countTo - 0.6 + i * 0.12));
      c.style.opacity = clamp(p * 1.4).toFixed(3);
      c.style.transform = `translateY(${px((1 - p) * 30)}) scale(${(0.6 + 0.4 * p).toFixed(4)})`;
    });
    more.style.opacity = E.outC(prog(t, countTo, countTo + 0.35)).toFixed(3);
    scrimEl.style.opacity = E.outC(prog(t, countFrom - 0.3, countFrom + 0.2)).toFixed(3);
  }, 21);
  scrimKeys.push([t0 + 0.1, t1 - 0.1]);
  ev(t0, 'sweep');
  for (let i = 0; i < 5; i++) ev(countTo - 0.9 + i * 0.12, 'tick', { gain: 0.5 });
  ev(countFrom, 'riser', { dur: countTo - countFrom });
}

// ══════════════════════════════════════════════════════════════════════════
// SCENE: composer (big recreation of the app's input bar) with typing
// ══════════════════════════════════════════════════════════════════════════
function composerScene({ t0, t1, text, typeFrom, typeTo, sendAt, y = 820, seed = 3 }) {
  const root = h('div', {});
  const wrap = h('div', { id: 'composerWrap', style: `top:${y}px` });
  root.style.zIndex = 22;
  const chipL = h('div', { class: 'achip', html: `${ICON.anchor}<span>M/V Bay Pioneer</span>${ICON.chev}` });
  const chipR1 = h('div', { class: 'achip bold', html: `${ICON.lines}<span>Standard</span>${ICON.chev}` });
  const chipR2 = h('div', { class: 'achip bold', html: `${ICON.mic}<span>Log</span>` });
  const row = h('div', { class: 'chiprow' }, chipL, h('div', { class: 'right' }, chipR1, chipR2));
  const txt = h('div', { class: 'ctext' });
  const ripple = h('div', { class: 'ripple' });
  const send = h('div', { class: 'cbtn send', html: ICON.send });
  send.append(ripple);
  const comp = h('div', { class: 'composer' }, h('div', { class: 'cbtn', html: ICON.mic }), h('div', { class: 'cbtn', html: ICON.clip }), txt, send);
  wrap.append(row, comp);
  root.append(wrap);
  // Irregular human typing, deterministic.
  const r = rng(seed);
  const raw = [];
  let acc = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    acc += (0.7 + r() * 0.6) * (ch === ' ' ? 1.5 : 1) * (',?.'.includes(text[i - 1] || '') ? 2.2 : 1);
    raw.push(acc);
  }
  const times = raw.map(v => typeFrom + (v / acc) * (typeTo - typeFrom));
  times.forEach((tt, i) => { if (text[i] !== ' ' || i % 3 === 0) ev(tt, 'key', { gain: 0.6 + r() * 0.4 }); });
  ev(sendAt, 'tap');
  ev(sendAt + 0.05, 'whoosh');

  addScene(t0, t1, root, t => {
    const lt = t - t0;
    const inP = E.outC(prog(lt, 0, 0.45));
    const outP = E.inQ(prog(t, sendAt + 0.08, sendAt + 0.36));
    wrap.style.opacity = (inP * (1 - outP)).toFixed(3);
    wrap.style.transform = `translateY(${px((1 - inP) * 90 + outP * 160)}) scale(${(1 - 0.2 * outP).toFixed(4)})`;
    wrap.style.filter = outP > 0 ? `blur(${px(outP * 8)})` : 'none';
    row.style.opacity = E.outC(prog(lt, 0.12, 0.5)).toFixed(3);
    let n = 0;
    while (n < times.length && times[n] <= t) n++;
    const focus = E.outC(prog(t, typeFrom - 0.25, typeFrom));
    comp.style.borderColor = `rgba(${Math.round(lerp(255, 45, focus))},${Math.round(lerp(255, 212, focus))},${Math.round(lerp(255, 191, focus))},${lerp(0.1, 0.45, focus).toFixed(3)})`;
    comp.style.boxShadow = `0 30px 80px rgba(0,0,0,0.55), 0 0 ${(40 * focus).toFixed(1)}px rgba(45,212,191,${(0.25 * focus).toFixed(3)})`;
    if (t < typeFrom || t > sendAt + 0.02) {
      txt.innerHTML = '<span class="ph">Ask a regulation question…</span>';
    } else {
      txt.textContent = text.slice(0, n);
      const typing = n > 0 && n < times.length;
      if (typing || Math.floor((t - typeFrom) / 0.45) % 2 === 0) txt.append(h('span', { class: 'caret' }));
    }
    const tp = prog(t, sendAt, sendAt + 0.45);
    ripple.style.opacity = t >= sendAt ? (0.9 * (1 - tp)).toFixed(3) : '0';
    ripple.style.transform = `scale(${(0.4 + 1.1 * E.outC(tp)).toFixed(4)})`;
    const press = t >= sendAt - 0.06 && t < sendAt + 0.12 ? 0.9 : 1;
    send.style.transform = `scale(${press})`;
  }, 22);
}

// ══════════════════════════════════════════════════════════════════════════
// PHONE
// ══════════════════════════════════════════════════════════════════════════
const S = 560 / 464, BEZEL = 14, STATUS = 46;
const PHONE_W = 560 + BEZEL * 2, APP_H = 1003 * S, PHONE_H = BEZEL * 2 + STATUS + APP_H;
const PHONE_LEFT = (W - PHONE_W) / 2, PHONE_TOP = 470;
const CAM0 = { ax: 232, ay: 501.5, sx: 540, sy: PHONE_TOP + BEZEL + STATUS + 501.5 * S, k: 1, ry: 0, rz: 0, op: 1, blur: 0 };
const G = { W: 464, H: 1003, HEAD: 72, COMP: 848, CLEAN: 80 };

function makePhone() {
  const el = h('div', { class: 'phone', style: `left:${PHONE_LEFT}px; top:${PHONE_TOP}px; width:${PHONE_W}px; height:${PHONE_H}px` });
  el.append(h('div', { class: 'body' }));
  const screen = h('div', { class: 'screen', style: `left:${BEZEL}px; top:${BEZEL}px; width:560px; height:${STATUS + APP_H}px` });
  const sb = h('div', { class: 'statusbar', style: `height:${STATUS}px` });
  sb.append(h('div', { class: 'time' }, '4:52'), h('div', { class: 'island' }),
    h('div', { class: 'icons', html: `
      <svg width="30" height="18" viewBox="0 0 30 18"><rect x="0" y="12" width="5" height="6" rx="1" fill="#f5f5f5"/><rect x="8" y="8" width="5" height="10" rx="1" fill="#f5f5f5"/><rect x="16" y="4" width="5" height="14" rx="1" fill="#f5f5f5"/><rect x="24" y="0" width="5" height="18" rx="1" fill="#f5f5f5" opacity=".35"/></svg>
      <svg width="24" height="18" viewBox="0 0 24 18"><path d="M12 17l3.5-4.2a5 5 0 00-7 0z" fill="#f5f5f5"/><path d="M5.2 9.6a9.5 9.5 0 0113.6 0l-2 2.4a6.4 6.4 0 00-9.6 0z" fill="#f5f5f5"/><path d="M1.5 5.2a15 15 0 0121 0l-2 2.3a12 12 0 00-17 0z" fill="#f5f5f5"/></svg>
      <svg width="40" height="20" viewBox="0 0 40 20"><rect x="1" y="2" width="33" height="16" rx="5" fill="none" stroke="#f5f5f5" stroke-opacity=".5" stroke-width="1.5"/><rect x="3.5" y="4.5" width="22" height="11" rx="3" fill="#f5f5f5"/><rect x="36" y="7" width="3" height="6" rx="1.5" fill="#f5f5f5" opacity=".5"/></svg>` }));
  const app = h('div', { class: 'app', style: `top:${STATUS}px; transform:scale(${S})` });
  const img = (src, top, hgt, extra = '') => h('img', { src: `${ASSETS}${src}`, style: `top:${top}px; width:464px; height:${hgt}px; ${extra}` });
  const frames = {};
  for (const k of ['consult1', 'bottom', 'consult2', 'q2_top', 'menu']) { frames[k] = img(`${k}.png`, 0, 1003, 'display:none'); app.append(frames[k]); }
  const scroll = h('div', { class: 'scroll' });
  const strips = { q1: img('q1_strip.png', 8, 1649), q2: img('q2_strip.png', 8, 1117) };
  const inStrip = h('div', { style: 'position:absolute; left:0; top:8px; width:464px; height:1700px' });   // fx that scroll with the strip
  const dots = h('div', { class: 'dots' }, h('i'), h('i'), h('i'));
  scroll.append(strips.q1, strips.q2, inStrip, dots);
  const header = img('header.png', 0, 72);
  const cBusy = img('composer_busy.png', G.COMP, 155);
  const cIdle = img('composer_idle.png', G.COMP, 155);
  const fadeT = h('div', { class: 'fadeT' }), fadeB = h('div', { class: 'fadeB' });
  const dim = h('div', { class: 'dim' });
  const sheet = h('div', { class: 'sheet', style: 'top:301px; height:702px' });
  const sHead = img('sheet_head.png', 0, 119);
  const sBody = h('div', { class: 'sbody', style: 'top:119px; height:504px' });
  const sBodyImg = img('sheet_body.png', 0, 861);
  const inSheet = h('div', { style: 'position:absolute; left:0; top:0; width:464px; height:861px' });
  sBody.append(sBodyImg, inSheet);
  const sFoot = img('sheet_foot.png', 623, 79);
  sheet.append(sHead, sBody, sFoot);
  const fxi = h('div', { style: 'position:absolute; inset:0' });      // fx under the chrome-free app layer
  app.append(scroll, fadeT, fadeB, header, cBusy, cIdle, fxi, dim, sheet);
  screen.append(sb, app);
  const glare = h('div', { style: `position:absolute; inset:0; border-radius:68px; background:linear-gradient(115deg, rgba(255,255,255,0.07) 0%, rgba(255,255,255,0) 35%); pointer-events:none` });
  screen.append(glare);
  el.append(screen);
  const fxo = h('div', { class: 'fxo', style: `left:${BEZEL}px; top:${BEZEL + STATUS}px; transform:scale(${S})` });
  el.append(fxo);
  const vblur = document.getElementById('vblurDev');

  const P = { el, app, frames, scroll, strips, inStrip, dots, header, cBusy, cIdle, fadeT, fadeB, dim, sheet, sBody, sBodyImg, inSheet, fxi, fxo };
  // state: {frame, strip, scrollY, reveal, busy, dim, sheetY, sheetScroll, whip, cam}
  P.apply = st => {
    for (const [k, f] of Object.entries(frames)) f.style.display = st.frame === k ? 'block' : 'none';
    const stripMode = !st.frame;
    for (const k of ['scroll', 'header', 'fadeT', 'fadeB']) P[k].style.display = stripMode ? 'block' : 'none';
    for (const [k, s] of Object.entries(strips)) s.style.display = stripMode && st.strip === k ? 'block' : 'none';
    cBusy.style.display = stripMode && st.busy > 0.001 ? 'block' : 'none';
    cIdle.style.display = stripMode && st.busy < 0.999 ? 'block' : 'none';
    cBusy.style.opacity = st.busy;
    if (stripMode) {
      const s = strips[st.strip];
      const y = 8 - st.scrollY;
      s.style.top = px(y);
      inStrip.style.top = px(y);
      if (st.reveal != null) {
        s.style.webkitMaskImage = `linear-gradient(180deg, #000 0px, #000 ${px(st.reveal - 26)}, transparent ${px(st.reveal)})`;
        dots.style.display = st.dots > 0 ? 'flex' : 'none';
        dots.style.left = '38px';
        dots.style.top = px(y + st.reveal + 6);
        dots.childNodes.forEach((d, i) => { d.style.opacity = (st.dots * (0.35 + 0.65 * (0.5 + 0.5 * Math.sin(st.t * 9 - i * 1.3)))).toFixed(3); });
      } else {
        s.style.webkitMaskImage = 'none';
        dots.style.display = 'none';
      }
    }
    dim.style.opacity = st.dim;
    sheet.style.display = st.sheetY < 700 ? 'block' : 'none';
    sheet.style.transform = `translateY(${px(st.sheetY)})`;
    sBodyImg.style.top = px(-st.sheetScroll);
    inSheet.style.top = px(-st.sheetScroll);
    // camera
    const c = st.cam;
    const lx = BEZEL + c.ax * S, ly = BEZEL + STATUS + c.ay * S;
    const tx = c.sx - PHONE_LEFT - c.k * lx, ty = c.sy - PHONE_TOP - c.k * ly;
    el.style.transform = `translate(${px(tx)}, ${px(ty)}) scale(${c.k.toFixed(4)}) translate(${px(lx)}, ${px(ly)}) rotateY(${c.ry.toFixed(3)}deg) rotateZ(${c.rz.toFixed(3)}deg) translate(${px(-lx)}, ${px(-ly)})`;
    el.style.opacity = c.op.toFixed(3);
    const bl = [];
    if (c.blur > 0.05) bl.push(`blur(${px(c.blur)})`);
    if (st.whip > 0.02) { vblur.setAttribute('stdDeviation', `0 ${(st.whip * 12).toFixed(2)}`); bl.push('url(#vblur)'); }
    app.style.filter = bl.length ? bl.join(' ') : 'none';
    if (st.whip > 0.02) app.style.transform = `scale(${S}) translateY(${px(-st.whip * 36)})`; else app.style.transform = `scale(${S})`;
  };
  return P;
}

// ── fx primitives (raw app coordinates) ────────────────────────────────────
function hlBox(parent, x, y, w, hh, r = 7) {
  const pad = 8;
  const svg = sv('svg', { class: 'hlbox', width: w + pad * 2, height: hh + pad * 2, style: `left:${x - pad}px; top:${y - pad}px` });
  const rect = sv('rect', { x: pad, y: pad, width: w, height: hh, rx: r });
  svg.append(rect);
  parent.append(svg);
  const per = 2 * (w + hh);
  rect.setAttribute('stroke-dasharray', per);
  return {
    set(draw, op = 1, glow = 0) {
      svg.style.display = op > 0.001 && draw > 0.001 ? 'block' : 'none';
      rect.setAttribute('stroke-dashoffset', (per * (1 - draw)).toFixed(2));
      svg.style.opacity = op.toFixed(3);
      rect.style.strokeWidth = (3 + glow * 1.5).toFixed(2);
    },
  };
}
function marker(parent, x, y, w, hh) {
  const el = h('div', { class: 'marker', style: `left:${x}px; top:${y}px; width:${w}px; height:${hh}px` });
  parent.append(el);
  return { set(p, op = 1) { el.style.display = p > 0.001 && op > 0.001 ? 'block' : 'none'; el.style.transform = `scaleX(${p.toFixed(4)})`; el.style.opacity = op.toFixed(3); } };
}
function pill(parent, cx, cy, text, cls = '') {
  const el = h('div', { class: 'pill ' + cls, style: `left:${cx}px; top:${cy}px` }, text);
  parent.append(el);
  return { el, set(p, op = 1) { el.style.display = op > 0.001 && p > 0.001 ? 'block' : 'none'; el.style.opacity = (op * clamp(p * 1.5)).toFixed(3); el.style.transform = `translate(-50%,-50%) scale(${(0.6 + 0.4 * p).toFixed(4)})`; } };
}
function bigChip(parent, cx, cy, text, sub) {
  const el = h('div', { class: 'bigchip', style: `left:${cx}px; top:${cy}px` }, text);
  if (sub) el.append(h('small', {}, sub));
  parent.append(el);
  return { el, set(p, op = 1) { el.style.display = op > 0.001 && p > 0.001 ? 'block' : 'none'; el.style.opacity = (op * clamp(p * 1.4)).toFixed(3); el.style.transform = `translate(-50%,-50%) translateY(${px((1 - p) * 24)}) scale(${(0.55 + 0.45 * p).toFixed(4)})`; } };
}
function conn(parent, x1, y1, x2, y2) {
  const minx = Math.min(x1, x2) - 10, miny = Math.min(y1, y2) - 10;
  const svg = sv('svg', { class: 'conn', width: Math.abs(x2 - x1) + 20, height: Math.abs(y2 - y1) + 20, style: `left:${minx}px; top:${miny}px` });
  const my = (y1 + y2) / 2;
  const path = sv('path', { d: `M${x1 - minx},${y1 - miny} C${x1 - minx},${my - miny} ${x2 - minx},${my - miny} ${x2 - minx},${y2 - miny}` });
  svg.append(path);
  parent.append(svg);
  const len = Math.hypot(x2 - x1, y2 - y1) * 1.25 + 10;
  path.setAttribute('stroke-dasharray', len);
  return { set(p, op = 1) { svg.style.display = p > 0.001 && op > 0.001 ? 'block' : 'none'; path.setAttribute('stroke-dashoffset', (len * (1 - p)).toFixed(2)); svg.style.opacity = op.toFixed(3); } };
}
function tap(parent, x, y) {
  const f = h('div', { class: 'finger', style: `left:${x}px; top:${y}px` });
  const ring = h('div', { class: 'tapring', style: `left:${x}px; top:${y}px` });
  parent.append(f, ring);
  return {
    set(t, at) {
      const vis = t > at - 0.3 && t < at + 0.45;
      f.style.display = vis ? 'block' : 'none';
      ring.style.display = t >= at && t < at + 0.5 ? 'block' : 'none';
      const pin = E.outC(prog(t, at - 0.3, at - 0.12));
      const pout = E.inC(prog(t, at + 0.15, at + 0.45));
      const press = t >= at - 0.05 && t < at + 0.12 ? 0.82 : 1;
      f.style.opacity = (pin * (1 - pout)).toFixed(3);
      f.style.transform = `scale(${((0.6 + 0.4 * pin) * press).toFixed(4)})`;
      const rp = prog(t, at, at + 0.5);
      ring.style.opacity = (0.9 * (1 - rp)).toFixed(3);
      ring.style.transform = `scale(${(0.3 + 1.2 * E.outC(rp)).toFixed(4)})`;
    },
  };
}
function shimmer(parent, x, y) {
  // Pulsing status dot over the capture's own dot (the app pulses it while it works).
  const el = h('div', { style: `position:absolute; left:${x - 5}px; top:${y - 5}px; width:10px; height:10px; border-radius:50%; background:#5eead4; box-shadow:0 0 10px 3px rgba(45,212,191,0.8)` });
  parent.append(el);
  return { set(t, a, b) { const vis = t >= a && t < b; el.style.display = vis ? 'block' : 'none'; if (!vis) return; const p = 0.5 + 0.5 * Math.sin((t - a) * 7); el.style.opacity = (0.25 + 0.75 * p).toFixed(3); el.style.transform = `scale(${(0.8 + 0.5 * p).toFixed(3)})`; } };
}

// Side counter outside the phone (stage coordinates).
function sideCounter(parent, label) {
  const el = h('div', { class: 'sidecount', style: 'left:852px; top:760px; z-index:40' });
  const n = h('div', { class: 'n' }, '0');
  const l = h('div', { class: 'l' }, label);
  const bar = h('div', { class: 'bar' }, h('i'));
  el.append(n, l, bar);
  parent.append(el);
  return {
    set(count, total, op) {
      el.style.display = op > 0.001 ? 'block' : 'none';
      el.style.opacity = op.toFixed(3);
      el.style.transform = `translateX(${px((1 - op) * 60)})`;
      n.textContent = String(count);
      bar.firstChild.style.height = `${((count / total) * 100).toFixed(1)}%`;
    },
  };
}

// ══════════════════════════════════════════════════════════════════════════
// PHONE SCRIPTS
// ══════════════════════════════════════════════════════════════════════════
const MAX_Q1 = 8 + 1649 - 776, MAX_Q2 = 8 + 1117 - 776;
const Q1_ITEMS = [541, 572, 631, 663, 695, 727, 758, 817, 876, 934];

function phoneQ1Main({ t0, t1 }) {
  const P = makePhone();
  const root = h('div', {});
  root.append(P.el);
  const fx = P.fxo, fxi = P.fxi;
  const shim = shimmer(fxi, 40.5, 295.5);
  // vessel callout
  const bxBP = hlBox(fx, 318, 311, 130, 23);
  const bxVessel = hlBox(fx, 13, 866, 199, 34, 16);
  const plVessel = pill(fx, 232, 735, 'Answered for your vessel');
  const cnA = conn(fx, 262, 714, 383, 340);
  const cnB = conn(fx, 190, 756, 112, 860);
  // plain english markers
  const mk = [[36, 394, 366, 20], [36, 421, 392, 20], [36, 447, 384, 20]].map(([x, y, w, hh]) => marker(fx, x, y, w, hh));
  // chip callout
  const bxChip = hlBox(fx, 146, 365, 129, 25);
  const bc = bigChip(fx, 232, 700, '46 CFR 140.410', 'Safety orientation');
  const cnC = conn(fx, 210, 396, 232, 648);
  // bottom: badge + chip tap
  const bxBadge = hlBox(fx, 33, 685, 272, 32, 8);
  const tp = tap(fx, 101, 736);
  const chipFlash = h('div', { style: 'position:absolute; left:38px; top:726px; width:127px; height:21px; border-radius:4px; background:rgba(94,234,212,0.55); mix-blend-mode:screen; display:none' });
  fx.append(chipFlash);
  // sheet: (b) markers scroll with the body; eCFR link box
  const mkB = [[22, 120, 416, 21], [22, 144, 398, 21], [22, 167, 282, 21]].map(([x, y, w, hh]) => marker(P.inSheet, x, y, w, hh));
  const bxEcfr = hlBox(fx, 314, 952, 130, 24);
  const plEcfr = pill(fx, 300, 905, 'Opens the official eCFR', 'dark');
  plEcfr.el.style.textTransform = 'none';
  const counter = sideCounter(root, 'topics');

  const T = {
    enter: t0, strip: 13.8, flick: 22.2, bottomIn: 22.4, badge: 22.8, tap: 24.42, sheet: 24.55,
    bmark: 25.4, bscroll: 26.9, ecfr: 28.45, exit: 29.95,
  };
  const cam = [
    { t: t0, v: { ...CAM0, sy: CAM0.sy + 950, k: 0.9, op: 0 } },
    { t: t0 + 0.55, v: { ...CAM0 }, e: 'outC' },
    { t: 13.95, v: { ...CAM0 } },
    { t: 14.3, v: { ...CAM0, ay: 600, sy: 1115 } },
    { t: 15.65, v: { ...CAM0, ay: 600, sy: 1115 } },
    { t: 16.05, v: { ...CAM0, ay: 420, sy: 880, k: 1.16 } },
    { t: 16.8, v: { ...CAM0, ay: 420, sy: 880, k: 1.16 } },
    { t: 17.15, v: { ...CAM0, ax: 210, ay: 378, sx: 540, sy: 860, k: 1.36 } },
    { t: 19.05, v: { ...CAM0, ax: 210, ay: 378, sx: 540, sy: 860, k: 1.36 } },
    { t: 19.6, v: { ...CAM0, ry: -5 } },
    { t: 22.15, v: { ...CAM0, ry: -5 } },
    { t: 22.65, v: { ...CAM0, ax: 200, ay: 690, sy: 1100, k: 1.32 } },
    { t: 24.0, v: { ...CAM0, ax: 200, ay: 690, sy: 1100, k: 1.32 } },
    { t: 24.3, v: { ...CAM0, ax: 150, ay: 736, sy: 1150, k: 1.22 } },
    { t: 24.6, v: { ...CAM0, ax: 150, ay: 736, sy: 1150, k: 1.22 } },
    { t: 25.05, v: { ...CAM0, ay: 600, sy: 1080, k: 1.05 } },
    { t: 28.2, v: { ...CAM0, ay: 600, sy: 1080, k: 1.05 } },
    { t: 28.55, v: { ...CAM0, ax: 280, ay: 880, sy: 1180, k: 1.14 } },
    { t: T.exit, v: { ...CAM0, ax: 280, ay: 880, sy: 1180, k: 1.14 } },
    { t: t1, v: { ...CAM0, ax: 280, ay: 880, sy: 700, k: 0.82, op: 0, blur: 8 }, e: 'inC' },
  ];
  const revealKeys = [[T.strip, 195], [14.55, 398, 'outC'], [16.85, 470, 'lin'], [19.25, 530, 'lin'], [21.05, 990, 'ioS'], [22.15, 1649, 'inQ']];
  ev(T.strip, 'stream');
  ev(14.05, 'pop'); ev(14.3, 'pop', { gain: 0.7 });
  ev(17.0, 'pop'); ev(17.25, 'swoosh', { gain: 0.5 });
  ev(T.flick, 'whoosh'); ev(22.9, 'chime');
  ev(T.tap, 'tap'); ev(T.sheet, 'swoosh');
  ev(T.bscroll, 'swoosh', { gain: 0.35 });
  ev(28.5, 'pop', { gain: 0.6 });
  ev(T.exit, 'whoosh', { gain: 0.7 });
  scrimKeys.push([t0 + 0.4, T.exit + 0.3]);
  realKeys.push([T.strip - 0.1, T.flick + 0.1]);

  addScene(t0, t1, root, t => {
    const st = { t, frame: null, strip: 'q1', scrollY: 0, reveal: null, busy: 1, dim: 0, sheetY: 800, sheetScroll: 0, whip: 0, dots: 0, cam: trkO(t, cam) };
    if (t < T.strip) st.frame = 'consult1';
    else if (t < T.flick + 0.2) {
      const R = trk(t, revealKeys);
      st.reveal = R;
      st.dots = t < 22.1 ? 1 : 0;
      st.scrollY = clamp(R - 640, 0, MAX_Q1);
      if (t > T.flick) st.scrollY += E.inC(prog(t, T.flick, T.flick + 0.2)) * 400;
    } else st.frame = 'bottom';
    st.whip = t >= T.flick && t < T.flick + 0.45 ? Math.sin(Math.PI * prog(t, T.flick, T.flick + 0.45)) : 0;
    // sheet
    st.dim = E.outC(prog(t, T.sheet, T.sheet + 0.35));
    st.sheetY = t < T.sheet ? 800 : lerp(702, 0, E.outQu(prog(t, T.sheet, T.sheet + 0.5)));
    st.sheetScroll = trk(t, [[T.bscroll, 0], [T.bscroll + 1.4, 357, 'ioC']]);
    P.apply(st);

    shim.set(t, t0 + 0.3, T.strip);
    // vessel callout
    const vo = 1 - E.inC(prog(t, 15.45, 15.7));
    bxBP.set(E.outC(prog(t, 14.05, 14.35)), vo);
    bxVessel.set(E.outC(prog(t, 14.2, 14.5)), vo);
    plVessel.set(E.outB(prog(t, 14.3, 14.6)), vo);
    cnA.set(E.outC(prog(t, 14.4, 14.7)), vo);
    cnB.set(E.outC(prog(t, 14.4, 14.7)), vo);
    const mo = 1 - E.inC(prog(t, 16.75, 16.95));
    mk.forEach((m, i) => m.set(E.ioC(prog(t, 16.05 + i * 0.2, 16.3 + i * 0.2)), mo));
    const co = 1 - E.inC(prog(t, 18.95, 19.2));
    bxChip.set(E.outC(prog(t, 17.0, 17.3)), co, 0.5 + 0.5 * Math.sin(t * 8));
    cnC.set(E.outC(prog(t, 17.15, 17.45)), co);
    bc.set(E.outB(prog(t, 17.3, 17.65)), co);
    // counter: items counted as the reveal passes them
    const R = trk(t, revealKeys);
    const count = t >= T.strip ? Q1_ITEMS.filter(r => R > r + 22).length : 0;
    counter.set(count, 10, env(t, 19.3, 22.55, 0.3, 0.3));
    // bottom
    bxBadge.set(E.outC(prog(t, 22.85, 23.15)), 1 - E.inC(prog(t, 23.9, 24.1)), 0.5 + 0.5 * Math.sin(t * 7));
    tp.set(t, T.tap);
    chipFlash.style.display = t >= T.tap && t < T.tap + 0.25 ? 'block' : 'none';
    chipFlash.style.opacity = (1 - prog(t, T.tap, T.tap + 0.25)).toFixed(3);
    const bo = 1 - E.inC(prog(t, 26.75, 26.95));
    mkB.forEach((m, i) => m.set(E.ioC(prog(t, T.bmark + i * 0.3, T.bmark + 0.35 + i * 0.3)), bo));
    const eo = 1 - E.inC(prog(t, 29.7, 29.95));
    bxEcfr.set(E.outC(prog(t, T.ecfr, T.ecfr + 0.3)), eo);
    plEcfr.set(E.outB(prog(t, T.ecfr + 0.15, T.ecfr + 0.45)), eo);
  }, 30);
}

function phoneQ1Cut({ t0, t1 }) {
  const P = makePhone();
  const root = h('div', {});
  root.append(P.el);
  const fx = P.fxo;
  const shim = shimmer(P.fxi, 40.5, 295.5);
  const mk = [[36, 286, 366, 20], [36, 313, 410, 20], [36, 340, 402, 20], [36, 367, 106, 20]].map(([x, y, w, hh]) => marker(fx, x, y, w, hh));
  const bxChip = hlBox(fx, 146, 365, 129, 25);
  const bc = bigChip(fx, 232, 560, '46 CFR 140.410', 'Safety orientation');
  const cnC = conn(fx, 210, 396, 232, 510);
  // "Documentation" header, inside the strip so it scrolls with it
  const bxDoc = hlBox(P.inStrip, 34, 1377, 292, 26);
  const counter = sideCounter(root, 'topics');
  const T = { strip: t0 + 1.05, flick: null, exit: t1 - 0.3 };
  const cam = [
    { t: t0, v: { ...CAM0, sy: CAM0.sy + 950, k: 0.9, op: 0 } },
    { t: t0 + 0.5, v: { ...CAM0 }, e: 'outC' },
    { t: 6.15, v: { ...CAM0 } },
    { t: 6.5, v: { ...CAM0, ay: 350, sy: 860, k: 1.22 } },
    { t: 7.75, v: { ...CAM0, ay: 350, sy: 860, k: 1.22 } },
    { t: 8.15, v: { ...CAM0, ry: -5 } },
    { t: 9.9, v: { ...CAM0, ry: -5 } },
    { t: 10.3, v: { ...CAM0, ay: 560, sy: 1060, k: 1.12 } },
    { t: T.exit, v: { ...CAM0, ay: 560, sy: 1060, k: 1.12 } },
    { t: t1, v: { ...CAM0, ay: 560, sy: 700, k: 0.82, op: 0, blur: 8 }, e: 'inC' },
  ];
  const revealKeys = [[T.strip, 195], [6.6, 398, 'outC'], [7.9, 440, 'lin'], [10.2, 1649, 'ioS']];
  ev(T.strip, 'stream');
  ev(7.0, 'pop'); ev(7.2, 'swoosh', { gain: 0.5 });
  ev(10.35, 'pop');
  ev(T.exit, 'whoosh', { gain: 0.7 });
  scrimKeys.push([t0 + 0.4, T.exit + 0.3]);
  realKeys.push([T.strip - 0.1, T.exit]);

  addScene(t0, t1, root, t => {
    const st = { t, frame: null, strip: 'q1', scrollY: 0, reveal: null, busy: 1, dim: 0, sheetY: 800, sheetScroll: 0, whip: 0, dots: 0, cam: trkO(t, cam) };
    if (t < T.strip) st.frame = 'consult1';
    else {
      const R = trk(t, revealKeys);
      st.reveal = R;
      st.dots = R < 1640 ? 1 : 0;
      st.busy = 1 - E.lin(prog(t, 10.2, 10.35));
      st.scrollY = clamp(R - 640, 0, MAX_Q1);
    }
    P.apply(st);
    shim.set(t, t0 + 0.3, T.strip);
    const mo = 1 - E.inC(prog(t, 7.7, 7.9));
    mk.forEach((m, i) => m.set(E.ioC(prog(t, 6.45 + i * 0.16, 6.65 + i * 0.16)), mo));
    bxChip.set(E.outC(prog(t, 6.95, 7.25)), mo, 0.5 + 0.5 * Math.sin(t * 8));
    cnC.set(E.outC(prog(t, 7.1, 7.35)), mo);
    bc.set(E.outB(prog(t, 7.2, 7.5)), mo);
    const R = trk(t, revealKeys);
    const count = t >= T.strip ? Q1_ITEMS.filter(r => R > r + 22).length : 0;
    counter.set(count, 10, env(t, 7.95, 9.8, 0.3, 0.3));
    bxDoc.set(E.outC(prog(t, 10.35, 10.65)), 1 - E.inC(prog(t, T.exit, T.exit + 0.2)), 0.5 + 0.5 * Math.sin(t * 7));
  }, 30);
}

function phoneQ2Cut({ t0, t1 }) {
  const P = makePhone();
  const root = h('div', {});
  root.append(P.el);
  const fx = P.fxo;
  const shim = shimmer(P.fxi, 40.5, 268.5);
  const bxTVR1 = hlBox(fx, 312, 123, 136, 23);
  const bxTVR2 = hlBox(fx, 33, 149, 124, 23);
  const mk = [[250, 179, 178, 20], [36, 206, 150, 20]].map(([x, y, w, hh]) => marker(fx, x, y, w, hh));
  const bxChip = hlBox(P.inStrip, 218, 47, 84, 23);
  const counter = sideCounter(root, 'records');
  const T = { top: 5.95, flick: 7.45, exit: t1 - 0.3 };
  const cam = [
    { t: t0, v: { ...CAM0, sy: CAM0.sy + 950, k: 0.9, op: 0 } },
    { t: t0 + 0.5, v: { ...CAM0 }, e: 'outC' },
    { t: 6.1, v: { ...CAM0 } },
    { t: 6.45, v: { ...CAM0, ay: 190, sy: 760, k: 1.24 } },
    { t: 7.4, v: { ...CAM0, ay: 190, sy: 760, k: 1.24 } },
    { t: 7.8, v: { ...CAM0, ry: -5 } },
    { t: T.exit, v: { ...CAM0, ry: -5 } },
    { t: t1, v: { ...CAM0, sy: 700, k: 0.82, op: 0, blur: 8 }, e: 'inC' },
  ];
  ev(T.top, 'stream'); ev(6.35, 'pop');
  ev(T.flick, 'whoosh'); ev(7.95, 'pop', { gain: 0.6 });
  ev(T.exit, 'whoosh', { gain: 0.7 });
  scrimKeys.push([t0 + 0.4, T.exit + 0.3]);
  realKeys.push([T.top - 0.1, T.exit]);

  addScene(t0, t1, root, t => {
    const st = { t, frame: null, strip: 'q2', scrollY: 0, reveal: null, busy: 0, dim: 0, sheetY: 800, sheetScroll: 0, whip: 0, dots: 0, cam: trkO(t, cam) };
    if (t < T.top) st.frame = 'consult2';
    else if (t < T.flick + 0.22) st.frame = 'q2_top';
    else st.scrollY = trk(t, [[T.flick + 0.22, 0], [T.flick + 0.5, 0], [10.4, MAX_Q2, 'ioS']]);
    st.whip = t >= T.flick && t < T.flick + 0.45 ? Math.sin(Math.PI * prog(t, T.flick, T.flick + 0.45)) : 0;
    P.apply(st);
    shim.set(t, t0 + 0.3, T.top);
    const o = 1 - E.inC(prog(t, 7.25, 7.45));
    bxTVR1.set(E.outC(prog(t, 6.3, 6.6)), o);
    bxTVR2.set(E.outC(prog(t, 6.45, 6.75)), o);
    mk.forEach((m, i) => m.set(E.ioC(prog(t, 6.75 + i * 0.18, 6.98 + i * 0.18)), o));
    bxChip.set(E.outC(prog(t, 7.95, 8.25)), 1 - E.inC(prog(t, 9.0, 9.2)), 0.5 + 0.5 * Math.sin(t * 7));
    const count = Math.round(10 * E.lin(prog(t, 7.9, 10.3)));
    counter.set(count, 10, env(t, 7.8, T.exit + 0.2, 0.3, 0.3));
  }, 30);
}

// ══════════════════════════════════════════════════════════════════════════
// SCENE: nameplate (Karynn) — typographic until her own clip arrives
// ══════════════════════════════════════════════════════════════════════════
function nameplateScene({ t0, t1 }) {
  const root = h('div', {});
  const mark = h('div', { id: 'bigMark', html: MARK_SVG });
  const stripes = h('div', { class: 'stripes' }, h('i'), h('i'), h('i'), h('i'));
  const eyebrow = h('div', { class: 'eyebrow', style: 'top:760px' }, 'BUILT BY A');
  const title = h('div', { class: 'np-title', style: 'top:820px', html: '<span style="display:block">USCG Master</span><span style="display:block">Unlimited</span>' });
  const rule = h('div', { class: 'np-rule', style: 'top:1150px' });
  const name = h('div', { class: 'np-name', style: 'top:1180px' }, 'Captain Karynn Marchal');
  const sub = h('div', { class: 'np-sub', style: 'top:1290px' }, 'Active containership captain');
  root.append(mark, stripes, eyebrow, title, rule, name, sub);
  const lines = [...title.children];
  ev(t0 + 0.6, 'hit', { gain: 0.7 });
  addScene(t0, t1, root, t => {
    const lt = t - t0;
    const out = E.inC(prog(t, t1 - 0.35, t1));
    root.style.opacity = (1 - out).toFixed(3);
    root.style.transform = `translateY(${px(-out * 80)})`;
    const ring = mark.querySelector('.m-ring');
    ring.style.transform = `rotate(${(lt * 14).toFixed(2)}deg)`;
    mark.querySelector('.m-star').style.transform = `rotate(${(-8 + 8 * E.outC(prog(lt, 0, 1.2))).toFixed(2)}deg)`;
    mark.style.opacity = (0.1 * E.outC(prog(lt, 0, 0.6))).toFixed(3);
    mark.style.transform = `scale(${(1.15 - 0.15 * E.outC(prog(lt, 0, 1.5))).toFixed(4)})`;
    [...stripes.children].forEach((s, i) => {
      const p = E.outC(prog(lt, 0.1 + i * 0.07, 0.4 + i * 0.07));
      s.style.opacity = p.toFixed(3);
      s.style.transform = `scaleX(${p.toFixed(4)})`;
    });
    const ep = E.outC(prog(lt, 0.3, 0.6));
    eyebrow.style.opacity = ep.toFixed(3);
    eyebrow.style.letterSpacing = px(10 + 14 * (1 - ep));
    lines.forEach((l, i) => {
      const p = E.outX(prog(lt, 0.42 + i * 0.14, 0.82 + i * 0.14));
      l.style.opacity = p.toFixed(3);
      l.style.transform = `translateY(${px((1 - p) * 70)})`;
      l.style.filter = p < 1 ? `blur(${px((1 - p) * 10)})` : 'none';
    });
    const rp = E.ioC(prog(lt, 0.85, 1.35));
    rule.style.width = px(560 * rp);
    rule.style.marginLeft = px(-280 * rp);
    const np = E.outC(prog(lt, 1.05, 1.45));
    name.style.opacity = np.toFixed(3);
    name.style.transform = `translateY(${px((1 - np) * 30)})`;
    const sp = E.outC(prog(lt, 1.3, 1.7));
    sub.style.opacity = sp.toFixed(3);
  }, 24);
}

// ══════════════════════════════════════════════════════════════════════════
// SCENE: montage of more real screens
// ══════════════════════════════════════════════════════════════════════════
function montageScene({ t0, t1 }) {
  const root = h('div', {});
  const track = h('div', { id: 'montageTrack' });
  const items = [
    { src: 'dossier.png', h: 410, crop: 410, label: 'Your vessel profile' },
    { src: 'menu.png', h: 1003, crop: 560, label: 'Fleet · credentials · tools' },
    { src: 'q2_strip.png', h: 1117, crop: 560, label: 'Records & audits' },
  ];
  const GAP = 660;
  const panels = items.map((it, i) => {
    const scale = 600 / 464;
    const ph = it.crop * scale;
    const p = h('div', { class: 'panel', style: `left:${240 + i * GAP}px; top:${1000 - ph / 2}px; height:${ph}px` });
    p.append(h('img', { src: `${ASSETS}${it.src}`, style: `height:${it.h * scale}px` }));
    const lab = h('div', { class: 'plabel', style: `left:${240 + i * GAP}px; top:${1000 + ph / 2 + 34}px` }, it.label);
    track.append(p, lab);
    return { p, lab };
  });
  root.append(track);
  ev(t0 + 0.02, 'whoosh', { gain: 0.45 }); ev(t0 + 0.72, 'whoosh', { gain: 0.4 }); ev(t0 + 1.52, 'whoosh', { gain: 0.4 });
  addScene(t0, t1, root, t => {
    const lt = t - t0, dur = t1 - t0;
    // Pan with a pause on each panel.
    const segs = [[0, 40], [0.7, 0], [0.95, -GAP], [1.5, -GAP - 30], [1.75, -2 * GAP], [dur, -2 * GAP - 60]];
    let x = 0;
    for (let i = 1; i < segs.length; i++) {
      if (lt <= segs[i][0]) { x = lerp(segs[i - 1][1], segs[i][1], E.ioC(prog(lt, segs[i - 1][0], segs[i][0]))); break; }
      x = segs[i][1];
    }
    const inX = (1 - E.outC(prog(lt, 0, 0.4))) * 760;
    track.style.transform = `translateX(${px(x + inX)})`;
    panels.forEach(({ p, lab }, i) => {
      const cx = 240 + i * GAP + 300 + x + inX;
      const d = (cx - 540) / 620;
      p.style.transform = `perspective(1400px) rotateY(${(-d * 28).toFixed(2)}deg) scale(${(1 - Math.min(Math.abs(d), 1) * 0.14).toFixed(4)})`;
      p.style.opacity = (1 - Math.min(Math.abs(d), 1) * 0.55).toFixed(3);
      lab.style.opacity = clamp(1 - Math.abs(d) * 2.5).toFixed(3);
    });
    const out = E.inC(prog(t, t1 - 0.3, t1));
    root.style.opacity = (E.outC(prog(lt, 0, 0.25)) * (1 - out)).toFixed(3);
  }, 25);
}

// ══════════════════════════════════════════════════════════════════════════
// SCENE: company documents (fleet feature, illustrated)
// ══════════════════════════════════════════════════════════════════════════
function docsScene({ t0, t1 }) {
  const root = h('div', {});
  const panel = h('div', { class: 'wpanel', style: 'top:560px' });
  panel.append(
    h('div', { class: 'wp-head', html: `<div style="width:60px;height:60px">${MARK_SVG}</div><div class="t">Wheelhouse</div><div class="tag">FLEET</div>` }),
    h('div', { class: 'wp-sub' }, 'Company documents'),
  );
  const docs = [
    ['PDF', '#dc2626', 'Fleet SMS Manual'],
    ['PDF', '#dc2626', 'Bay Pioneer TSMS'],
    ['DOCX', '#2563eb', 'Drill & Training Procedures'],
  ].map(([ext, col, nm]) => {
    const row = h('div', { class: 'doc', style: 'position:relative' });
    row.append(h('div', { class: 'ic', html: `<b style="background:${col}">${ext}</b>` }), h('div', { class: 'nm' }, nm), h('div', { class: 'st' }, ''), h('div', { class: 'pb' }));
    panel.append(row);
    return row;
  });
  const bubble = h('div', { class: 'cbubble', style: 'top:1250px' });
  bubble.append(h('div', { class: 'q' }, 'Answers cite your own procedures, next to the regulations.'), h('div', { class: 'cchip' }, 'Company: Bay Pioneer TSMS'));
  root.append(panel, bubble);
  docs.forEach((_, i) => { ev(t0 + 0.2 + i * 0.28, 'whoosh', { gain: 0.35 }); ev(t0 + 0.95 + i * 0.28, 'tick', { gain: 0.5 }); });
  ev(t0 + 1.95, 'pop');
  addScene(t0, t1, root, t => {
    const lt = t - t0;
    const pin = E.outC(prog(lt, 0, 0.4));
    const out = E.inC(prog(t, t1 - 0.35, t1));
    panel.style.opacity = (pin * (1 - out)).toFixed(3);
    panel.style.transform = `translateY(${px((1 - pin) * 60 - out * 60)}) scale(${(0.96 + 0.04 * pin).toFixed(4)})`;
    docs.forEach((row, i) => {
      const a = 0.2 + i * 0.28;
      const p = E.outC(prog(lt, a, a + 0.4));
      row.style.opacity = p.toFixed(3);
      row.style.transform = `translateX(${px((1 - p) * -500)})`;
      const pb = prog(lt, a + 0.3, a + 0.75);
      row.querySelector('.pb').style.width = `${(pb * 100).toFixed(1)}%`;
      row.querySelector('.pb').style.opacity = (1 - prog(lt, a + 0.75, a + 0.9)).toFixed(3);
      row.querySelector('.st').textContent = pb >= 1 ? 'Ready ✓' : pb > 0 ? 'Indexing' : '';
    });
    const bp = E.outC(prog(lt, 1.9, 2.3));
    bubble.style.opacity = (bp * (1 - out)).toFixed(3);
    bubble.style.transform = `translateY(${px((1 - bp) * 40)})`;
  }, 26);
}

// ══════════════════════════════════════════════════════════════════════════
// SCENE: end card
// ══════════════════════════════════════════════════════════════════════════
function endCard({ t0, t1, variant = 'main' }) {
  const root = h('div', {});
  const Y = variant === 'main' ? 0 : 60;
  const markTop = 470 + Y;
  const rings = [0, 1, 2].map(() => { const r = h('div', { class: 'ring' }); root.append(r); return r; });
  const mark = h('div', { id: 'endMark', style: `top:${markTop}px`, html: MARK_SVG });
  const word = h('div', { class: 'wordmark', style: `top:${800 + Y}px` });
  const letters = [];
  for (const [chunk, cls] of [['REG', ''], ['KNOT', 'k']]) for (const ch of chunk) { const s = h('span', { class: cls }, ch); word.append(s); letters.push(s); }
  const wordMask = h('div', { class: 'wordmark', style: `top:${800 + Y}px; color:#eafffb; text-shadow:0 0 24px rgba(94,234,212,0.9)` }, 'REGKNOT');
  const tag = h('div', { class: 'tagline', style: `top:${975 + Y}px` }, 'MARITIME COMPLIANCE CO-PILOT');
  root.append(mark, word, wordMask, tag);
  let cta, url, ul, fine1, fine2;
  if (variant === 'main') {
    cta = h('div', { class: 'cta', style: 'top:1150px' }, 'Try it free');
    url = h('div', { class: 'url', style: 'top:1270px' }, 'regknots.com');
    fine1 = h('div', { class: 'fine', style: 'top:1420px' }, '7-day free trial · No credit card');
    fine2 = h('div', { class: 'fine b', style: 'top:1475px' }, 'Fleets: first boat free for 30 days');
  } else {
    cta = h('div', { class: 'cta', style: `top:${1150 + Y}px`, html: 'Ask <span style="color:var(--teal)">RegKnot</span>' });
    url = h('div', { class: 'url', style: `top:${1270 + Y}px` }, 'regknots.com');
    fine1 = h('div', { class: 'fine', style: `top:${1420 + Y}px` }, '7-day free trial · No credit card');
  }
  ul = h('u', {});
  url.append(ul);
  root.append(cta, url, fine1);
  if (fine2) root.append(fine2);
  // Voiced versions use a stock AI narrator (never Karynn's voice); say so.
  const aiNote = window.VO ? h('div', { class: 'fine', style: 'top:1560px; font-size:24px; opacity:0.75' }, 'Narration: AI voice') : null;
  if (aiNote) root.append(aiNote);
  flashAt(t0, 0.35, 0.22);
  ev(t0, 'impact', { big: true });
  ev(t0 + 0.9, 'shimmer');
  addScene(t0, t1, root, t => {
    const lt = t - t0;
    const mp = E.outX(prog(lt, 0, 0.7));
    mark.style.opacity = clamp(mp * 1.5).toFixed(3);
    mark.style.transform = `scale(${(1.7 - 0.7 * mp).toFixed(4)}) rotate(${(-120 * (1 - mp)).toFixed(2)}deg)`;
    mark.querySelector('.m-ring').style.transform = `rotate(${(lt * 20).toFixed(2)}deg)`;
    rings.forEach((r, i) => {
      const cyc = (lt - 0.2 - i * 0.8) / 2.4;
      const vis = cyc >= 0;
      const p = vis ? cyc % 1 : 0;
      const size = 280 + p * 700;
      r.style.display = vis ? 'block' : 'none';
      r.style.width = r.style.height = px(size);
      r.style.left = px(540 - size / 2);
      r.style.top = px(markTop + 140 - size / 2);
      r.style.opacity = (0.5 * (1 - p) * E.outC(prog(lt, 0.2, 0.6))).toFixed(3);
    });
    letters.forEach((s, i) => {
      const p = E.outX(prog(lt, 0.25 + i * 0.04, 0.65 + i * 0.04));
      s.style.opacity = p.toFixed(3);
      s.style.transform = `translateY(${px((1 - p) * 70)})`;
      s.style.filter = p < 1 ? `blur(${px((1 - p) * 8)})` : 'none';
    });
    const sp = prog(lt, 1.0, 1.75);
    wordMask.style.display = sp > 0 && sp < 1 ? 'block' : 'none';
    const sx = -10 + sp * 120;
    wordMask.style.webkitMaskImage = `linear-gradient(105deg, transparent ${(sx - 9).toFixed(1)}%, #000 ${sx.toFixed(1)}%, transparent ${(sx + 9).toFixed(1)}%)`;
    const tp = E.outC(prog(lt, 0.6, 1.0));
    tag.style.opacity = tp.toFixed(3);
    tag.style.letterSpacing = px(9 + 8 * (1 - tp));
    const cp = E.outB(prog(lt, 0.95, 1.35));
    cta.style.opacity = clamp(cp * 1.3).toFixed(3);
    cta.style.transform = `scale(${(0.8 + 0.2 * cp).toFixed(4)})`;
    const up = E.outC(prog(lt, 1.15, 1.5));
    url.style.opacity = up.toFixed(3);
    url.style.transform = `translateY(${px((1 - up) * 30)})`;
    const ulp = E.ioC(prog(lt, 1.45, 1.9));
    ul.style.width = px(560 * ulp);
    ul.style.marginLeft = px(-280 * ulp);
    ul.style.top = '96px';
    fine1.style.opacity = E.outC(prog(lt, 1.7, 2.05)).toFixed(3);
    if (fine2) fine2.style.opacity = E.outC(prog(lt, 1.95, 2.3)).toFixed(3);
    if (aiNote) aiNote.style.opacity = (0.75 * E.outC(prog(lt, 2.1, 2.5))).toFixed(3);
  }, 27);
}

// ══════════════════════════════════════════════════════════════════════════
// SCENE: Cut B opener — "TPO audit coming?"
// ══════════════════════════════════════════════════════════════════════════
function auditOpener({ t0, t1 }) {
  const root = h('div', {});
  const stamp = h('div', { class: 'stamp', style: 'left:320px; top:600px' }, 'AUDIT');
  const hero = h('div', { class: 'hero', style: 'top:880px', html: '<span class="line">TPO audit</span><span class="line hl">coming?</span>' });
  const list = h('div', { style: 'position:absolute; left:200px; top:1260px; width:680px' });
  const rows = ['Crew list & watch records', 'Safety orientation log', 'Drills & instruction'].map(t => {
    const r = h('div', { style: 'display:flex; align-items:center; gap:22px; margin:0 0 22px; font-family:var(--mono); font-size:36px; color:var(--bone)' });
    const box = h('div', { style: 'width:46px; height:46px; border-radius:10px; border:3px solid rgba(45,212,191,.6); display:flex; align-items:center; justify-content:center; color:var(--teal); font-size:34px; font-weight:700' });
    r.append(box, h('span', {}, t));
    list.append(r);
    return { r, box };
  });
  root.append(stamp, hero, list);
  ev(t0 + 0.15, 'impact');
  ev(t0 + 0.9, 'hit', { gain: 0.8 });
  rows.forEach((_, i) => ev(t0 + 1.25 + i * 0.3, 'tick'));
  addScene(t0, t1, root, t => {
    const lt = t - t0;
    const out = E.inC(prog(t, t1 - 0.35, t1 - 0.05));
    const hp = E.outX(prog(lt, 0.15, 0.5));
    hero.style.opacity = (hp * (1 - out)).toFixed(3);
    hero.style.transform = `scale(${(1.25 - 0.25 * hp + out * 0.2).toFixed(4)})`;
    hero.style.filter = hp < 1 || out > 0 ? `blur(${px((1 - hp) * 14 + out * 10)})` : 'none';
    const sp = E.outB2(prog(lt, 0.9, 1.15));
    stamp.style.opacity = (clamp(sp * 2) * (1 - out)).toFixed(3);
    stamp.style.transform = `rotate(-9deg) scale(${(2.2 - 1.2 * sp).toFixed(4)})`;
    rows.forEach(({ r, box }, i) => {
      const p = E.outC(prog(lt, 1.1 + i * 0.3, 1.4 + i * 0.3));
      r.style.opacity = (p * (1 - out)).toFixed(3);
      r.style.transform = `translateX(${px((1 - p) * 60)})`;
      box.textContent = lt > 1.25 + i * 0.3 ? '✓' : '';
    });
  }, 20);
}

// ══════════════════════════════════════════════════════════════════════════
// CUTS
// ══════════════════════════════════════════════════════════════════════════
let DURATION = 45;
// Voice-over variants (vo.py) bring their own caption timings, retimed to the speech.
const VOX = window.VO || null;
const cap = (a, b, text) => { if (!VOX) caption(a, b, text); };
const st = (i, d) => (VOX && VOX.stack && VOX.stack[i] != null ? VOX.stack[i] : d);
if (CUT === 'main') {
  DURATION = 45;
  radarScene({ t0: 0, t1: 5.1, top: 470, heroAt: 3.3, heroLines: ['Is that actually', '<span class="hl">required?</span>'], dimAt: 3.2 });
  cap(0.45, 2.2, 'Every captain gets the question');
  cap(2.2, 3.25, 'at the worst moment:');
  wallScene({ t0: 4.8, t1: 9.3, countFrom: 5.35, countTo: 7.6 });
  cap(5.0, 6.85, "The answer's in there somewhere.");
  cap(6.85, 8.8, '*Thousands* of pages of it.');
  composerScene({ t0: 9.0, t1: 12.6, text: Q1, typeFrom: 9.45, typeTo: 11.95, sendAt: 12.15 });
  cap(9.1, 10.55, 'So I ask *RegKnot*,');
  cap(10.55, 12.45, "the way I'd ask another captain.");
  phoneQ1Main({ t0: 12.2, t1: 30.4 });
  cap(13.9, 15.6, 'It answers for *my vessel*,');
  cap(15.6, 16.85, 'in plain English,');
  cap(16.85, 19.2, "and it shows exactly *where it's written.*");
  cap(24.1, 25.3, 'Tap the citation,');
  cap(25.3, 27.7, "and there's *the regulation itself.*");
  nameplateScene({ t0: 30.0, t1: 33.9 });
  montageScene({ t0: 33.6, t1: 36.25 });
  cap(33.7, 36.0, 'We built RegKnot for *working mariners*,');
  docsScene({ t0: 36.1, t1: 40.35 });
  cap(36.1, 37.65, 'and for fleets, it answers');
  cap(37.65, 40.0, 'from your own *safety management system*, too.');
  endCard({ t0: 40.2, t1: 45.0, variant: 'main' });
} else if (CUT === 'cutA') {
  DURATION = 15;
  radarScene({
    t0: 0, t1: 3.2, top: 470, readouts: true, dimAt: 0.0,
    stack: [['New deckhand.', st(0, 0.15), 700, 130], ['First trip.', st(1, 0.8), 850, 130], ['<span class="hl">Orientation</span> first?', st(2, 1.5), 1000, 130]],
  });
  composerScene({ t0: 3.0, t1: 5.2, text: Q1, typeFrom: 3.3, typeTo: 4.55, sendAt: 4.75 });
  cap(3.1, 4.8, 'Ask *RegKnot*.');
  phoneQ1Cut({ t0: 4.85, t1: 11.2 });
  cap(6.0, 7.9, '*Yes,* before the boat gets underway.');
  cap(7.9, 9.55, '*10* topics.');
  cap(9.55, 10.95, '*Logged.*');
  endCard({ t0: 11.0, t1: 15.0, variant: 'cut' });
} else if (CUT === 'cutB') {
  DURATION = 15;
  auditOpener({ t0: 0, t1: 3.2 });
  composerScene({ t0: 3.0, t1: 5.2, text: Q2, typeFrom: 3.3, typeTo: 4.55, sendAt: 4.75, seed: 8 });
  cap(3.1, 4.8, 'Ask *RegKnot*.');
  phoneQ2Cut({ t0: 4.85, t1: 11.2 });
  cap(6.0, 10.85, "Here's what your *TVR* has to show.");
  endCard({ t0: 11.0, t1: 15.0, variant: 'cut' });
}
if (VOX) VOX.caps.forEach(([a, b, text]) => caption(a, b, text));

// ── seek ───────────────────────────────────────────────────────────────────
function seek(t) {
  const f = Math.round(t * 30);
  for (const s of scenes) {
    const vis = t >= s.t0 && t < s.t1;
    s.el.style.display = vis ? 'block' : 'none';
    if (vis) s.update(t);
  }
  for (const u of updaters) u(t, f);
}
window.seek = seek;
window.DURATION = DURATION;
window.EVENTS = EVENTS.sort((a, b) => a.t - b.t);
window.ready = (async () => {
  await document.fonts.ready;
  await Promise.all(['500 20px "IBM Plex Mono"', '600 20px "IBM Plex Mono"', '700 20px "IBM Plex Mono"', '600 20px "Barlow Condensed"', '700 20px "Barlow Condensed"', '800 20px "Barlow Condensed"', '900 20px "Barlow Condensed"'].map(f => document.fonts.load(f)));
  await Promise.all([...document.images].map(img => img.decode().catch(() => null)));
  seek(0);
  return { duration: DURATION, events: EVENTS.length, fonts: document.fonts.check('900 20px "Barlow Condensed"') };
})();
})();
