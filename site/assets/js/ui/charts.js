// Native SVG charts. Every chart takes plain data, returns an element, uses
// theme tokens for colour, and carries an accessible name. Sizes come from the
// viewBox, so charts scale with their container.
import { h, s, fmt, tooltip } from './dom.js';

const C = {
  ink: 'var(--ink)', muted: 'var(--muted)', faint: 'var(--faint)', line: 'var(--line)', line2: 'var(--line-2)',
  pos: 'var(--strength)', neg: 'var(--weakness)', pitch: 'var(--pitch)', sky: 'var(--sky)', gold: 'var(--gold)',
};

function frame(w, hgt, label) {
  return s('svg', { viewBox: `0 0 ${w} ${hgt}`, width: '100%', role: 'img', 'aria-label': label, class: 'chart',
                    preserveAspectRatio: 'xMidYMid meet' });
}

/**
 * Horizontal bars around zero with optional confidence whiskers.
 * rows: [{label, value, lo?, hi?, flag?: 'strength'|'weakness'|'', note?, sub?}]
 * opts: {unit: 'runs per 100 balls', label}
 */
export function divergingBars(rows, opts = {}) {
  const W = 640, rowH = 34, top = 26, left = 190, right = 64;
  const H = top + rows.length * rowH + 8;
  // Scale to the estimates; very wide intervals from thin samples are clipped
  // (at 2.5x the largest estimate) rather than allowed to flatten every bar.
  const ests = rows.map((r) => r.value).filter((x) => x != null && Number.isFinite(x));
  const vMax = Math.max(4, ...ests.map(Math.abs));
  const ci = rows.flatMap((r) => [r.lo, r.hi]).filter((x) => x != null && Number.isFinite(x)).map(Math.abs);
  const m = Math.min(Math.max(vMax, ...ci), vMax * 2.5) * 1.08;
  const x = (v) => left + ((v + m) / (2 * m)) * (W - left - right);
  const svg = frame(W, H, opts.label || `Chart of ${opts.unit || 'values'}`);
  svg.append(s('line', { x1: x(0), x2: x(0), y1: 14, y2: H - 4, stroke: C.line, 'stroke-width': 1.5 }));
  svg.append(s('text', { x: x(0), y: 12, 'text-anchor': 'middle', class: 'ct-axis' }, 'average'));
  svg.append(s('text', { x: x(-m) + 2, y: 12, class: 'ct-axis' }, `− ${opts.negLabel || 'worse'}`));
  svg.append(s('text', { x: x(m) - 2, y: 12, 'text-anchor': 'end', class: 'ct-axis' }, `${opts.posLabel || 'better'} +`));
  rows.forEach((r, i) => {
    const y = top + i * rowH;
    const g = s('g', { class: 'ct-row' });
    const colour = r.flag === 'weakness' ? C.neg : r.flag === 'strength' ? C.pos : r.value >= 0 ? 'var(--pitch-2)' : 'var(--faint)';
    g.append(s('text', { x: left - 12, y: y + 14, 'text-anchor': 'end', class: 'ct-label' }, r.label));
    if (r.sub) g.append(s('text', { x: left - 12, y: y + 27, 'text-anchor': 'end', class: 'ct-sub' }, r.sub));
    if (r.lo != null && r.hi != null) {
      g.append(s('line', { x1: x(Math.max(-m, r.lo)), x2: x(Math.min(m, r.hi)), y1: y + 11, y2: y + 11, stroke: colour, 'stroke-opacity': .35, 'stroke-width': 10, 'stroke-linecap': 'round' }));
    }
    const v = r.value ?? 0;
    g.append(s('rect', { x: Math.min(x(0), x(v)), y: y + 6, width: Math.max(1.5, Math.abs(x(v) - x(0))), height: 10, rx: 3, fill: colour }));
    g.append(s('text', { x: W - 4, y: y + 15, 'text-anchor': 'end', class: 'ct-value', fill: colour }, fmt.signed(v)));
    if (r.flag) g.append(s('text', { x: W - 4, y: y + 28, 'text-anchor': 'end', class: 'ct-sub', fill: colour }, r.flag));
    svg.append(g);
    if (r.note) tooltip(g, r.note);
  });
  return h('figure.chart-fig', svg, opts.caption ? h('figcaption.tiny.muted', opts.caption) : null);
}

/**
 * Season chart: bars for a count (runs/wickets) and an optional line for a rate.
 * points: [{y, bar, line}] ; opts: {barLabel, lineLabel, lineFmt}
 */
export function seasonChart(points, opts = {}) {
  const W = 640, H = 220, L = 40, R = 44, T = 16, B = 28;
  const svg = frame(W, H, opts.label || 'Season by season');
  if (!points.length) return h('p.small.muted', 'No seasons in range.');
  const years = points.map((p) => p.y);
  const y0 = Math.min(...years), y1 = Math.max(...years);
  const n = y1 - y0 + 1;
  const bw = (W - L - R) / n;
  const bx = (yr) => L + (yr - y0) * bw;
  const maxBar = Math.max(1, ...points.map((p) => p.bar || 0));
  const lines = points.filter((p) => p.line != null && Number.isFinite(p.line));
  const lMin = Math.min(0, ...lines.map((p) => p.line)), lMax = Math.max(1, ...lines.map((p) => p.line));
  const by = (v) => H - B - (v / maxBar) * (H - T - B);
  const ly = (v) => H - B - ((v - lMin) / (lMax - lMin || 1)) * (H - T - B);
  for (let k = 0; k <= 4; k++) {
    const yy = T + k * (H - T - B) / 4;
    svg.append(s('line', { x1: L, x2: W - R, y1: yy, y2: yy, stroke: C.line2 }));
  }
  svg.append(s('text', { x: L - 6, y: T + 4, 'text-anchor': 'end', class: 'ct-axis' }, fmt.n(maxBar)));
  svg.append(s('text', { x: L - 6, y: H - B, 'text-anchor': 'end', class: 'ct-axis' }, '0'));
  for (const p of points) {
    const r = s('rect', { x: bx(p.y) + bw * 0.18, y: by(p.bar || 0), width: bw * 0.64, height: Math.max(0, H - B - by(p.bar || 0)), rx: 2,
                          fill: opts.barColour || 'var(--grass)' });
    svg.append(r);
    tooltip(r, `${p.y}: ${opts.barLabel || 'value'} ${fmt.n(p.bar)}${p.line != null ? ` · ${opts.lineLabel}: ${(opts.lineFmt || fmt.sr)(p.line)}` : ''}`);
  }
  const step = Math.ceil(n / 12);
  for (let yr = y0; yr <= y1; yr += step) {
    svg.append(s('text', { x: bx(yr) + bw / 2, y: H - 10, 'text-anchor': 'middle', class: 'ct-axis' }, `'${String(yr).slice(2)}`));
  }
  if (lines.length > 1) {
    if (lMin < 0) svg.append(s('line', { x1: L, x2: W - R, y1: ly(0), y2: ly(0), stroke: C.faint, 'stroke-dasharray': '3 3' }));
    const d = lines.map((p, i) => `${i ? 'L' : 'M'}${bx(p.y) + bw / 2},${ly(p.line)}`).join(' ');
    svg.append(s('path', { d, fill: 'none', stroke: opts.lineColour || C.pitch, 'stroke-width': 2.2, 'stroke-linejoin': 'round' }));
    for (const p of lines) svg.append(s('circle', { cx: bx(p.y) + bw / 2, cy: ly(p.line), r: 3.2, fill: opts.lineColour || C.pitch }));
    svg.append(s('text', { x: W - R + 6, y: T + 4, class: 'ct-axis' }, (opts.lineFmt || fmt.sr)(lMax)));
    svg.append(s('text', { x: W - R + 6, y: H - B, class: 'ct-axis' }, (opts.lineFmt || fmt.sr)(lMin)));
  }
  const legend = h('div.chart-legend.tiny',
    h('span', h('span.swatch', { style: { background: opts.barColour || 'var(--grass)' } }), ` ${opts.barLabel || 'value'}`),
    lines.length > 1 ? h('span', h('span.swatch', { style: { background: opts.lineColour || 'var(--pitch)' } }), ` ${opts.lineLabel}`) : null);
  return h('figure.chart-fig', svg, legend);
}

/**
 * Player rate vs peer rate per row (dot plot), e.g. dismissal modes per 1000 balls.
 * rows: [{label, value, peer, count?}]
 */
export function compareDots(rows, opts = {}) {
  const W = 640, rowH = 30, top = 22, left = 190, right = 60;
  const H = top + rows.length * rowH + 6;
  const max = Math.max(1, ...rows.flatMap((r) => [r.value || 0, r.peer || 0])) * 1.1;
  const x = (v) => left + (v / max) * (W - left - right);
  const svg = frame(W, H, opts.label || 'Player versus peers');
  svg.append(s('text', { x: left, y: 12, class: 'ct-axis' }, '0'));
  svg.append(s('text', { x: W - right, y: 12, 'text-anchor': 'end', class: 'ct-axis' }, `${fmt.n(max, 1)} ${opts.unit || ''}`));
  rows.forEach((r, i) => {
    const y = top + i * rowH + 10;
    const hi = r.peer > 0 && r.value / r.peer >= 1.2, lo = r.peer > 0 && r.value / r.peer <= 0.8;
    const col = hi ? (opts.highIsBad === false ? C.pos : C.neg) : lo ? (opts.highIsBad === false ? C.neg : C.pos) : C.ink;
    svg.append(s('text', { x: left - 12, y: y + 4, 'text-anchor': 'end', class: 'ct-label' }, r.label));
    svg.append(s('line', { x1: left, x2: W - right, y1: y, y2: y, stroke: C.line2 }));
    svg.append(s('line', { x1: x(r.peer || 0), x2: x(r.value || 0), y1: y, y2: y, stroke: col, 'stroke-width': 2.5, 'stroke-opacity': .5 }));
    svg.append(s('circle', { cx: x(r.peer || 0), cy: y, r: 5, fill: 'var(--surface)', stroke: C.muted, 'stroke-width': 1.5 }));
    const dot = s('circle', { cx: x(r.value || 0), cy: y, r: 6, fill: col });
    svg.append(dot);
    svg.append(s('text', { x: W - 4, y: y + 4, 'text-anchor': 'end', class: 'ct-value' }, r.peer ? `${(r.value / r.peer).toFixed(2)}×` : '–'));
    tooltip(dot, `${r.label}: ${fmt.n(r.value, 2)} vs peers ${fmt.n(r.peer, 2)} ${opts.unit || ''}${r.count != null ? ` (${r.count} times)` : ''}`);
  });
  const legend = h('div.chart-legend.tiny',
    h('span', h('span.swatch.dot', { style: { background: 'var(--ink)' } }), ' this player'),
    h('span', h('span.swatch.dot.hollow'), ' peers in the same competition'));
  return h('figure.chart-fig', svg, legend);
}

// Fielding positions in metres for a right-hander: x towards the off side, y
// from the striker's stumps towards the bowler. Deep positions are pushed out
// to just inside the rope of the rendered ground.
const POS_M = {
  'Wicketkeeper': [0, -15], '1st slip': [2.2, -15.6], '2nd slip': [4.4, -15.4], '3rd slip': [6.6, -14.8],
  '4th slip': [8.7, -14], 'Gully': [12.5, -10.5], 'Leg slip': [-3.2, -13.5], 'Short leg': [-4.6, 3.8],
  'Silly point': [4.6, 3.8], 'Short mid-wicket': [-9.5, 9], 'Point': [24, 1], 'Cover': [23, 15],
  'Extra cover': [15.5, 23], 'Mid-off': [7.5, 28], 'Mid-on': [-7.5, 28], 'Mid-wicket': [-23, 15],
  'Square leg': [-25, 0], 'Short fine leg': [-15, -19], 'Short third man': [15, -20],
  'Third man': [40, -48], 'Deep point': [62, 2], 'Deep cover': [52, 36], 'Long-off': [22, 66],
  'Long-on': [-22, 66], 'Deep mid-wicket': [-52, 36], 'Deep square leg': [-62, 2], 'Fine leg': [-40, -48],
  'Cow corner': [-46, 54],
};
const SHORT = { '1st slip': '1st', '2nd slip': '2nd', '3rd slip': '3rd', '4th slip': '4th',
                'Short mid-wicket': 'Short mid-wkt', 'Short third man': 'Short 3rd man' };
const GROUND = { rx: 68, ry: 72, half: 10.06 };   // matches assets/img/ground/field.json
const VIEW = 156;                                  // metres shown across the plan

function groundXY(name, hand, zone, keeperUp) {
  let [x, y] = name === 'Wicketkeeper' && keeperUp ? [0.4, -1.6] : (POS_M[name] || [0, 0]);
  y -= GROUND.half;                                // ground centre is mid-pitch
  if (zone === 'deep') {
    const r = Math.hypot(x / GROUND.rx, y / GROUND.ry) || 1;
    x *= 0.92 / r; y *= 0.92 / r;
  }
  return [hand === 'left' ? -x : x, y];
}

const SPAN = 180;                                  // metres covered by the full-ground image
const CLOSEUP = { span: 52, cx: 0, cy: -19 };      // high-resolution render of the striker's end

function groundImages(view, cx = 0, cy = 0) {
  // Scale the image so `view` metres fill the stage, then shift it so ground
  // point (cx, cy) sits in the middle. Small views use the close-up render.
  const close = view <= CLOSEUP.span * 0.9
    && Math.abs(cx - CLOSEUP.cx) + view / 2 <= CLOSEUP.span / 2 && Math.abs(cy - CLOSEUP.cy) + view / 2 <= CLOSEUP.span / 2;
  const span = close ? CLOSEUP.span : SPAN, ox = close ? CLOSEUP.cx : 0, oy = close ? CLOSEUP.cy : 0;
  const w = (span / view) * 100;
  const left = 50 - (0.5 + (cx - ox) / span) * w, top = 50 - (0.5 - (cy - oy) / span) * w;
  const style = { width: `${w}%`, left: `${left}%`, top: `${top}%` };
  const name = close ? 'closeup' : 'field';
  const day = h('img.fp-bg.fp-day', { src: `assets/img/ground/${name}-day.webp`, alt: '', loading: 'lazy', decoding: 'async', style });
  const night = h('img.fp-bg.fp-night', { src: `assets/img/ground/${name}-night.webp`, alt: '', loading: 'lazy', decoding: 'async', style });
  // Once the ground for this theme has loaded, fetch the other quietly, so a theme switch shows it at once.
  day.addEventListener('load', () => { night.loading = 'eager'; }, { once: true });
  night.addEventListener('load', () => { day.loading = 'eager'; }, { once: true });
  return [day, night];
}

function groupLabel(names) {
  const slips = names.filter((n) => / slip$/.test(n) && n !== 'Leg slip').length;
  const rest = names.filter((n) => !/ slip$/.test(n) || n === 'Leg slip').map((n) => n.toLowerCase());
  return [slips ? `${slips} slip${slips > 1 ? 's' : ''}` : null, ...rest].filter(Boolean).join(', ');
}

/**
 * Field plan drawn on the rendered ground, with a zoomed inset for the
 * catchers around the bat. Positions are placed in metres and expressed as
 * percentages of the stage, so markers stay put at any size.
 */
export function fieldPlan(plan, opts = {}) {
  const hand = plan.hand === 'left' ? 'left' : 'right';
  const spin = plan.bowling === 'spin';
  const keeperUp = spin && (plan.reasons || []).some((r) => r.signal === 'stumped');
  const placed = plan.positions.map((p) => {
    const zone = p.zone || (p.name === 'Wicketkeeper' ? 'keeper' : 'ring');
    return { ...p, zone, xy: groundXY(p.name, hand, zone, keeperUp) };
  });
  // Catchers behind or square of the bat cluster too tightly for the full view.
  const cordon = placed.filter((p) => (p.zone === 'close' || p.zone === 'keeper') && p.xy[1] < -GROUND.half - 1);
  const mark = (cls, [l, t], label, tip, side) => {
    const m = h(`div.fp-pos.${cls}`, { style: { left: `${l}%`, top: `${t}%` }, tabindex: tip ? '0' : null },
      h('span.fp-dot'), label ? h(`span.fp-tag.${side}`, label) : null);
    if (tip) tooltip(m, tip);
    return m;
  };
  const describe = (p) => `${p.name}${p.zone === 'close' ? ' (catcher)' : p.zone === 'deep' ? ' (boundary)' : p.zone === 'ring' ? ' (saving one)' : ''}`;
  const batterXY = [hand === 'left' ? 0.5 : -0.5, -GROUND.half + 1.4];

  // ---- full field
  const pct = ([x, y]) => [50 + (x / VIEW) * 100, 50 - (y / VIEW) * 100];
  const stage = h('div.fp-stage', { role: 'img', 'aria-label': opts.label || `Field plan: ${plan.positions.map((p) => p.name).join(', ')}` },
    ...groundImages(VIEW));
  stage.append(mark('fp-batter', pct(batterXY), null, `${hand === 'left' ? 'Left' : 'Right'}-handed batter on strike`));
  stage.append(mark('fp-bowler', pct([hand === 'left' ? -0.9 : 0.9, GROUND.half + 1.2]), null, `${spin ? 'Spin' : 'Pace'} bowler`));
  for (const p of placed) {
    const inCordon = cordon.includes(p);
    const side = p.xy[1] < -30 ? 'down' : (p.zone === 'close' ? (p.xy[0] >= 0 ? 'right' : 'left') : 'up');
    const label = inCordon ? null : (SHORT[p.name] || p.name);
    stage.append(mark(`fp-${p.zone}`, pct(p.xy), label, describe(p), side));
  }
  const catchers = cordon.filter((p) => p.zone === 'close');
  if (catchers.length) {
    const cx = catchers.reduce((a, p) => a + p.xy[0], 0) / catchers.length;
    const cy = Math.min(...catchers.map((p) => p.xy[1]));
    const g = h('div.fp-pos.fp-group', { style: { left: `${pct([cx, cy])[0]}%`, top: `${pct([cx, cy])[1]}%` } },
      h('span.fp-tag.down', groupLabel(catchers.map((p) => p.name))));
    stage.append(g);
  }

  // ---- close-up of the catchers around the bat
  let inset = null;
  if (cordon.length) {
    const xs = [...cordon.map((p) => p.xy[0]), batterXY[0]];
    const ys = [...cordon.map((p) => p.xy[1]), batterXY[1]];
    const icx = (Math.min(...xs) + Math.max(...xs)) / 2, icy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const view = Math.max(20, Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) * 1.9);
    const ip = ([x, y]) => [50 + ((x - icx) / view) * 100, 50 - ((y - icy) / view) * 100];
    const ist = h('div.fp-stage.fp-inset-stage', { role: 'img', 'aria-label': `Close catchers: ${cordon.map((p) => p.name).join(', ')}` },
      ...groundImages(view, icx, icy));
    ist.append(mark('fp-batter', ip(batterXY), null, 'Batter on strike'));
    const SIDE = { 'Wicketkeeper': 'left', 'Leg slip': 'left', 'Gully': 'right', '1st slip': 'down', '2nd slip': 'up',
                   '3rd slip': 'down', '4th slip': 'up' };
    cordon.forEach((p) => {
      let side = SIDE[p.name] || 'up';
      if (hand === 'left') side = side === 'left' ? 'right' : side === 'right' ? 'left' : side;
      ist.append(mark(`fp-${p.zone}`, ip(p.xy), p.name === 'Wicketkeeper' ? (keeperUp ? 'Keeper (up)' : 'Keeper') : (SHORT[p.name] || p.name), describe(p), side));
    });
    inset = h('div.fp-inset', h('div.fp-inset-title', 'Around the bat'), h('div.fp-frame', ist));
  }

  const c = plan.counts || {};
  const legend = h('div.chart-legend.tiny.fp-legend',
    h('span', h('span.fp-key.fp-close'), ` catchers ${c.close ?? ''}`),
    h('span', h('span.fp-key.fp-ring'), ` ring ${c.ring ?? ''}`),
    h('span', h('span.fp-key.fp-deep'), ` boundary ${c.deep ?? ''}`),
    h('span', h('span.fp-key.fp-keeper'), keeperUp ? ' keeper standing up' : ' keeper'),
    plan.outfieldCap != null ? h('span.faint', `at most ${plan.outfieldCap} outside the circle`) : null,
    h('span.faint', `${hand}-hander, ${spin ? 'spin' : 'pace'}`));
  return h('figure.chart-fig.fp', h('div.fp-layout', h('div.fp-frame.fp-main', stage), inset), legend);
}

/** Percentile meter 0..1 with label. */
export function percentile(p, label) {
  if (p == null) return h('div.pct', h('div.small.muted', label), h('div.pct-value', '–'));
  const pct = Math.round(p * 100);
  return h('div.pct', { 'aria-label': `${label}: ${pct}th percentile` },
    h('div.small.muted', label),
    h('div.pct-value', `${pct}`, h('span.tiny.muted', ' pctile')),
    h('div.meter', h('span', { style: { width: `${pct}%` } })));
}

/** Stacked won/lost/drawn bar. */
export function resultBar(rec) {
  const parts = [['won', 'var(--strength)'], ['lost', 'var(--weakness)'], ['drawn', 'var(--faint)'], ['tied', 'var(--gold)'], ['no_result', 'var(--line)']];
  const total = parts.reduce((a, [k]) => a + (Number(rec[k]) || 0), 0) || 1;
  return h('div.bar.result-bar', { role: 'img', 'aria-label': parts.map(([k]) => `${k.replace('_', ' ')} ${rec[k] || 0}`).join(', ') },
    parts.map(([k, col]) => (Number(rec[k]) ? tooltip(h('span', { style: { width: `${(100 * rec[k]) / total}%`, background: col } }), `${k.replace('_', ' ')}: ${rec[k]}`) : null)));
}

/** Tiny inline trend line. */
export function sparkline(values, { w = 120, hgt = 28, colour = 'var(--pitch)' } = {}) {
  const v = values.filter((x) => x != null && Number.isFinite(x));
  const svg = s('svg', { viewBox: `0 0 ${w} ${hgt}`, width: w, height: hgt, 'aria-hidden': 'true' });
  if (v.length < 2) return svg;
  const lo = Math.min(...v), hi = Math.max(...v);
  const d = v.map((x, i) => `${i ? 'L' : 'M'}${(i / (v.length - 1)) * (w - 4) + 2},${hgt - 3 - ((x - lo) / (hi - lo || 1)) * (hgt - 6)}`).join(' ');
  svg.append(s('path', { d, fill: 'none', stroke: colour, 'stroke-width': 1.8 }));
  return svg;
}
