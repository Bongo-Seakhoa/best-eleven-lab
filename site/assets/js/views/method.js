// Method and data: how an eleven is picked, what the data covers, the checks
// each build runs, and the fitted model itself. Every number shown here is read
// from site/data or the selection engine; nothing is restated by hand except
// the pipeline's fixed thresholds, which are named as such.
import { h, s, clear, fmt } from '../ui/dom.js';
import * as data from '../data.js';
import { setQuery } from '../app.js';
import { PRESETS, TEMPLATES, SLOT_TYPES } from '../engine/select.js';

const REPO = 'https://github.com/Bongo-Seakhoa/best-eleven-lab';

const SECTIONS = [
  { id: 'picking', short: 'How an eleven is picked', title: 'How an eleven is picked' },
  { id: 'coverage', short: 'Data coverage', title: 'Data coverage' },
  { id: 'checks', short: 'Checks on every build', title: 'Checks we run on every build' },
  { id: 'model', short: 'The model up close', title: 'The model up close' },
  { id: 'profiles', short: 'Profiles and field plans', title: 'Profiles, matchups and field plans' },
  { id: 'versus', short: 'XI vs XI', title: 'XI vs XI: from two elevens to a result' },
  { id: 'limitations', short: 'Limitations', title: 'Limitations' },
  { id: 'run', short: 'Run it yourself', title: 'Run it yourself' },
  { id: 'sources', short: 'Sources and licences', title: 'Sources and licences' },
];

const COMPONENTS = [
  { key: 'quality', label: 'Quality', colour: 'var(--pitch)' },
  { key: 'legacy', label: 'Legacy', colour: 'var(--sky)' },
  { key: 'experience', label: 'Experience', colour: 'var(--gold)' },
  { key: 'leadership', label: 'Leadership', colour: 'var(--ball)' },
];

const FAMILY = {
  t20: { label: 'T20', perOver: 6 },
  fifty: { label: '50-over', perOver: 6 },
  hundred: { label: 'The Hundred', perOver: 0 },
};

// Fixed thresholds from the Python pipeline (model/profiles.py, model/values.py).
const MIN_SPLIT = [['Tests', 300, 60], ['ODIs', 150, 30], ['T20s', 90, 18], ['The Hundred', 75, 15]];
const MIN_MATCHES_TO_ADJUST = 50;

// ------------------------------------------------------------------ helpers
const ok = (r) => (r.status === 'fulfilled' ? r.value : null);
const why = (r) => (r.status === 'rejected' ? String(r.reason?.message || r.reason) : null);
const isNum = (x) => typeof x === 'number' && Number.isFinite(x);

function dateFmt(iso) {
  if (!iso) return null;
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(+d)) return null;
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
}
const span = (a, b) => (a === b ? String(a) : `${a}–${b}`);
const eraLabel = (e) => String(e).replace('-', '–');
const pct = (x, d = 0) => fmt.pct(x, d);
function millions(n) {
  if (!isNum(n)) return '–';
  return n >= 1e6 ? `${+(n / 1e6).toFixed(n >= 1e7 ? 1 : 2)} million` : fmt.n(n);
}
function plural(n, one, many = `${one}s`) { return `${fmt.n(n)} ${n === 1 ? one : many}`; }

function prefersReducedMotion() {
  try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; }
}

function niceScale(max, maxTicks = 5) {
  const m = Math.max(max, 1);
  for (const st of [1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]) {
    if (Math.ceil(m / st) <= maxTicks) return { max: Math.ceil(m / st) * st, step: st };
  }
  const st = 10 ** Math.ceil(Math.log10(m / maxTicks));
  return { max: Math.ceil(m / st) * st, step: st };
}

/** Push label positions apart by at least `gap`, staying within [lo, hi]. */
function spreadLabels(ys, gap, lo, hi) {
  const a = ys.map((y, i) => ({ y: Math.min(hi, Math.max(lo, y)), i })).sort((p, q) => p.y - q.y);
  for (let k = 1; k < a.length; k++) if (a[k].y - a[k - 1].y < gap) a[k].y = a[k - 1].y + gap;
  if (a.length && a[a.length - 1].y > hi) {
    a[a.length - 1].y = hi;
    for (let k = a.length - 2; k >= 0; k--) if (a[k + 1].y - a[k].y < gap) a[k].y = a[k + 1].y - gap;
  }
  const out = [];
  for (const p of a) out[p.i] = p.y;
  return out;
}

/** Map a pointer event on an SVG to viewBox x. */
function viewX(svg, e, W) {
  const r = svg.getBoundingClientRect();
  return r.width ? ((e.clientX - r.left) / r.width) * W : 0;
}

function loadError(what, message) {
  return h('div.notice.error', { role: 'alert' }, h('div',
    h('strong', `${what} could not load. `), message || 'The data file is missing or unreadable.',
    h('p.small.m-flush', 'The rest of this page still works. Rebuilding the site data with ', h('code', 'best-eleven build'), ' usually fixes this.')));
}

let liveEl = null;
function announce(msg) {
  if (!liveEl || !liveEl.isConnected) {
    liveEl = h('div.sr-only', { role: 'status', 'aria-live': 'polite' });
    document.body.append(liveEl);
  }
  liveEl.textContent = '';
  setTimeout(() => { if (liveEl) liveEl.textContent = msg; }, 30);
}

async function copyText(text, btn, codeEl) {
  let done = false;
  try { await navigator.clipboard.writeText(text); done = true; } catch (e) { done = false; }
  const label = btn.querySelector('.m-copy-label');
  if (done) {
    if (label) label.textContent = 'Copied';
    btn.classList.add('is-done');
    announce('Copied to the clipboard');
  } else {
    if (codeEl) {
      const range = document.createRange();
      range.selectNodeContents(codeEl);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    }
    if (label) label.textContent = 'Press Ctrl+C';
    announce('Copying is blocked here. The text is selected: press Control and C to copy it.');
  }
  clearTimeout(btn._t);
  btn._t = setTimeout(() => { if (label) label.textContent = 'Copy'; btn.classList.remove('is-done'); }, 2200);
}

function copyButton(text, accessible, codeEl) {
  const btn = h('button.btn.sm.m-copy', { type: 'button', 'aria-label': accessible },
    s('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' },
      s('rect', { x: 9, y: 9, width: 11, height: 11, rx: 2 }), s('path', { d: 'M5 15V5a2 2 0 0 1 2-2h8' })),
    h('span.m-copy-label', 'Copy'));
  btn.addEventListener('click', () => copyText(text, btn, codeEl));
  return btn;
}

function statusBadge(passed) {
  return passed
    ? h('span.badge.good', s('svg', { viewBox: '0 0 16 16', width: 12, height: 12, 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', 'stroke-width': '2.2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, s('path', { d: 'M3 8.5l3.2 3L13 4.5' })), 'Passed')
    : h('span.badge.bad', s('svg', { viewBox: '0 0 16 16', width: 12, height: 12, 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', 'stroke-width': '2.2', 'stroke-linecap': 'round' }, s('path', { d: 'M4 4l8 8M12 4l-8 8' })), 'Failed');
}

function statGrid(items) {
  return h('div.stat-grid', items.filter(Boolean).map(([value, label, note]) => h('div.stat',
    h('div.stat-value', value), h('div.stat-label', label), note ? h('div.tiny.faint.m-stat-note', note) : null)));
}

function table(cols, rows, opts = {}) {
  return h('div.table-wrap', { class: opts.wrapClass || '' }, h('table.data', opts.caption ? h('caption.sr-only', opts.caption) : null,
    h('thead', h('tr', cols.map(([label, cls]) => h('th', { scope: 'col', class: cls || '' }, label)))),
    h('tbody', rows)));
}

// ------------------------------------------------------------------- mount
export async function mount(root, route) {
  const reduced = prefersReducedMotion();
  const page = h('div.page.method-page');
  const hero = h('header.method-hero',
    h('div.eyebrow', 'Method and data'),
    h('h1.display', 'From one ball to a Best XI'),
    h('p.lede', 'Every rating on this site starts from a single delivery. This page follows that delivery through the model to the team sheet, then shows what the data covers, how each build is checked, and where the method falls short.'));
  const layout = h('div.method-layout', { 'aria-busy': 'true' },
    h('div.m-loading', h('div.row', h('div.spinner'), h('span.muted', 'Loading the model and data files…')),
      h('div.skeleton.m-skel', { style: 'height: 220px' }), h('div.skeleton.m-skel', { style: 'height: 120px' })));
  page.append(hero, layout);
  root.append(page);

  const results = await Promise.allSettled([data.meta(), data.validation(), data.runExpectancy(),
    data.bowlerFamily(), data.reference(), data.versusModel()]);
  const [metaR, valR, reR, famR, refR, vsR] = results;
  const ctx = {
    reduced,
    meta: ok(metaR), validation: ok(valR), re: ok(reR), fam: ok(famR), ref: ok(refR), vs: ok(vsR),
    err: { meta: why(metaR), validation: why(valR), re: why(reR), fam: why(famR), vs: why(vsR) },
  };

  clear(layout);
  layout.removeAttribute('aria-busy');
  const toc = buildToc(scrollTo);
  const content = h('div.m-content');
  layout.append(toc.el, content);
  if (ctx.err.meta) content.append(loadError('The site summary (meta.json)', ctx.err.meta));
  content.append(
    sectionPicking(ctx), sectionCoverage(ctx), sectionChecks(ctx), sectionModel(ctx),
    sectionProfiles(ctx), sectionVersus(ctx), sectionLimitations(ctx), sectionRun(ctx), sectionSources(ctx));

  function scrollTo(id, smooth) {
    const el = id && document.getElementById(`m-${id}`);
    if (!el) return false;
    el.scrollIntoView({ behavior: smooth && !reduced ? 'smooth' : 'auto', block: 'start' });
    el.querySelector('.m-h2')?.focus({ preventScroll: true });
    toc.setActive(id);
    return true;
  }

  let raf = 0;
  const onScroll = () => {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      if (!page.isConnected) { window.removeEventListener('scroll', onScroll); return; }
      let active = SECTIONS[0].id;
      for (const sec of SECTIONS) {
        const el = document.getElementById(`m-${sec.id}`);
        if (el && el.getBoundingClientRect().top <= 140) active = sec.id;
      }
      const doc = document.documentElement;
      if (window.innerHeight + window.scrollY >= doc.scrollHeight - 4) active = SECTIONS[SECTIONS.length - 1].id;
      toc.setActive(active);
    });
  };
  if (page.isConnected) window.addEventListener('scroll', onScroll, { passive: true });

  const initial = route.query.get('section');
  if (initial) requestAnimationFrame(() => { if (!scrollTo(initial, false)) window.scrollTo(0, 0); onScroll(); });
  else onScroll();

  return {
    update(r) {
      const id = r.query.get('section');
      if (!id || !scrollTo(id, true)) window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' });
    },
    destroy() {
      window.removeEventListener('scroll', onScroll);
      if (raf) cancelAnimationFrame(raf);
    },
  };
}

function buildToc(scrollTo) {
  const links = SECTIONS.map((sec) => h('a', {
    href: `#/method?section=${sec.id}`, 'data-sec': sec.id,
    onclick: (e) => {
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      setQuery({ section: sec.id });
      scrollTo(sec.id, true);
    },
  }, sec.short));
  const el = h('nav.m-toc', { 'aria-label': 'On this page' },
    h('div.eyebrow.m-toc-title', 'On this page'), h('ol', links.map((a) => h('li', a))));
  return {
    el,
    setActive(id) {
      for (const a of links) {
        if (a.dataset.sec === id) a.setAttribute('aria-current', 'location');
        else a.removeAttribute('aria-current');
      }
    },
  };
}

function section(id, intro, ...children) {
  const i = SECTIONS.findIndex((x) => x.id === id);
  const sec = SECTIONS[i];
  return h('section.m-section', { id: `m-${id}`, 'aria-labelledby': `m-${id}-title` },
    h('div.m-section-head',
      h('span.m-num', { 'aria-hidden': 'true' }, String(i + 1).padStart(2, '0')),
      h('h2.display.m-h2', { id: `m-${id}-title`, tabindex: '-1' }, sec.title)),
    intro ? h('p.m-intro', intro) : null,
    ...children);
}

// -------------------------------------------------------------- 1. picking
function stepFacts(ctx) {
  const m = ctx.meta || {};
  const groups = m.model?.groups || {};
  const gl = Object.values(groups);
  const f = {
    archive: m.source?.matches ?? null,
    competitions: Array.isArray(m.scopes) ? m.scopes.length : null,
    matches: gl.length ? gl.reduce((a, g) => a + (g.matches || 0), 0) : null,
    deliveries: gl.length ? gl.reduce((a, g) => a + (g.deliveries || 0), 0) : null,
    mt: groups['men-test'] || null,
    wt: groups['women-test'] || null,
    dataEnd: dateFmt(m.dataEnd),
  };
  const t = ctx.re?.['t20-male'];
  if (t && Array.isArray(t.re) && t.re.length) {
    const e = t.re.length - 1;
    const i = t.balls.indexOf(60);
    const row = i >= 0 ? t.re[e][i] : null;
    if (row && isNum(row[2]) && isNum(row[3])) f.t20 = { era: eraLabel(t.eras[e]), before: row[2], after: row[3] };
  }
  const tw = m.model?.testWicketValue?.male;
  if (tw) {
    const y = Math.max(...Object.keys(tw).map(Number).filter(Number.isFinite));
    if (Number.isFinite(y) && isNum(tw[y])) f.testW = { year: y, runs: tw[y] };
  }
  return f;
}

function buildSteps(ctx) {
  const f = stepFacts(ctx);
  const lamB = f.mt?.lambda_bat, lamW = f.mt?.lambda_bowl;

  const visual1 = () => statGrid([
    f.archive != null && [fmt.n(f.archive), 'matches in Cricsheet’s archive'],
    f.competitions != null && [fmt.n(f.competitions), 'competitions covered here'],
    f.matches != null && [fmt.n(f.matches), 'matches in those competitions'],
    f.deliveries != null && [millions(f.deliveries), 'deliveries valued'],
  ]);

  const visual2 = () => h('div.m-vis-stack',
    h('div.m-formula', { role: 'img', 'aria-label': 'Value of a ball equals runs scored plus expected runs after the ball minus expected runs before it' },
      h('span', 'value'), h('span.m-op', '='), h('span', 'runs'), h('span.m-op', '+'),
      h('span', 'expected after'), h('span.m-op', '−'), h('span', 'expected before')),
    f.t20 ? h('div.m-example',
      h('div.m-ex-row', h('span', '60 balls left, two down'), h('strong.num', `${fmt.n(f.t20.before)} more runs expected`)),
      h('div.m-ex-row', h('span', 'A wicket falls: three down'), h('strong.num', `${fmt.n(f.t20.after)} expected`)),
      h('div.m-ex-row.m-ex-total', h('span', 'What that wicket cost'), h('strong.num', `about ${fmt.n(f.t20.before - f.t20.after)} runs`)),
      h('p.tiny.faint.m-flush', `Men’s T20s, ${f.t20.era}, from the fitted run-expectancy table. The ball itself also uses up a little expectation, which is ignored here.`)) : null,
    f.testW ? h('p.small.m-flush', h('strong', 'Tests: '), `in ${f.testW.year} a dismissal in men’s Tests was priced at ${fmt.n(f.testW.runs, 1)} runs, the year’s runs per wicket.`) : null);

  const visual3 = () => h('div.m-factors',
    h('div', h('div.field-label', 'Who was involved'),
      h('div.chips', ['Batter', 'Bowler', 'Batting side', 'Bowling unit'].map((x) => h('span.badge.m-chip', x)))),
    h('div', h('div.field-label', 'Where and when'),
      h('div.chips', ['Year', 'Phase of the innings', 'Which innings', 'Home or away'].map((x) => h('span.badge.m-chip.m-chip-ctx', x)))));

  const visual4 = () => {
    if (!isNum(lamB)) return null;
    return h('div.m-vis-stack',
      h('p.small.muted.m-flush', `Men’s Test batters: ${fmt.n(lamB)} average balls added to every record`),
      h('ul.m-keep', [100, 300, 1000, 3000, 10000].map((n) => {
        const k = n / (n + lamB);
        return h('li',
          h('span.m-keep-n', `${fmt.n(n)} balls`),
          h('span.meter.m-keep-meter', { 'aria-hidden': 'true' }, h('span', { style: `width: ${(k * 100).toFixed(1)}%` })),
          h('span.m-keep-v', `keeps ${pct(k)} of their edge`));
      })));
  };

  const visual5 = () => h('div.m-vis-stack',
    h('div.chart-legend.tiny', COMPONENTS.map((c) => h('span', h('span.swatch', { style: `background: ${c.colour}` }), ` ${c.label}`))),
    h('ul.m-presets', Object.values(PRESETS).map((p) => {
      const total = COMPONENTS.reduce((a, c) => a + (p.weights[c.key] || 0), 0) || 1;
      const desc = COMPONENTS.filter((c) => p.weights[c.key]).map((c) => `${c.label.toLowerCase()} ${p.weights[c.key]}`).join(', ');
      return h('li',
        h('span.m-preset-name', p.label),
        h('span.bar.m-preset-bar', { role: 'img', 'aria-label': `${p.label}: ${desc}; half-life ${p.halfLife ? `${p.halfLife} years` : 'off'}` },
          COMPONENTS.filter((c) => p.weights[c.key]).map((c) => h('span', { style: `width: ${(100 * p.weights[c.key]) / total}%; background: ${c.colour}` }))),
        h('span.tiny.muted.m-preset-hl', p.halfLife ? `half-life ${p.halfLife} yr${p.halfLife > 1 ? 's' : ''}` : 'no recency weighting'));
    })),
    h('p.tiny.faint.m-flush', 'The lenses on the Best XI page. Every weight can also be set by hand.'));

  const visual6 = () => {
    const rows = [['Tests', TEMPLATES.multi], ['ODIs', TEMPLATES.fifty], ['T20s and the Hundred', TEMPLATES.t20]];
    return h('div.m-vis-stack',
      h('ul.m-templates', rows.filter(([, t]) => t).map(([label, t]) => h('li',
        h('span.m-tpl-label', label),
        h('span.chips', t.map(([type, n]) => h('span.badge', `${n} × ${SLOT_TYPES[type]?.label ?? type}`)))))),
      h('p.tiny.faint.m-flush', 'Default compositions. Each adds up to 11 and can be changed on the Best XI page.'));
  };

  return [
    {
      short: 'Every ball', title: 'Start from every delivery', visual: visual1,
      text: [f.archive != null
        ? `Cricsheet’s archive holds ${fmt.n(f.archive)} matches, each recorded ball by ball: batter, bowler, non-striker, runs, extras and how any wicket fell. The ${f.competitions ?? ''} competitions covered here account for ${fmt.n(f.matches)} of those matches, and every delivery in them is used apart from super overs.`
        : 'Cricsheet publishes matches ball by ball: batter, bowler, non-striker, runs, extras and how any wicket fell. Every delivery in the competitions covered here is used apart from super overs.'],
      detail: ['Matches are read from Cricsheet’s JSON files into a columnar warehouse, keyed by match, innings and the order of each ball, so a wide or a no-ball never overwrites another delivery. Super overs are kept but left out of player values. Innings totals rebuilt from the deliveries must reproduce the official winning margins; that check is in the next-but-one section.'],
    },
    {
      short: 'Value', title: 'Value each ball by what it changes', visual: visual2,
      text: ['Runs are not all equal. A dot ball at the death is a small win for the bowler, and a wicket with plenty of overs left costs far more than one off the last ball. In one-day and T20 cricket each ball is therefore valued by how much it changes the batting side’s expected total. Tests have no ball clock, so a Test ball is worth its runs, minus that year’s runs per wicket whenever a batter is out.'],
      detail: ['Expected further runs come from uninterrupted first innings that ran their full length or ended all out. For each number of wickets lost they are fitted with the curve shape the Duckworth-Lewis method uses, separately for each era, and constrained so that losing a wicket never raises the expectation. The change on each ball splits into the cost of using up a legal ball and the cost of any wicket, so the batter is credited and the bowler charged for their part. Wides and no-balls count against the bowler only. You can explore the fitted curves under The model up close.'],
    },
    {
      short: 'Adjust', title: 'Take out the opposition and the conditions', visual: visual3,
      text: ['Runs against a strong attack in their conditions should count for more than runs against a weak one at home. A ridge regression fits every ball at once, with a term for the batter, the bowler, the batting side, the bowling unit and the context: the year, the phase of the innings, which innings it is, and whether the batting side is at home. A player’s adjusted value is what is left once the other side and the context are accounted for.'],
      detail: [
        'Ridge regression shrinks every term towards zero, which stops thinly observed players soaking up noise. Team terms are barely shrunk, so the strength of a whole bowling unit is captured even when its bowlers are rarely seen elsewhere. The home side is inferred from where teams play most often, so designated home grounds abroad count as home and genuinely neutral venues count as neutral.',
        f.mt && f.mt.adjusted ? `In men’s Tests the fit covers ${millions(f.mt.deliveries)} deliveries across ${fmt.n(f.mt.ctx_levels)} context cells.` : null,
        f.wt && f.wt.adjusted === false ? `Women’s Tests (${fmt.n(f.wt.matches)} matches) are too few to fit, so values there are centred on the average but not adjusted for opposition.` : null,
      ].filter(Boolean),
    },
    {
      short: 'Shrink', title: 'Pull small samples towards average', visual: visual4,
      text: [isNum(lamB)
        ? `Three good innings are not a career. Each player’s adjusted total is divided by their balls plus a set number of extra, perfectly average balls. In men’s Tests that is ${fmt.n(lamB)} balls for batters and ${fmt.n(lamW)} for bowlers, so a batter who has faced ${fmt.n(lamB)} balls keeps half of their measured edge over average.`
        : 'Three good innings are not a career. Each player’s adjusted total is divided by their balls plus a set number of extra, perfectly average balls, so short records are pulled towards average and long ones keep most of their edge.'],
      detail: ['The number of extra balls is estimated from the data by empirical Bayes: it is the ratio of ball-to-ball noise to the real spread between players. Each competition group gets its own figures, listed under The model up close. For batters the site uses the figure fitted among top-seven batters when that is larger, because tail-enders widen the spread and would otherwise make the shrinkage too weak.'],
    },
    {
      short: 'Weigh', title: 'Turn your priorities into one score', visual: visual5,
      text: ['Each candidate gets a score from 0 to 100 for every slot they can fill, where 50 is the average qualified player and 15 points is one standard deviation. Quality is adjusted value per ball, or per innings for Test batters. Legacy is total adjusted value over the window. Experience is matches played and leadership is matches formally captained. Your weights blend them into one score per player per slot, and a recency half-life sets how quickly older seasons fade.'],
      detail: ['With a half-life of three years, a season three years before the end of the window counts half as much as the latest one. Where a competition has no captaincy records, the leadership weight drops out rather than scoring everyone zero. Roles come from where a player bats, how much they bowl, whether they keep wicket and their bowling type.'],
    },
    {
      short: 'Solve', title: 'Solve for the best eleven exactly', visual: visual6,
      text: ['The chosen eleven has the highest total score of any eleven that fills every slot in your composition and respects your caps, such as at most four players from one country. It is not built greedily one pick at a time. The site solves it exactly as a min-cost flow, and the test suite checks that solver against an integer program.'],
      detail: ['Each player belongs to one group: their country under a per-team cap, overseas or local under an overseas cap. That keeps the problem a network flow, whose best answer always uses whole players. When no eleven satisfies the settings, the site says which slot is short instead of returning a near miss. A per-team cap and an overseas cap together would break that structure, so the site refuses the combination rather than approximating. To show how settled each pick is, the eleven is re-solved 20 times with every weight nudged by up to 25%.'],
    },
  ];
}

function stepBody(st, i, n, headingTag = 'h3') {
  return [
    h('div.eyebrow', `Step ${i + 1} of ${n}`),
    h(`${headingTag}.m-step-title`, st.title),
    h('div.m-step-grid',
      h('div.m-step-text', st.text.map((t) => h('p', t)),
        h('details.m-more', h('summary', 'More detail'), st.detail.map((t) => h('p.small', t)))),
      h('div.m-step-visual', st.visual())),
  ];
}

function stepExplainer(steps, reduced) {
  let cur = 0;
  let all = reduced;
  const n = steps.length;
  const tabs = steps.map((st, i) => h('button.m-dot', {
    type: 'button', role: 'tab', id: `m-step-tab-${i}`, 'aria-controls': 'm-step-panel',
    'aria-selected': 'false', tabindex: '-1', onclick: () => go(i, false),
  }, h('span.m-dot-num', { 'aria-hidden': 'true' }, String(i + 1)), h('span.m-dot-label', st.short)));
  const tablist = h('div.m-dots', { role: 'tablist', 'aria-label': 'Six steps from ball to eleven' }, tabs);
  tablist.addEventListener('keydown', (e) => {
    const map = { ArrowRight: cur + 1, ArrowDown: cur + 1, ArrowLeft: cur - 1, ArrowUp: cur - 1, Home: 0, End: n - 1 };
    if (!(e.key in map)) return;
    e.preventDefault();
    go((map[e.key] + n) % n, true);
  });
  const panel = h('div.m-step-panel', { role: 'tabpanel', id: 'm-step-panel', tabindex: '0' });
  const prev = h('button.btn.sm', { type: 'button', onclick: () => go(cur - 1, false) }, h('span', { 'aria-hidden': 'true' }, '←'), 'Previous');
  const next = h('button.btn.sm.primary', { type: 'button', onclick: () => go(cur + 1, false) }, 'Next', h('span', { 'aria-hidden': 'true' }, '→'));
  const counter = h('span.small.muted.num', { 'aria-hidden': 'true' });
  const nav = h('div.m-step-nav', prev, counter, next);
  const stepper = h('div.m-stepper', tablist, panel, nav);
  const list = h('ol.m-step-list');
  const toggle = h('button.btn.sm.ghost.m-step-toggle', { type: 'button', onclick: () => { all = !all; render(); } });
  const wrap = h('div.card.m-steps', h('div.m-steps-head', h('p.small.muted.m-flush', 'Six steps take a delivery from the archive to the team sheet.'), toggle), stepper, list);

  function go(i, focusTab) {
    if (i < 0 || i >= n) return;
    cur = i;
    render();
    if (focusTab) tabs[cur].focus();
  }
  function render() {
    toggle.textContent = all ? 'Step through instead' : 'Show all six at once';
    toggle.setAttribute('aria-pressed', String(all));
    stepper.hidden = all;
    list.hidden = !all;
    if (all) {
      if (!list.firstChild) list.append(...steps.map((st, i) => h('li.m-step-item', ...stepBody(st, i, n))));
      return;
    }
    tabs.forEach((t, i) => {
      t.setAttribute('aria-selected', String(i === cur));
      t.tabIndex = i === cur ? 0 : -1;
      t.classList.toggle('is-done', i < cur);
    });
    panel.setAttribute('aria-labelledby', `m-step-tab-${cur}`);
    clear(panel);
    panel.append(h('div.fade-in', ...stepBody(steps[cur], cur, n)));
    prev.disabled = cur === 0;
    next.disabled = cur === n - 1;
    counter.textContent = `${cur + 1} / ${n}`;
  }
  render();
  return wrap;
}

function sectionPicking(ctx) {
  return section('picking',
    'In plain terms: value every ball, take out who it was against and where, be sceptical of small samples, weigh what you care about, then let an exact solver pick the side.',
    stepExplainer(buildSteps(ctx), ctx.reduced));
}

// ------------------------------------------------------------- 2. coverage
function sectionCoverage(ctx) {
  const m = ctx.meta;
  if (!m) return section('coverage', null, loadError('Coverage details', ctx.err.meta));
  const src = m.source || {};
  const scopes = Array.isArray(m.scopes) ? m.scopes : [];
  const fmtOrder = { Test: 0, ODI: 1, T20I: 2 };
  const intl = scopes.filter((x) => x.tier === 'national')
    .sort((a, b) => (a.gender === b.gender ? 0 : a.gender === 'male' ? -1 : 1) || (fmtOrder[a.format] ?? 9) - (fmtOrder[b.format] ?? 9));
  const leagues = scopes.filter((x) => x.tier === 'league')
    .sort((a, b) => (a.gender === b.gender ? 0 : a.gender === 'male' ? -1 : 1) || (!!b.featured - !!a.featured) || (b.matches - a.matches));
  const byKey = new Map(scopes.map((x) => [x.key, x]));

  const sha = src.sha256 ? String(src.sha256) : '';
  const shaCode = sha ? h('code.m-hash', { title: sha }, `${sha.slice(0, 12)}…${sha.slice(-4)}`) : null;
  const sourceCard = h('div.card.card-pad.m-source',
    h('div.spread',
      h('div', h('div.eyebrow', 'Source'),
        h('h3.m-source-name', src.url ? h('a', { href: src.url, rel: 'noopener' }, src.name || 'Cricsheet') : (src.name || 'Cricsheet'), h('span.muted.small', ' full JSON archive'))),
      sha ? h('div.m-hash-row', h('span.tiny.muted', 'SHA-256'), shaCode, copyButton(sha, 'Copy the full SHA-256 checksum of the archive')) : null),
    statGrid([
      [fmt.n(src.matches), 'matches in the archive'],
      [dateFmt(m.dataEnd) ?? '–', 'latest match in the data'],
      [dateFmt(src.builtAt) ?? '–', 'warehouse built'],
      [dateFmt(m.generatedAt) ?? '–', 'site data exported'],
    ]),
    h('p.tiny.faint.m-flush', 'The checksum identifies the exact archive this build used, so anyone can confirm they are working from the same file.'));

  const scopeRow = (x) => h('tr',
    h('th', { scope: 'row' }, h('span.m-scope-name', x.label), x.squads ? h('span.badge.m-sq', { title: 'Current squads are tracked from Wikipedia' }, 'squads') : null),
    h('td.small', x.tier === 'national' ? 'International' : x.featured ? 'Featured league' : 'League'),
    h('td.small', x.format),
    h('td.r.num', Array.isArray(x.years) ? span(x.years[0], x.years[1]) : '–'),
    h('td.r.num', fmt.n(x.matches)),
    h('td.r.num', fmt.n(x.players)));
  const group = (label, rows) => (rows.length ? [h('tr.m-group-row', h('th', { scope: 'rowgroup', colspan: 6 }, `${label} · ${rows.length}`)), ...rows.map(scopeRow)] : []);
  const scopeTable = scopes.length
    ? table([['Competition'], ['Tier'], ['Format'], ['Seasons', 'r'], ['Matches', 'r'], ['Players', 'r']],
      [...group('International', intl), ...group('Leagues', leagues)], { caption: 'Competitions covered ball by ball', wrapClass: 'm-scroll-y' })
    : h('p.small.muted', 'No competitions are listed in this build.');

  const hist = Array.isArray(m.historic) ? [...m.historic].sort((a, b) => a.years[0] - b.years[0]) : [];
  const histTable = hist.length ? table([['All-eras list'], ['Seasons', 'r'], ['Players', 'r']],
    hist.map((x) => h('tr', h('th', { scope: 'row' }, x.label), h('td.r.num', span(x.years[0], x.years[1])), h('td.r.num', fmt.n(x.players)))),
    { caption: 'Career lists used by the all-eras mode' }) : null;

  const mt = byKey.get('men-test'), mo = byKey.get('men-odi'), wo = byKey.get('women-odi'), wt20 = byKey.get('women-t20i'), wt = byKey.get('women-test');
  const firstHist = hist.length ? Math.min(...hist.map((x) => x.years[0])) : null;
  const notes = [
    mt || mo ? `Ball-by-ball coverage of men’s internationals starts around 2002${mt ? ` (the earliest men’s Tests here are from ${mt.years[0]})` : ''}.${wo || wt20 ? ` Women’s coverage starts later: ${[wo && `ODIs from ${wo.years[0]}`, wt20 && `T20Is from ${wt20.years[0]}`].filter(Boolean).join(' and ')}${wt ? `, with ${plural(wt.matches, 'women’s Test')} in all` : ''}.` : ''}` : null,
    'Cricsheet withholds matches involving Afghanistan’s men. Those games are missing, so Afghanistan’s men do not appear in the ball-by-ball views and their opponents’ records are short by those matches.',
    `The all-eras mode does not use deliveries. It works from Wikipedia’s lists of national players, with career totals going back to ${firstHist ?? 1877}, adjusted to each decade’s average.`,
    m.profiles?.players ? `${fmt.n(m.profiles.players)} players have a full profile page${m.captains?.rows ? `, and ${fmt.n(m.captains.rows)} captaincy records feed the leadership score` : ''}.` : null,
  ].filter(Boolean);

  return section('coverage',
    'What this build was made from, and how far back each competition goes.',
    sourceCard,
    h('div.m-sub', h('h3', 'Competitions covered ball by ball'),
      h('p.small.muted', 'International cricket first, then leagues. A squads tag means current squads come from Wikipedia, so the current-squad filter works there.'),
      scopeTable),
    histTable ? h('div.m-sub', h('h3', 'Career lists for the all-eras mode'), histTable) : null,
    h('div.m-sub', h('h3', 'Worth knowing'), h('ul.m-notes', notes.map((t) => h('li', t)))),
    enrichmentBlock(ctx));
}

function enrichmentBlock(ctx) {
  const ref = ctx.ref;
  if (!ref || typeof ref !== 'object') {
    return h('p.small.muted.m-sub', 'Counts from the latest Wikipedia and Wikidata refresh are not included in this build.');
  }
  const human = (k) => { const t = k.replace(/_/g, ' '); return t.charAt(0).toUpperCase() + t.slice(1); };
  const mods = Object.entries(ref.modules || {}).map(([name, st]) => {
    const nums = Object.entries(st || {}).filter(([, v]) => isNum(v)).slice(0, 5);
    if (!nums.length) return null;
    return h('div.panel.m-ref-mod', h('div.field-label', human(name)),
      h('dl.m-dl', nums.map(([k, v]) => [h('dt.small.muted', human(k)), h('dd.num', fmt.n(v))])));
  }).filter(Boolean);
  return h('div.m-sub',
    h('h3', 'Wikipedia and Wikidata refresh'),
    h('p.small.muted', `${ref.source || 'English Wikipedia and Wikidata'}${dateFmt(ref.fetched_at) ? `, fetched ${dateFmt(ref.fetched_at)}` : ''}. These snapshots supply squads, captaincy, retirements, styles and historic careers.`),
    mods.length ? h('div.m-ref-grid', mods) : h('p.small.muted', 'The refresh recorded no counts.'));
}

// --------------------------------------------------------------- 3. checks
function sectionChecks(ctx) {
  const v = ctx.validation;
  if (!v) return section('checks', null, loadError('The build checks (validation.json)', ctx.err.validation));
  const checks = Array.isArray(v.checks) ? v.checks : [];
  if (!checks.length) return section('checks', null, h('p.small.muted', 'This build recorded no checks.'));
  const failed = checks.filter((c) => !c.passed);
  const summary = failed.length
    ? h('div.notice.error', { role: 'status' }, h('div',
      h('strong', `${failed.length} of ${checks.length} checks failed on this build. `),
      `Failed: ${failed.map((c) => c.name).join('; ')}. The details below show what was measured; treat the affected numbers with extra care.`))
    : h('div.m-allpass', statusBadge(true), h('span.small', `All ${checks.length} checks passed on this build.`));
  return section('checks',
    'Each build reruns these against the full archive and records the result. A failure is reported here, not hidden.',
    summary,
    h('div.m-checks', checks.map((c) => checkCard(c, ctx))));
}

function checkCard(c, ctx) {
  let body;
  if (c.runs && c.wickets) body = marginBody(c);
  else if (c.strict || c.broad) body = careerBody(c);
  else if (c.scopes && c.split_year != null) body = oosBody(c, ctx);
  else if (c.cv_accuracy != null) body = classifierBody(c);
  else if (c.groups && c.min_held_out != null) body = versusCheckBody(c);
  else if (c.targets && c.split_year != null) body = debutCheckBody(c);
  else body = [h('p.small', c.summary || 'No summary recorded.')];
  return h('article.card.card-pad.m-check', { class: c.passed ? '' : 'is-failed' },
    h('div.m-check-head', h('h3', c.name), statusBadge(!!c.passed)),
    ...body);
}

function marginBody(c) {
  const r = c.runs, w = c.wickets;
  const rate = (x) => (x.checked ? x.exact / x.checked : null);
  const mism = [
    ...(c.runs_mismatches || []).map((x) => ({ id: x.match_id, winner: x.winner, rebuilt: `${fmt.n(x.w_runs - x.l_runs)} runs`, official: `${fmt.n(x.margin)} runs` })),
    ...(c.wickets_mismatches || []).map((x) => ({ id: x.match_id, winner: x.winner, rebuilt: `${fmt.n(10 - x.wickets)} wickets`, official: `${fmt.n(x.by_wickets)} wickets` })),
  ];
  const missing = (r.checked - r.exact) + (w.checked - w.exact);
  return [
    h('p.small', `Every innings total is rebuilt from its deliveries and compared with the official result. Of ${fmt.n(r.checked)} wins by runs, ${fmt.n(r.exact)} reproduce the official margin exactly. Of ${fmt.n(w.checked)} wins by wickets, ${fmt.n(w.exact)} do.`),
    statGrid([[pct(rate(r), 2), 'runs margins exact', `${fmt.n(r.checked)} matches`], [pct(rate(w), 2), 'wickets margins exact', `${fmt.n(w.checked)} matches`]]),
    h('p.tiny.faint', 'Passes when more than 99.5% of runs margins and 99% of wickets margins match.'),
    mism.length ? h('details.m-more', h('summary', missing === mism.length
      ? `The ${plural(mism.length, 'match', 'matches')} that disagree`
      : `${fmt.n(mism.length)} of the ${fmt.n(missing)} matches that disagree`),
      table([['Match id'], ['Winner'], ['Rebuilt margin', 'r'], ['Official margin', 'r']],
        mism.map((x) => h('tr', h('td.num', x.id), h('td', x.winner), h('td.r.num', x.rebuilt), h('td.r.num', x.official))),
        { caption: 'Matches whose rebuilt margin differs from the official one' })) : null,
  ];
}

function careerBody(c) {
  const st = c.strict || {};
  const broad = c.broad || {};
  const fmts = Object.keys(broad);
  return [
    h('p.small', `The strict set is ${plural(st.players ?? 0, 'men’s Test player')} from sides that have never played Afghanistan in a Test (Australia, England, South Africa and Pakistan), whose Wikipedia figures were updated within 60 days of the data end and whose careers fall inside the archive. Matches, runs and wickets must agree exactly: ${pct(st.exact, 1)} do.`),
    st.mismatches && st.mismatches.length ? h('details.m-more', h('summary', `${plural(st.mismatches.length, 'player')} in the strict set disagree`),
      table([['Player id'], ['Matches', 'r'], ['Wikipedia', 'r'], ['Runs', 'r'], ['Wikipedia', 'r'], ['Wickets', 'r'], ['Wikipedia', 'r']],
        st.mismatches.map((x) => h('tr', h('td.num', x.id), h('td.r.num', fmt.n(x.m)), h('td.r.num', fmt.n(x.wk_m)), h('td.r.num', fmt.n(x.r)), h('td.r.num', fmt.n(x.wk_r)), h('td.r.num', fmt.n(x.ww)), h('td.r.num', fmt.n(x.wk_w)))))) : null,
    h('p.tiny.faint', 'Passes with at least 50 players in the strict set and 98% exact.'),
    fmts.length ? h('div.m-sub-s',
      h('p.small', 'For context, every player whose career lies inside coverage, in each format. Gaps here come mostly from matches Cricsheet withholds or lacks, and from Wikipedia infoboxes that lag behind.'),
      table([['Format'], ['Players', 'r'], ['Exact', 'r'], ['Cricsheet has fewer matches', 'r'], ['Cricsheet has more', 'r']],
        fmts.map((k) => { const b = broad[k]; return h('tr', h('th', { scope: 'row' }, k), h('td.r.num', fmt.n(b.players)), h('td.r.num', pct(b.exact)), h('td.r.num', pct(b.cricsheet_fewer)), h('td.r.num', pct(b.cricsheet_more))); }),
        { caption: 'Career totals against Wikipedia, all players inside coverage' })) : null,
  ];
}

function oosColumns(sp) {
  const keys = Object.keys(sp || {});
  return {
    raw: keys.find((k) => /raw/i.test(k)),
    sr: keys.find((k) => /strike/i.test(k)),
    adj: keys.find((k) => /adjust/i.test(k)),
  };
}

function oosBody(c, ctx) {
  const scopes = Object.entries(c.scopes || {});
  const labelOf = (k) => (ctx.meta?.scopes || []).find((x) => x.key === k)?.label || k;
  const y = c.split_year;
  const rows = scopes.map(([k, v]) => {
    const col = oosColumns(v.spearman);
    const vals = [col.raw, col.sr, col.adj].map((key) => (key ? v.spearman[key] : null));
    const best = Math.max(...vals.filter(isNum));
    return h('tr',
      h('th', { scope: 'row' }, labelOf(k)),
      h('td.r.num', fmt.n(v.players)),
      vals.map((x) => h('td.r.num', { class: isNum(x) && x === best ? 'm-best' : '' }, isNum(x) ? x.toFixed(2) : '–', isNum(x) && x === best ? h('span.sr-only', ' (best)') : null)));
  });
  const losses = scopes.filter(([, v]) => {
    const col = oosColumns(v.spearman);
    return col.sr && col.adj && v.spearman[col.sr] > v.spearman[col.adj];
  }).map(([k, v]) => {
    const col = oosColumns(v.spearman);
    return `${labelOf(k)}: strike rate ${v.spearman[col.sr].toFixed(2)} against ${v.spearman[col.adj].toFixed(2)}`;
  });
  return [
    h('p.small', `Does a rating built from ${y - 5}–${y} rank batters in the order they actually performed after ${y}? For batters with at least 300 balls in both periods, each earlier measure is compared with later raw value per ball using a Spearman rank correlation: 1 is a perfect ordering, 0 is no relationship.`),
    table([['Competition'], ['Batters', 'r'], ['Raw value per ball', 'r'], ['Strike rate', 'r'], ['Adjusted (this model)', 'r']], rows,
      { caption: 'Out-of-sample rank correlations; the best predictor in each row is bold' }),
    h('p.tiny.faint', 'Bold marks the best predictor in each row. Passes when the adjusted rating beats raw value per ball in every competition.'),
    losses.length ? h('p.small', h('strong', 'Where it falls short: '), `strike rate alone ranked later output better than the adjusted value in ${losses.join('; ')}.`) : null,
  ];
}

function classifierBody(c) {
  return [
    h('p.small', `Cricsheet does not record bowling styles. A classifier learns pace or spin from ${fmt.n(c.training_bowlers)} bowlers whose style Wikipedia gives, then labels the rest. These figures come from five-fold cross-validation on those labelled bowlers.`),
    statGrid([
      [pct(c.cv_accuracy, 1), 'accuracy', 'all predictions'],
      [isNum(c.cv_auc) ? c.cv_auc.toFixed(3) : '–', 'AUC', '1 is perfect, 0.5 is a coin toss'],
      [pct(c.cv_confident_coverage), 'confident', `at least ${pct(c.confidence_threshold)} sure`],
      [pct(c.cv_confident_accuracy, 1), 'accuracy when confident', 'the labels the site uses'],
    ]),
  ];
}

// ---------------------------------------------------------------- 4. model
function sectionModel(ctx) {
  const m = ctx.meta;
  const tw = m?.model?.testWicketValue;
  const groups = m?.model?.groups;
  return section('model',
    'The fitted pieces behind steps two to four, straight from this build.',
    h('div.m-sub',
      h('h3', 'Expected runs, ball by ball'),
      h('p.small.muted', 'How many more runs an average side scores from each point of an innings. Each line is a number of wickets already lost. A ball’s value in limited-overs cricket is the runs it brings plus the move between two points on these curves.'),
      ctx.re ? reExplorer(ctx.re) : loadError('The run-expectancy table', ctx.err.re)),
    h('div.m-sub',
      h('h3', 'What a Test wicket costs'),
      h('p.small.muted', 'Tests have no ball clock, so a dismissal is priced at that year’s runs per wicket in men’s Tests. Higher bars mean batting was easier that year and each wicket cost more.'),
      tw?.male ? rpwChart(tw.male) : (m ? h('p.small.muted', 'No Test wicket values in this build.') : loadError('Test wicket values', ctx.err.meta)),
      tw?.female ? womenTestNote(tw.female, m) : null),
    h('div.m-sub',
      h('h3', 'How hard each group is shrunk'),
      h('p.small.muted', 'Each group of competitions is fitted on its own. The shrinkage penalty is the number of average balls effectively added to every player’s record, so bigger numbers mean short records are pulled harder towards average.'),
      groups ? groupsBlock(groups, m) : loadError('The fitted groups', ctx.err.meta)));
}

function womenTestNote(female, meta) {
  const vals = Object.values(female).filter(isNum);
  if (!vals.length) return null;
  const pooled = vals.every((x) => x === vals[0]);
  const wt = (meta?.scopes || []).find((x) => x.key === 'women-test');
  return h('p.small.muted', pooled
    ? `Women’s Tests use one pooled figure, ${fmt.n(vals[0], 1)} runs per wicket, because ${wt ? `${fmt.n(wt.matches)} matches are` : 'the matches are'} too few for a steady yearly one.`
    : `Women’s Tests range from ${fmt.n(Math.min(...vals), 1)} to ${fmt.n(Math.max(...vals), 1)} runs per wicket across years.`);
}

function reExplorer(re) {
  const keys = Object.keys(re).filter((k) => re[k] && Array.isArray(re[k].re) && re[k].re.length && Array.isArray(re[k].balls));
  if (!keys.length) return h('p.small.muted', 'No run-expectancy curves in this build.');
  const families = ['t20', 'fifty', 'hundred'].filter((f) => keys.some((k) => re[k].family === f));
  const has = (fam, g) => keys.includes(`${fam}-${g}`);
  const st = { fam: families[0], g: has(families[0], 'male') ? 'male' : 'female', era: null, idx: null };
  const yScale = {};
  for (const f of families) {
    let mx = 0;
    for (const k of keys) if (re[k].family === f) for (const era of re[k].re) for (const row of era) for (const v of row) if (isNum(v)) mx = Math.max(mx, v);
    yScale[f] = niceScale(mx);
  }
  const colour = (w) => `color-mix(in oklab, var(--pitch) ${100 - w * 7}%, var(--surface))`;

  const controls = h('div.m-controls');
  const fig = h('div.m-re-fig');
  const rootEl = h('div.card.card-pad.m-re', controls, fig);

  function seg(label, options, value, onPick) {
    return h('div.m-control', h('span.field-label', { id: `m-re-${label.toLowerCase()}` }, label),
      h('div.seg', { role: 'group', 'aria-labelledby': `m-re-${label.toLowerCase()}` },
        options.map(([v, text, disabled]) => h('button', { type: 'button', 'aria-pressed': String(v === value), disabled: !!disabled, onclick: () => onPick(v) }, text))));
  }

  function renderControls() {
    clear(controls);
    const d = re[`${st.fam}-${st.g}`];
    controls.append(
      seg('Format', families.map((f) => [f, FAMILY[f]?.label || f]), st.fam, (v) => {
        const frac = st.idx != null ? st.idx / Math.max(1, re[`${st.fam}-${st.g}`].balls.length - 1) : 1;
        st.fam = v;
        if (!has(v, st.g)) st.g = st.g === 'male' ? 'female' : 'male';
        st.era = null;
        st.idx = Math.round(frac * (re[`${st.fam}-${st.g}`].balls.length - 1));
        renderAll();
      }),
      seg('Gender', [['male', 'Men', !has(st.fam, 'male')], ['female', 'Women', !has(st.fam, 'female')]], st.g, (v) => {
        const prevEras = re[`${st.fam}-${st.g}`].eras;
        st.g = v;
        const eras = re[`${st.fam}-${st.g}`].eras;
        if (st.era != null && eras[st.era] !== prevEras[st.era]) st.era = null;
        renderAll();
      }),
      d.eras.length > 1
        ? seg('Era', d.eras.map((e, i) => [i, eraLabel(e)]), st.era ?? d.eras.length - 1, (v) => { st.era = v; renderAll(); })
        : h('div.m-control', h('span.field-label', 'Era'), h('span.small.muted.m-era-one', 'All seasons, one curve')));
  }

  function renderChart() {
    clear(fig);
    const key = `${st.fam}-${st.g}`;
    const d = re[key];
    const e = Math.min(st.era ?? d.eras.length - 1, d.re.length - 1);
    const rows = d.re[e];
    const balls = d.balls;
    const n = balls.length;
    if (st.idx == null || st.idx > n - 1) st.idx = n - 1;
    const maxU = balls[n - 1] || 1;
    const per = FAMILY[d.family]?.perOver || 0;
    const { max: ymax, step: ystep } = yScale[d.family];
    const W = 640, H = 340, L = 40, R = 66, T = 26, B = 40;
    const x = (u) => L + (u / maxU) * (W - L - R);
    const y = (v) => T + (1 - v / ymax) * (H - T - B);
    const gname = d.gender === 'female' ? 'Women’s' : 'Men’s';
    const fname = FAMILY[d.family]?.label || d.family;
    const eraText = d.eras.length > 1 ? eraLabel(d.eras[e]) : 'all seasons';
    const start = rows[n - 1] || [];
    const svg = s('svg', {
      viewBox: `0 0 ${W} ${H}`, width: '100%', class: 'chart m-chart', role: 'img',
      'aria-label': `Line chart: expected further runs against balls remaining, ${gname.toLowerCase()} ${fname} cricket, ${eraText}. One line per wickets lost from 0 to 9. With ${maxU} balls left, an innings with no wickets down expects ${fmt.n(start[0])} more runs and one nine down expects ${fmt.n(start[9])}.`,
    });
    for (let v = 0; v <= ymax + 1e-9; v += ystep) {
      svg.append(s('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), class: v === 0 ? 'm-axis-line' : 'm-grid' }));
      svg.append(s('text', { x: L - 8, y: y(v) + 3.5, 'text-anchor': 'end', class: 'ct-axis' }, fmt.n(v)));
    }
    for (let u = 0; u <= maxU + 1e-9; u += maxU / 5) {
      svg.append(s('line', { x1: x(u), x2: x(u), y1: H - B, y2: H - B + 4, class: 'm-axis-line' }));
      svg.append(s('text', { x: x(u), y: H - B + 16, 'text-anchor': 'middle', class: 'ct-axis' }, fmt.n(u)));
    }
    svg.append(s('text', { x: (L + W - R) / 2, y: H - 4, 'text-anchor': 'middle', class: 'ct-axis m-axis-title' }, 'balls remaining →'));
    svg.append(s('text', { x: L - 8, y: 12, 'text-anchor': 'start', class: 'ct-axis m-axis-title' }, 'expected further runs'));

    for (let w = 9; w >= 0; w--) {
      const dpath = balls.map((u, i) => `${i ? 'L' : 'M'}${x(u).toFixed(1)},${y(rows[i][w]).toFixed(1)}`).join(' ');
      svg.append(s('path', { d: dpath, class: 'm-re-line', style: `stroke: ${colour(w)}` }));
    }
    const endY = Array.from({ length: 10 }, (_, w) => y(start[w] ?? 0));
    const labY = spreadLabels(endY, 11.5, T + 4, H - B - 2);
    for (let w = 0; w < 10; w++) {
      const lx = x(maxU);
      if (Math.abs(labY[w] - endY[w]) > 3) svg.append(s('path', { d: `M${lx + 2},${endY[w]} L${lx + 8},${labY[w]}`, class: 'm-leader', style: `stroke: ${colour(w)}` }));
      svg.append(s('text', { x: lx + 10, y: labY[w] + 3.5, class: 'ct-axis m-re-label' }, `${w} down`));
    }

    const cross = s('g', { class: 'm-cross' });
    const vline = s('line', { y1: T, y2: H - B, class: 'm-cross-line' });
    const dots = Array.from({ length: 10 }, (_, w) => s('circle', { r: 4, class: 'm-cross-dot', style: `fill: ${colour(w)}` }));
    cross.append(vline, ...dots);
    svg.append(cross);
    svg.append(s('rect', { x: L, y: T, width: W - L - R, height: H - T - B, class: 'm-hit' }));

    const slider = h('input', { type: 'range', id: 'm-re-balls', min: 0, max: n - 1, step: 1, value: st.idx, class: 'm-range' });
    const out = h('output.num', { for: 'm-re-balls' });
    const head = h('p.small.m-readout-head');
    const items = Array.from({ length: 10 }, (_, w) => {
      const val = h('span.num.m-ro-v');
      return { val, el: h('li', h('span.swatch', { style: `background: ${colour(w)}` }), h('span.m-ro-k', `${w} down`), val) };
    });
    const readout = h('div.m-readout', head, h('ol.m-readout-list', { 'aria-label': 'Expected further runs at the selected point, by wickets lost' }, items.map((i) => i.el)));

    function where(i) {
      const u = balls[i];
      if (u === 0) return 'No balls left';
      const overs = per ? ` (${fmt.n(u / per, Number.isInteger(u / per) ? 0 : 1)} overs)` : '';
      return `${fmt.n(u)} balls left${overs}${i === n - 1 ? ', the start of the innings' : ''}`;
    }
    function update() {
      const i = st.idx;
      const u = balls[i];
      const row = rows[i];
      vline.setAttribute('x1', x(u)); vline.setAttribute('x2', x(u));
      dots.forEach((c, w) => { c.setAttribute('cx', x(u)); c.setAttribute('cy', y(row[w])); });
      out.textContent = where(i);
      head.textContent = `${where(i)}: expected further runs`;
      items.forEach((it, w) => { it.val.textContent = fmt.n(row[w]); });
      slider.value = String(i);
      slider.setAttribute('aria-valuetext', `${where(i)}. ${row.map((v, w) => `${w} down ${fmt.n(v)}`).join(', ')} runs`);
    }
    slider.addEventListener('input', () => { st.idx = Number(slider.value); update(); });
    const fromPointer = (ev) => {
      const vx = viewX(svg, ev, W);
      const u = ((vx - L) / (W - L - R)) * maxU;
      let best = 0;
      for (let i = 1; i < n; i++) if (Math.abs(balls[i] - u) < Math.abs(balls[best] - u)) best = i;
      if (best !== st.idx) { st.idx = best; update(); }
    };
    svg.addEventListener('pointermove', fromPointer);
    svg.addEventListener('pointerdown', fromPointer);

    const used = Array.isArray(d.innings_used) ? d.innings_used[e] : null;
    const pooled = d.eras.length > 1 && isNum(used) && used < 300;
    const caption = h('p.tiny.faint.m-flush',
      isNum(used) ? (pooled
        ? `Only ${plural(used, 'complete first innings', 'complete first innings')} in this era, so this panel shows the curve fitted to all eras together. `
        : `Fitted from ${fmt.n(used)} complete first innings${d.eras.length > 1 ? ' in this era' : ''}. `) : '',
      'States such as nine down with most of the innings left are rare, so the lowest lines rest on few innings.');

    fig.append(
      h('figure.chart-fig.m-figure', svg,
        h('figcaption.m-figcap', h('span.small', `${gname} ${fname}, ${eraText}`), caption)),
      h('div.m-scrub', h('label.field-label', { for: 'm-re-balls' }, 'Move along the innings'), slider, out),
      readout,
      h('details.m-more', h('summary', 'Show these numbers as a table'),
        table([['Balls left'], ...Array.from({ length: 10 }, (_, w) => [`${w} down`, 'r'])],
          balls.map((u, i) => h('tr', h('th.num', { scope: 'row' }, fmt.n(u)), rows[i].map((v) => h('td.r.num', fmt.n(v, 1))))).reverse(),
          { caption: `Expected further runs, ${gname.toLowerCase()} ${fname}, ${eraText}`, wrapClass: 'm-scroll-y' })));
    update();
  }

  function renderAll() { renderControls(); renderChart(); }
  renderAll();
  return rootEl;
}

function rpwChart(series) {
  const years = Object.keys(series).map(Number).filter((y) => Number.isFinite(y) && isNum(series[y])).sort((a, b) => a - b);
  if (!years.length) return h('p.small.muted', 'No Test wicket values in this build.');
  const vals = years.map((y) => series[y]);
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const { max: ymax, step: ystep } = niceScale(hi, 4);
  const W = 640, H = 210, L = 34, R = 10, T = 14, B = 26;
  const n = years.length;
  const bw = (W - L - R) / n;
  const x = (i) => L + i * bw;
  const y = (v) => T + (1 - v / ymax) * (H - T - B);
  let active = n - 1;
  const svg = s('svg', {
    viewBox: `0 0 ${W} ${H}`, width: '100%', class: 'chart m-chart', role: 'img',
    'aria-label': `Bar chart: runs per wicket in men’s Tests by year, ${years[0]} to ${years[n - 1]}. Lowest ${fmt.n(lo, 1)} in ${years[vals.indexOf(lo)]}, highest ${fmt.n(hi, 1)} in ${years[vals.indexOf(hi)]}, average ${fmt.n(mean, 1)}.`,
  });
  for (let v = 0; v <= ymax + 1e-9; v += ystep) {
    svg.append(s('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), class: v === 0 ? 'm-axis-line' : 'm-grid' }));
    svg.append(s('text', { x: L - 6, y: y(v) + 3.5, 'text-anchor': 'end', class: 'ct-axis' }, fmt.n(v)));
  }
  const bars = years.map((yr, i) => {
    const r = s('rect', { x: x(i) + bw * 0.16, y: y(vals[i]), width: bw * 0.68, height: Math.max(0, y(0) - y(vals[i])), rx: 2, class: 'm-bar' });
    svg.append(r);
    return r;
  });
  const step = Math.ceil(n / 7);
  for (let i = 0; i < n; i += step) svg.append(s('text', { x: x(i) + bw / 2, y: H - 8, 'text-anchor': 'middle', class: 'ct-axis' }, String(years[i])));
  if (step > 1 && (n - 1) % step) svg.append(s('text', { x: x(n - 1) + bw / 2, y: H - 8, 'text-anchor': 'middle', class: 'ct-axis' }, String(years[n - 1])));
  svg.append(s('line', { x1: L, x2: W - R, y1: y(mean), y2: y(mean), class: 'm-mean' }));
  svg.append(s('text', { x: L + 4, y: y(mean) - 5, class: 'ct-axis m-mean-label' }, `average ${fmt.n(mean, 1)}`));
  svg.append(s('rect', { x: L, y: T, width: W - L - R, height: H - T - B, class: 'm-hit' }));

  const readout = h('p.small.m-readout-head.m-flush');
  const update = () => {
    bars.forEach((b, i) => b.classList.toggle('is-active', i === active));
    const v = vals[active];
    const diff = v - mean;
    readout.textContent = `${years[active]}: ${fmt.n(v, 1)} runs per wicket, ${Math.abs(diff) < 0.05 ? 'level with' : `${fmt.n(Math.abs(diff), 1)} ${diff > 0 ? 'above' : 'below'}`} the ${years[0]}–${years[n - 1]} average.`;
  };
  const fromPointer = (ev) => {
    const i = Math.max(0, Math.min(n - 1, Math.floor((viewX(svg, ev, W) - L) / bw)));
    if (i !== active) { active = i; update(); }
  };
  svg.addEventListener('pointermove', fromPointer);
  svg.addEventListener('pointerdown', fromPointer);
  const frame = h('div.m-kbd-chart', {
    tabindex: '0', role: 'group',
    'aria-label': 'Runs per wicket chart. Use the left and right arrow keys to read each year.',
    onkeydown: (e) => {
      const map = { ArrowRight: active + 1, ArrowLeft: active - 1, Home: 0, End: n - 1 };
      if (!(e.key in map)) return;
      e.preventDefault();
      active = Math.max(0, Math.min(n - 1, map[e.key]));
      update();
    },
  }, svg);
  readout.setAttribute('aria-live', 'polite');
  update();
  return h('div.card.card-pad.m-rpw',
    h('figure.chart-fig.m-figure', frame, h('figcaption', readout)),
    h('details.m-more', h('summary', 'Show these numbers as a table'),
      table([['Year'], ['Runs per wicket', 'r']], years.map((yr, i) => h('tr', h('th.num', { scope: 'row' }, yr), h('td.r.num', fmt.n(vals[i], 2)))).reverse(),
        { caption: 'Runs per wicket in men’s Tests by year', wrapClass: 'm-scroll-y' })));
}

function groupsBlock(groups, meta) {
  const scopes = meta?.scopes || [];
  const byKey = new Map(scopes.map((x) => [x.key, x]));
  const order = ['men-test', 'men-odi', 'men-t20i', 'women-test', 'women-odi', 'women-t20i', 'men-club', 'women-club'];
  const keys = Object.keys(groups).sort((a, b) => ((order.indexOf(a) + 1) || 99) - ((order.indexOf(b) + 1) || 99));
  const labelOf = (k) => byKey.get(k)?.label || (k === 'men-club' ? 'Men’s leagues' : k === 'women-club' ? 'Women’s leagues' : k);
  const members = (g) => {
    const list = (g.scopes || []).filter((k) => k !== g.group);
    if (list.length < 2) return null;
    const names = list.map((k) => byKey.get(k)?.short || byKey.get(k)?.label || k);
    return `${list.length} competitions fitted together: ${names.slice(0, 4).join(', ')}${names.length > 4 ? ` and ${names.length - 4} more` : ''}`;
  };
  const rows = keys.map((k) => {
    const g = groups[k];
    const fitNote = g.adjusted && isNum(g.lambda_bat_fit) && Math.abs(g.lambda_bat_fit - g.lambda_bat) > 0.5
      ? h('div.tiny.faint', `all batters: ${fmt.n(g.lambda_bat_fit)}`) : null;
    return h('tr',
      h('th', { scope: 'row' }, labelOf(k), members(g) ? h('div.tiny.faint.m-members', members(g)) : null),
      h('td.r.num', fmt.n(g.matches)),
      h('td.r.num', millions(g.deliveries)),
      h('td', g.adjusted ? h('span.badge.good', 'Yes') : h('span.badge', { title: `Fewer than ${MIN_MATCHES_TO_ADJUST} matches` }, 'No: too few matches')),
      h('td.r.num', fmt.n(g.lambda_bat), g.adjusted ? fitNote : h('div.tiny.faint', 'fixed default')),
      h('td.r.num', fmt.n(g.lambda_bowl), g.adjusted ? null : h('div.tiny.faint', 'fixed default')));
  });
  return h('div.m-vis-stack',
    table([['Group'], ['Matches', 'r'], ['Deliveries', 'r'], ['Adjusted'], ['Batter penalty (balls)', 'r'], ['Bowler penalty (balls)', 'r']], rows,
      { caption: 'Fitted groups and their shrinkage penalties' }),
    h('p.tiny.faint.m-flush', `A penalty of 600 balls means every record is treated as if it also held 600 perfectly average balls. Groups with fewer than ${MIN_MATCHES_TO_ADJUST} matches are not fitted and use a fixed 400. For batters the larger of the all-batter fit and the top-seven fit is used; the all-batter figure is shown underneath when they differ.`),
    shrinkCalc(groups, keys, labelOf));
}

function shrinkCalc(groups, keys, labelOf) {
  let key = keys.includes('men-test') ? 'men-test' : keys[0];
  const toBalls = (t) => { const v = 30 * (5000 / 30) ** (t / 100); return v < 300 ? Math.round(v / 10) * 10 : Math.round(v / 50) * 50; };
  let t = 55;
  const sel = h('select.select', { id: 'm-shrink-group', onchange: (e) => { key = e.target.value; update(); } },
    keys.map((k) => h('option', { value: k, selected: k === key }, labelOf(k))));
  const range = h('input', { type: 'range', id: 'm-shrink-balls', min: 0, max: 100, step: 1, value: t, class: 'm-range',
    oninput: (e) => { t = Number(e.target.value); update(); } });
  const out = h('output.num', { for: 'm-shrink-balls' });
  const res = h('div.m-shrink-res');
  const row = (who, k, lam) => h('div.m-shrink-row',
    h('span.small', who),
    h('span.meter', { 'aria-hidden': 'true' }, h('span', { style: `width: ${(k * 100).toFixed(1)}%` })),
    h('span.small.num', `keeps ${pct(k)} of the edge`, h('span.tiny.faint', ` · penalty ${fmt.n(lam)}`)));
  function update() {
    const g = groups[key];
    const n = toBalls(t);
    out.textContent = `${fmt.n(n)} balls`;
    range.setAttribute('aria-valuetext', `${fmt.n(n)} balls`);
    clear(res);
    const kb = n / (n + g.lambda_bat), kw = n / (n + g.lambda_bowl);
    res.append(row('A batter', kb, g.lambda_bat), row('A bowler', kw, g.lambda_bowl),
      h('p.small.m-flush', { 'aria-live': 'polite' }, `In ${labelOf(key)}, a batter with ${fmt.n(n)} balls who has added 10 runs per 100 balls above average is rated at ${fmt.n(10 * kb, 1)}.`));
  }
  update();
  return h('div.panel.m-shrink',
    h('div.field-label', 'Try it: how much of a record survives shrinkage'),
    h('div.m-shrink-controls',
      h('div.field', h('label', { for: 'm-shrink-group' }, 'Group'), sel),
      h('div.field', h('label', { for: 'm-shrink-balls' }, 'Balls in the record'), range, out)),
    res);
}

// ------------------------------------------------------------- 5. profiles
function sectionProfiles(ctx) {
  const f = ctx.fam;
  const famBlock = f
    ? h('div.m-vis-stack',
      statGrid([
        [fmt.n(f.training_bowlers), 'bowlers labelled by Wikipedia', 'used to train the classifier'],
        [fmt.n(f.predicted), 'labelled by the model', `only when at least ${pct(f.confidence_threshold)} sure`],
        [fmt.n(f.unresolved), 'left without a type', 'rather than guessed'],
        [pct(f.spin_share), 'of labelled bowlers are spinners', `minimum ${fmt.n(f.min_balls)} balls`],
      ]),
      h('p.tiny.faint.m-flush', `Cross-validated accuracy is ${pct(f.cv_accuracy, 1)} overall and ${pct(f.cv_confident_accuracy, 1)} on the confident labels the site keeps; the classifier check above has the details.`))
    : loadError('The bowling-type classifier summary', ctx.err.fam);

  const ruleRows = [
    ['Edges caught behind, 1.2× peers or more', 'An extra slip or catcher behind the wicket'],
    ['Edges caught behind, 0.8× peers or fewer', 'One fewer slip'],
    ['Caught elsewhere, 1.2× peers (Tests)', 'A bat-pad or gully catcher'],
    ['Caught elsewhere, 1.2× peers (limited overs)', 'A deep catcher for the mis-hit'],
    ['Fours and sixes, 1.15× peers or more', 'Another boundary rider, within the fielding restrictions'],
    ['Fours and sixes, 0.85× peers or fewer', 'A boundary rider brought into the ring'],
    ['Sixes, 1.25× peers or more', 'Boundary riders start at long-on, deep mid-wicket and cow corner'],
    ['Stumped off spin, 1.3× peers or more', 'Keeper up to the stumps, long-on and long-off back'],
  ];

  return section('profiles',
    'Each player page splits a record by bowling type, phase, opponent and more. These are the rules behind those splits.',
    h('div.grid-2.m-cards',
      h('div.card.card-pad.m-card',
        h('h3', 'Every ball counts, not just the dismissals'),
        h('p.small', 'A split such as “against leg-spin” uses every ball the player faced from that kind of bowler, valued with the same opposition-adjusted figures as the selector. Counting only dismissals would mislead: a batter caught five times by leg-spinners while scoring heavily off them is not weak against leg-spin, and a batter who rarely faces it cannot look strong just by surviving.')),
      h('div.card.card-pad.m-card',
        h('h3', 'Flagging strengths and weaknesses'),
        h('p.small', 'A split is flagged only when it differs from the player’s own overall level by more than 1.96 standard errors and rests on enough balls. With several splits per player, about one in twenty splits with no real difference will still be flagged by chance, so treat a single flag as a lead rather than a verdict.'),
        table([['Format'], ['Balls to flag a split', 'r'], ['Balls to list a matchup', 'r']],
          MIN_SPLIT.map(([label, a, b]) => h('tr', h('th', { scope: 'row' }, label), h('td.r.num', fmt.n(a)), h('td.r.num', fmt.n(b)))),
          { caption: 'Minimum balls for splits and matchups' }))),
    h('div.m-sub',
      h('h3', 'Where bowling types come from'),
      h('p.small', 'Cricsheet does not record how anyone bowls. Where Wikipedia gives a style, that is used and marked as coming from Wikipedia. Where it does not, a gradient-boosted classifier predicts pace or spin from how and when the bowler is used (new ball, death overs, late in Tests) and how their wickets fall (stumped, caught behind, bowled, lbw), along with wides and byes. Those labels are marked “model” on profiles. The model only says pace or spin: arm and variety, such as left-arm orthodox, come from Wikipedia alone.'),
      famBlock),
    h('div.m-sub',
      h('h3', 'How field plans are drawn'),
      h('p.small', 'Cricsheet has no shot direction or catch location, so a field cannot be measured directly. What can be measured is how a batter gets out and scores compared with peers: edges caught behind, catches elsewhere, bowled and lbw, stumpings, fours, sixes and singles. A plan starts from a conventional field for the format, phase and bowling type, then the evidence decides how many catchers, ring fielders and boundary riders to use. Where exactly they stand follows convention.'),
      table([['Measured against peers'], ['What changes']],
        ruleRows.map(([a, b]) => h('tr', h('td.small', a), h('td.small', b))),
        { caption: 'Rules that move fielders' }),
      h('p.tiny.faint', 'Starting fields: in Tests, four catchers for pace or two for spin, with two boundary riders. In limited overs the start depends on the phase, from two catchers and two out in the powerplay to none close and five out at the death.')));
}

// ------------------------------------------------------------ 6. XI vs XI
function versusCheckBody(c) {
  const rows = Object.values(c.groups).sort((a, b) => b.held_out - a.held_out);
  return [
    h('p.small', `Win chances on the XI vs XI page are fitted on matches up to 2020 and scored on later ones the fit never saw. Each calibrated group with ${fmt.n(c.min_held_out)} or more held-out matches must beat a naive forecast on Brier score (lower is better).`),
    table([['Group'], ['Held out', 'r'], ['Brier', 'r'], ['Naive', 'r'], ['Favourite won', 'r']],
      rows.map((g) => h('tr', h('th', { scope: 'row' }, g.label), h('td.r.num', fmt.n(g.held_out)),
        h('td.r.num', g.brier.toFixed(3)), h('td.r.num', g.brier_baseline.toFixed(3)), h('td.r.num', pct(g.accuracy, 1)))),
      { caption: 'Held-out scores of the XI vs XI win chances' }),
  ];
}

function debutCheckBody(c) {
  const label = { 'men-test': "Men's Tests", 'men-odi': "Men's ODIs", 'men-t20i': "Men's T20Is",
    'women-test': "Women's Tests", 'women-odi': "Women's ODIs", 'women-t20i': "Women's T20Is" };
  const rows = [];
  for (const [t, kinds] of Object.entries(c.targets)) {
    for (const [k, v] of Object.entries(kinds)) {
      rows.push(h('tr', h('th', { scope: 'row' }, `${label[t] ?? t}, ${k === 'bat' ? 'batting' : 'bowling'}`),
        h('td.r.num', fmt.n(v.players)),
        h('td.r.num', v.judged ? v.mse_prior.toFixed(3) : '–'), h('td.r.num', v.judged ? v.mse_zero.toFixed(3) : '–'),
        h('td.r.num', v.judged ? v.mse_newcomer.toFixed(3) : '–')));
    }
  }
  return [
    h('p.small', `A short record is pulled towards a prior. Here the prior is what the player’s other cricket predicts, through transitions fitted on seasons before ${c.split_year}; it is scored on everyone who debuted in a format from ${c.split_year} on, using only what they had done before their debut, against their first two seasons there. Lower error is better; it must beat the old assumption that a newcomer is an average player.`),
    table([['Format'], ['Debutants', 'r'], ['Prior', 'r'], ['Average player', 'r'], ['Average newcomer', 'r']], rows,
      { caption: 'Error of debut priors on unseen debutants' }),
  ];
}

function sectionVersus(ctx) {
  const vs = ctx.vs;
  const cal = vs?.calibration || {};
  const method = vs?.calibrationMethod || {};
  const groups = Object.entries(cal).sort((a, b) => (b[1].nTest || 0) - (a[1].nTest || 0));
  const reliability = (g) => {
    const bins = (g.bins || []).filter((b) => b.n > 0);
    return h('div.m-rel', { role: 'img', 'aria-label': `${g.label}: predicted against observed win rates` },
      bins.map((b) => h('div.m-rel-row',
        h('span.m-rel-label.tiny', b.hi - b.lo < 0.03 ? `${pct(b.lo, 1)}–${pct(b.hi, 1)}` : `${pct(b.lo)}–${pct(b.hi)}`),
        h('div.m-rel-track',
          h('span.m-rel-pred', { style: { width: `${Math.round(100 * b.predicted)}%` }, title: `Predicted ${pct(b.predicted, 1)}` }),
          h('span.m-rel-obs', { style: { left: `${Math.round(100 * b.observed)}%` }, title: `Observed ${pct(b.observed, 1)} of ${fmt.n(b.n)}` })),
        h('span.tiny.faint.m-rel-n', fmt.n(b.n)))));
  };
  const skipped = Object.values(method.notCalibrated || {});
  return section('versus',
    'XI vs XI picks two elevens with the Best XI engine, turns each into runs per innings, and projects the match between them. Win chances are then fitted on real matches, not assumed.',
    h('div.grid-2.m-cards',
      h('div.card.card-pad.m-card',
        h('h3', 'From players to runs per innings'),
        h('p.small', 'Every player carries the model’s adjusted runs per ball: added when batting, saved when bowling, against a Full-Member average. A batter’s rate is spread over the share of an innings their position usually faces; the best bowlers take the most overs, within the format’s limit and near their usual workload. Overs a side cannot cover go to part-timers at the rate occasional bowlers really concede in that format. Innings lengths, position shares, par and that part-time rate come from the same archive.'),
        h('p.small', 'Side A’s projected score is par plus A’s batting minus B’s bowling, and the reverse for B. In Tests the per-innings gap is multiplied by the innings a side usually bats.')),
      h('div.card.card-pad.m-card',
        h('h3', 'Sides from anywhere, in any shape'),
        h('p.small', 'Each side can be picked from any international format or league and played as a Test, ODI or T20I. A player’s own record in the match format comes first, batting and bowling each on its own: over his side’s years if he did it then, otherwise his record up to then, with the same filters that format’s Best XI uses. Only what he never did in the format is rated on what his other cricket predicts. The shape can be the Best XI’s or free: the best eleven of any kind, all batters or all bowlers. Both pages share a swap preview that keeps the other ten players. Manual picks may use thin or earlier recorded evidence, with labels; any shape or cap change is shown before you confirm. The same exact selector assigns roles within your chosen eleven.'),
        h('p.small', 'Records do not carry across one to one. For each pair of competitions a slope and an offset are fitted on players who played both: in men’s cricket a league batting edge carries into T20Is almost whole but drops about 0.045 runs a ball, only about three quarters of it reaches ODIs, and less than half of a T20I edge reaches Tests. First-class records are not in the ratings, so Test priors lean on white-ball cricket.')),
      h('div.card.card-pad.m-card', { style: { gridColumn: '1 / -1' } },
        h('h3', 'Where the win chances come from'),
        h('p.small', `For ${fmt.n(Object.values(cal).reduce((a, g) => a + (g.nTrain || 0) + (g.nTest || 0), 0))} real matches the two actual elevens were rated from the ${fmt.n(method.window ?? 4)} seasons before the game, so nothing from the match itself leaks in. A logistic curve (an ordered one with a draw band for Tests) turns the projected margin into chances, fitted to ${method.splitYear ?? 2020} and checked on the years after. A home-side term is fitted and then left out, so the page shows a neutral venue.`),
        h('p.small', 'Calibration rates real elevens without priors: priors use the whole archive and would leak later seasons into earlier matches. Win chances for a side picked outside the match format rest on predicted ratings the calibration did not test.'),
        h('p.small', 'Ratings know nothing about pitch, weather, toss, form beyond each side’s years, or injuries. The chances describe how often sides rated this far apart have won, not a forecast of any real match.'))),
    groups.length ? h('div.m-sub',
      h('h3', 'How well the chances held up on unseen matches'),
      h('p.small', 'Each bar is a band of predicted chances for the favourite; the bar shows the average prediction and the dot what actually happened. Dots near the end of their bars mean the chances were honest.'),
      h('div.m-rel-grid', groups.map(([, g]) => h('div.card.card-pad.m-rel-card',
        h('div.m-rel-head', h('strong', g.label),
          h('span.tiny.muted', `${fmt.n(g.nTest)} held out, ${g.testYears?.[0]}–${g.testYears?.[1]} · favourite won ${pct(g.accuracy, 1)}`)),
        reliability(g))))) : loadError('The XI vs XI calibration (model/versus.json)', ctx.err.vs || 'no calibrated groups in this build'),
    skipped.length ? h('p.tiny.faint', `No win chances for ${skipped.map((g) => `${g.label} (${g.reason})`).join('; ')}.`) : null);
}

// ---------------------------------------------------------- 7. limitations
function sectionLimitations(ctx) {
  const oos = (ctx.validation?.checks || []).find((c) => c.scopes && c.split_year != null);
  let t20 = ['Strike rate can beat the adjustment in T20Is.', 'In the out-of-sample check, T20I strike rate alone has predicted later output slightly better than the adjusted value. See the checks above for this build’s figures.'];
  const t = oos?.scopes?.['men-t20i'];
  if (t) {
    const col = oosColumns(t.spearman);
    const sr = t.spearman[col.sr], adj = t.spearman[col.adj];
    if (isNum(sr) && isNum(adj)) {
      t20 = sr > adj
        ? ['Strike rate still wins in T20Is.', `In the out-of-sample check, men’s T20I strike rate alone ranked later output slightly better than the adjusted value (${sr.toFixed(2)} against ${adj.toFixed(2)}), as reported in the checks above.`]
        : ['T20Is are the closest call.', `In this build’s out-of-sample check the adjusted value beat strike rate in men’s T20Is, but only by ${(adj - sr).toFixed(2)} (${adj.toFixed(2)} against ${sr.toFixed(2)}).`];
    }
  }
  const wt = (ctx.meta?.scopes || []).find((x) => x.key === 'women-test');
  const items = [
    ['No ball-tracking.', 'Cricsheet has no pitch maps, wagon wheels, pace or line and length. Field positions therefore follow convention, and nothing here knows where a ball pitched.'],
    ['Captaincy is formal appointment only.', 'Leadership counts matches as appointed captain in Wikipedia’s records. It says nothing about how well anyone captained.'],
    ['Retirements and squads can lag.', 'Both come from Wikipedia text and tables, which can trail announcements by days or weeks.'],
    ['Overseas status is inferred.', 'In leagues it comes from a player’s international appearances, or from Wikipedia when they have none.'],
    ['Careers before about 2002 rely on totals.', 'The all-eras mode uses career runs, wickets and averages adjusted to each decade, with no ball-by-ball context.'],
    ['The women’s Test sample is small.', `${wt ? `${plural(wt.matches, 'match', 'matches')} in all, so` : 'There are too few matches, so'} values there are centred on the average but not adjusted for opposition.`],
    ['Afghanistan’s men are missing.', 'Cricsheet withholds their matches, which also shortens their opponents’ records.'],
    t20,
  ];
  return section('limitations',
    'What the data cannot tell you, stated plainly so you can weigh the results.',
    h('ul.m-limits', items.map(([head, text]) => h('li', h('strong', head), ' ', text))));
}

// ------------------------------------------------------------------ 8. run
function sectionRun(ctx) {
  const cmds = [
    ['Install the package from a clone of the repository.', 'pip install -e .'],
    ['Download Cricsheet’s full archive and people register. Nothing is downloaded when the archive has not changed.', 'best-eleven fetch'],
    ['Ingest the archive, value every ball, run the checks and write the site data. No network needed.', 'best-eleven build'],
    ['Pick an eleven in the terminal, using the same selection engine as this site.', 'best-eleven select --scope men-test --team "South Africa" --availability squad'],
    ['Serve the site on your machine at http://127.0.0.1:8765 and open it.', 'best-eleven serve --open'],
    ['Refresh the Wikipedia and Wikidata snapshots: squads, captaincy, retirements, styles and historic careers. Needs the network; run build again afterwards.', 'best-eleven enrich'],
  ];
  const end = dateFmt(ctx.meta?.dataEnd);
  return section('run',
    'The whole pipeline is one Python package. You need Python 3.11 or later, and Node.js 18 or later for the select command.',
    h('ol.m-cmds', cmds.map(([desc, cmd], i) => {
      const code = h('code', cmd);
      return h('li.m-cmd-item',
        h('p.small.m-cmd-desc', desc),
        h('div.m-cmd', h('pre', { tabindex: '0', 'aria-label': `Command ${i + 1}: ${cmd}` }, code), copyButton(cmd, `Copy command: ${cmd}`, code)));
    })),
    h('p.small', `A GitHub Actions workflow rebuilds the site from Cricsheet every week${end ? `; this build has matches up to ${end}` : ''}. The source is on `, h('a', { href: REPO, rel: 'noopener' }, 'GitHub'), '.'));
}

// -------------------------------------------------------------- 9. sources
function sectionSources() {
  const rows = [
    { name: 'Cricsheet', href: 'https://cricsheet.org', what: 'Ball-by-ball match data and the people register that links player identities.',
      licence: 'Open Data Commons Attribution 1.0 (ODC-By)', lhref: 'https://opendatacommons.org/licenses/by/1-0/' },
    { name: 'Wikipedia', href: 'https://en.wikipedia.org', what: 'Batting and bowling styles, squads, captaincy records, retirements and the national player lists behind the all-eras mode.',
      licence: 'Creative Commons Attribution-ShareAlike 4.0', lhref: 'https://creativecommons.org/licenses/by-sa/4.0/' },
    { name: 'Wikidata', href: 'https://www.wikidata.org', what: 'Identifiers that link a Wikipedia article to the player’s ESPNcricinfo id and so to Cricsheet’s register.',
      licence: 'CC0 1.0 public domain dedication', lhref: 'https://creativecommons.org/publicdomain/zero/1.0/' },
    { name: 'This project’s code', href: REPO, what: 'The pipeline, the selection engine and this site.',
      licence: 'MIT licence', lhref: `${REPO}/blob/main/LICENSE` },
  ];
  return section('sources',
    'Where everything comes from, and the terms each part carries.',
    h('ul.m-sources', rows.map((r) => h('li.card.card-pad',
      h('h3', h('a', { href: r.href, rel: 'noopener' }, r.name)),
      h('p.small.m-flush', r.what),
      h('p.small.m-licence', h('span.muted', 'Licence: '), h('a', { href: r.lhref, rel: 'noopener license' }, r.licence))))),
    h('p.small.muted', 'The MIT licence covers the code only. Match data and Wikipedia material keep their own licences and attribution requirements, including when they appear in this site’s data files.'));
}
