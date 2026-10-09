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
  const vals = rows.flatMap((r) => [r.value, r.lo, r.hi]).filter((x) => x != null && Number.isFinite(x));
  const m = Math.max(5, ...vals.map(Math.abs)) * 1.08;
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

/**
 * Fielding diagram for a plan from the profile data.
 * plan: {positions:[{name,x,y,zone}], counts, reasons, hand, bowling, outfieldCap}
 */
export function fieldPlan(plan, opts = {}) {
  const W = 420, H = 440, cx = W / 2, cy = 230, R = 190;
  const svg = frame(W, H, opts.label || `Field plan: ${plan.positions.map((p) => p.name).join(', ')}`);
  const px = (p) => cx + p.x * R;
  const py = (p) => cy - p.y * R;   // y > 0 is towards the bowler (up the page)
  svg.append(s('ellipse', { cx, cy, rx: R + 14, ry: R + 14, fill: 'var(--grass)', 'fill-opacity': .55, stroke: 'var(--pitch)', 'stroke-opacity': .5 }));
  svg.append(s('ellipse', { cx, cy, rx: R * 0.5, ry: R * 0.5, fill: 'none', stroke: 'var(--surface)', 'stroke-width': 2, 'stroke-dasharray': '6 6' }));
  svg.append(s('rect', { x: cx - 7, y: cy - 58, width: 14, height: 76, rx: 2, fill: 'var(--gold-soft)', stroke: 'var(--gold)', 'stroke-opacity': .5 }));
  svg.append(s('text', { x: cx, y: cy - 64, 'text-anchor': 'middle', class: 'ct-axis' }, 'bowler'));
  svg.append(s('text', { x: 14, y: 22, class: 'ct-axis' }, plan.hand === 'left' ? 'left-hander' : 'right-hander'));
  svg.append(s('text', { x: W - 14, y: 22, 'text-anchor': 'end', class: 'ct-axis' }, `${plan.hand === 'left' ? 'leg' : 'off'} side →`));
  svg.append(s('text', { x: 14, y: H - 12, class: 'ct-axis' }, `← ${plan.hand === 'left' ? 'off' : 'leg'} side`));
  const colour = { keeper: 'var(--sky)', close: 'var(--ball)', ring: 'var(--ink)', deep: 'var(--gold)' };
  for (const p of plan.positions) {
    const g = s('g', { class: 'ct-fielder' });
    g.append(s('circle', { cx: px(p), cy: py(p), r: 7.5, fill: colour[p.zone] || 'var(--ink)', stroke: 'var(--surface)', 'stroke-width': 2 }));
    const anchor = p.x > 0.55 ? 'end' : p.x < -0.55 ? 'start' : 'middle';
    const dx = anchor === 'end' ? -10 : anchor === 'start' ? 10 : 0;
    g.append(s('text', { x: px(p) + dx, y: py(p) + (p.y < -0.05 && Math.abs(p.x) < 0.3 ? 20 : -11), 'text-anchor': anchor, class: 'ct-field' }, p.name));
    svg.append(g);
  }
  const c = plan.counts || {};
  const legend = h('div.chart-legend.tiny',
    h('span', h('span.swatch.dot', { style: { background: 'var(--ball)' } }), ` catchers ${c.close ?? ''}`),
    h('span', h('span.swatch.dot', { style: { background: 'var(--ink)' } }), ` ring ${c.ring ?? ''}`),
    h('span', h('span.swatch.dot', { style: { background: 'var(--gold)' } }), ` boundary ${c.deep ?? ''}`),
    plan.outfieldCap != null ? h('span.faint', `max ${plan.outfieldCap} outside the circle`) : null);
  return h('figure.chart-fig.field-fig', svg, legend);
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
