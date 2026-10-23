// XI vs XI: two elevens, each picked wherever you like, played in one format.
import { h, clear, fmt, debounce, initials } from '../ui/dom.js';
import * as data from '../data.js';
import { setQuery, isLive } from '../app.js';
import { rememberTitle, saved as savedPage } from '../memory.js';
import { PRESETS, SLOT_TYPES, buildPool } from '../engine/select.js';
import { historicPool } from '../engine/historic.js';
import { comparable, groupKey, ownRates, crossRates, matchAggregate, matchCareer, matchRecord, sideProfile, project } from '../engine/versus.js';
import { stats as statsOf } from '../engine/metrics.js';
import { defaults, fromQuery, queryString, selectableTeams, resolve, selectFor, xiTitle, compositionText,
  COMPOSITIONS, engineSettings } from '../xistate.js';
import { icon, ROLE_ICON, logoMark } from '../ui/icons.js';
import { teamBadge } from '../ui/teams.js';
import { playerHref } from '../ui/links.js';

const SIDES = ['a', 'b'];
const LENSES = ['balanced', 'quality', 'form', 'alltime', 'legacy', 'experience'];
const MATCH = {
  Test: { label: 'Test', a: 'a Test', plural: 'Tests' },
  ODI: { label: 'ODI', a: 'an ODI', plural: 'ODIs' },
  T20I: { label: 'T20I', a: 'a T20I', plural: 'T20Is' },
  league: { label: 'League match', a: 'a match', plural: 'matches' },
};
const SWAP_PAGE = 60;
const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

const stateOf = (qs) => defaults(fromQuery(new URLSearchParams(qs || '')));
const shortYears = (st) => (st.from === st.to ? String(st.from)
  : `${st.from}–${String(st.to).slice(String(st.from).slice(0, 2) === String(st.to).slice(0, 2) ? 2 : 0)}`);
const ids = (str) => new Set(str ? str.split(',') : []);

export async function mount(root, route) {
  const [meta, model] = await Promise.all([data.meta(), data.versusModel().catch(() => null)]);
  const page = h('div.page.vs-page');
  root.append(page);

  const st = initial(route);
  const side = { a: {}, b: {} };
  let match = null, matchScope = null, priors = null, dead = false;
  let swapDialog = null;
  let indexCache = null;
  const resultCache = new Map();   // side settings -> selection, so an unchanged side is not picked again

  const hero = h('header.vs-hero');
  const arenaEl = h('section.card.card-pad.vs-arena', { 'aria-label': 'The match' });
  const sidesEl = h('section.vs-sides', { 'aria-label': 'The two elevens' });
  const results = h('div.vs-results', { 'aria-live': 'polite' });
  page.append(hero, arenaEl, sidesEl, results);

  /** No settings in the link: the Test World XI against the T20I World XI, as an ODI. */
  function initial(r) {
    const q = r.query;
    if (q.get('a') == null) return { a: defaults({ f: 'Test' }), b: defaults({ f: 'T20I' }), m: 'ODI' };
    const a = stateOf(q.get('a'));
    const b = q.get('b') != null ? stateOf(q.get('b')) : defaults({ g: a.g, f: a.f });
    return { a, b, m: q.get('m') || (a.tier === 'league' ? 'league' : a.f) };
  }

  const scopeMeta = (key) => meta.scopes.find((s) => s.key === key);
  const isHist = () => st.a.mode === 'hist';

  /** Both sides share the evidence base and gender; all eras also share the format. */
  function align() {
    const a = st.a, b = st.b;
    b.g = a.g; b.mode = a.mode;
    if (a.mode === 'hist') {
      for (const x of [a, b]) { x.tier = 'national'; if (!['Test', 'ODI'].includes(x.f)) x.f = 'Test'; }
      b.f = a.f;
      st.m = a.f;
      return;
    }
    if (!MATCH[st.m]) st.m = a.tier === 'league' ? 'league' : a.f;
  }

  async function load() {
    align();
    // Every file the matchup needs is fetched at once rather than one after another.
    const intl = !isHist() && st.m !== 'league';
    const matchKey = intl ? `${st.a.g === 'male' ? 'men' : 'women'}-${st.m.toLowerCase()}` : null;
    const crossing = intl && SIDES.some((s) => st[s].tier !== 'national' || st[s].f !== st.m);
    const [ra, rb, ms, pr] = await Promise.all([resolve(st.a, meta), resolve(st.b, meta),
      matchKey ? data.scope(matchKey) : null,
      crossing && !priors ? data.priorsModel().catch(() => null) : priors]);
    Object.assign(side.a, ra); Object.assign(side.b, rb);
    priors = pr;
    matchScope = null;
    indexCache = null;
    if (isHist()) return;
    if (st.m === 'league' && !comparable(side.a.scope, side.b.scope)) {
      st.m = 'T20I';
      return load();
    }
    matchScope = ms ?? side.a.scope;
    if (SIDES.some((s) => !comparable(side[s].scope, matchScope)) && !priors) priors = await data.priorsModel().catch(() => null);
  }

  function matchIndex() {
    if (!indexCache) indexCache = new Map(matchScope.players.id.map((id, i) => [id, i]));
    return indexCache;
  }
  // Aggregates are memoised by the engine, so asking again is cheap.
  const matchCtx = (s) => ({ index: matchIndex(), agg: matchAggregate(matchScope, st[s]), career: matchCareer(matchScope, st[s]) });

  function selectCached(s) {
    const x = side[s];
    const key = `${x.scope?.key ?? x.hist?.key}|${queryString(st[s])}`;
    if (!resultCache.has(key)) {
      resultCache.set(key, selectFor(st[s], x));
      if (resultCache.size > 16) resultCache.delete(resultCache.keys().next().value);
    }
    return resultCache.get(key);
  }
  /** Per-ball rates of an eleven (or one player) in the match format. */
  function ratesFor(s, xi, k) {
    const x = side[s];
    if (comparable(x.scope, matchScope)) return ownRates(xi, x.scope, k);
    return crossRates(xi, { scope: x.scope, k: model.groups[groupKey(x.scope)] ?? k },
      { scope: matchScope, priors, k, ...matchCtx(s) });
  }

  function compute() {
    for (const s of SIDES) {
      const x = side[s];
      x.result = selectCached(s);
      x.title = xiTitle(st[s], x);
      x.prof = null; x.rates = null;
    }
    match = null;
    if (isHist() || side.a.result.error || side.b.result.error) return;
    const key = groupKey(matchScope);
    const k = model?.groups?.[key];
    if (!k) return;
    for (const s of SIDES) {
      side[s].rates = ratesFor(s, side[s].result.xi, k);
      side[s].prof = sideProfile(side[s].result.xi, side[s].scope, k, side[s].rates);
    }
    const cal = model.calibration?.[key] ?? null;
    match = { k, cal, key, ...project(side.a.prof, side.b.prof, k, cal) };
  }

  // -------------------------------------------------------------- naming
  const formatOf = (s) => (st[s].mode === 'hist' ? 'all-time' : side[s].scope.tier === 'league' ? side[s].scope.short : side[s].scope.format);
  function baseName(s) {
    const x = side[s], t = st[s];
    if (t.team) return t.team;
    if (t.mode === 'bbb' && x.scope?.tier === 'league') return `${x.scope.short} XI`;
    return t.mode === 'hist' ? 'World all-time XI' : 'World XI';
  }
  function name(s) {
    const o = s === 'a' ? 'b' : 'a';
    const base = baseName(s);
    if (base !== baseName(o)) return base;
    if (formatOf(s) !== formatOf(o)) return `${base.replace(/ XI$/, '')} ${formatOf(s)} XI`;
    return st[s].mode === 'bbb' ? `${base} ${shortYears(st[s])}` : base;
  }
  function colour(s) {
    const c = (x) => (st[x].team ? data.teamColour(st[x].team) : null);
    const ca = c('a') || 'var(--pitch)';
    let cb = c('b') || 'var(--sky)';
    if (cb === ca) cb = 'var(--gold)';
    return s === 'a' ? ca : cb;
  }
  const badge = (s, size) => (st[s].team ? teamBadge(st[s].team, { size }) : logoMark(size));
  const M = () => MATCH[st.m] || MATCH.ODI;
  /** What a zero means: a Full-Member average internationally, the leagues' own average otherwise. */
  const baseline = (what) => (matchScope?.tier === 'league' ? `an average ${what} in these leagues` : `a Full-Member average ${what}`);

  // ------------------------------------------------------------- commit
  const commit = debounce(async (reload = true) => {
    if (dead) return;
    setQuery({ a: queryString(st.a), b: queryString(st.b), m: st.m }, route);
    if (reload) await load();
    if (dead) return;
    compute();
    renderAll();
  }, 60);

  function set(s, patch, reload = true) {
    Object.assign(st[s], patch);
    commit(reload);
  }
  const freshSide = { team: '', from: null, to: null, lock: '', excl: '', mos: null };

  // ---------------------------------------------------------------- hero
  function renderHero() {
    clear(hero);
    const sub = (s) => {
      const t = st[s], x = side[s];
      if (t.mode === 'hist') return `All eras · ${PRESETS[t.lens]?.label ?? 'Custom'} lens`;
      return `${x.scope.label} ${shortYears(t)} · ${PRESETS[t.lens]?.label ?? 'Custom'} lens`;
    };
    const team = (s) => h(`div.vs-team.${s}`, { style: { '--c': colour(s) } },
      h('div.vs-badge', badge(s, 64)),
      h('div.vs-team-name', name(s)),
      h('div.vs-team-sub', sub(s)));
    hero.append(
      h('div.eyebrow', 'XI vs XI'),
      h('div.vs-hero-row', team('a'),
        h('div.vs-mid', h('div.vs-ring', { 'aria-hidden': 'true' }, 'vs'),
          h('div.vs-match-chip', isHist() ? `${st.a.f} records` : M().label)),
        team('b')),
      verdict());
    if (isLive(route)) rememberTitle('versus', `${name('a')} vs ${name('b')}`);
  }

  function verdict() {
    const err = SIDES.find((s) => side[s].result.error);
    if (err) return h('p.vs-verdict-line', `${name(err)} cannot field a full eleven with these settings.`);
    if (isHist()) return h('p.vs-verdict-line', histVerdict());
    if (!match) return h('p.vs-verdict-line', 'No projection for this format: too few recent matches to set innings lengths.');
    const e = match.edge, lead = e >= 0 ? 'a' : 'b';
    const line = Math.abs(e) < 0.5 ? 'Dead level on paper'
      : `${name(lead)} by ${fmt.n(Math.abs(e))} ${Math.abs(e) >= 1.5 ? 'runs' : 'run'} ${M().a}`;
    return h('div.vs-verdict', h('p.vs-verdict-line', line), match.chances ? odds(match.chances) : null);
  }

  function odds(c) {
    const parts = [['a', c.a, name('a')], ['draw', c.draw, 'Draw'], ['b', c.b, name('b')]].filter(([, p]) => p >= 0.005);
    const label = parts.map(([, p, n]) => `${n} ${fmt.pct(p)}`).join(', ');
    return h('div.vs-odds', { role: 'img', 'aria-label': `Win chances: ${label}` },
      parts.map(([k, p, n]) => h(`span.vs-odds-seg.${k}`, {
        style: { flexGrow: String(Math.max(p, 0.02)), '--c': k === 'draw' ? 'var(--faint)' : colour(k) },
        title: `${n} ${fmt.pct(p, 1)}`,
      }, p >= 0.09 ? h('span', `${k === 'draw' ? 'Draw ' : ''}${fmt.pct(p)}`) : null)));
  }

  // --------------------------------------------------------------- arena
  function seg(options, value, onPick, label) {
    return h('div.seg', { role: 'group', 'aria-label': label },
      options.map(([v, text, disabled, title]) => h('button', {
        type: 'button', 'aria-pressed': String(value === v), disabled: !!disabled, title: title || null, onclick: () => onPick(v),
      }, text)));
  }

  function renderArena() {
    clear(arenaEl);
    const hist = isHist();
    const leaguesComparable = !hist && st.a.tier === 'league' && st.b.tier === 'league' && comparable(side.a.scope, side.b.scope);
    arenaEl.append(
      h('div.vs-arena-row',
        h('div.vs-field', h('span.vs-field-label', 'Evidence'),
          seg([['bbb', 'Ball by ball'], ['hist', 'All eras']], st.a.mode, (v) => {
            for (const s of SIDES) {
              Object.assign(st[s], freshSide, v === 'hist'
                ? { mode: v, tier: 'national', f: ['Test', 'ODI'].includes(st[s].f) ? st[s].f : 'Test', lens: 'legacy', ...PRESETS.legacy.weights }
                : { mode: v, lens: 'balanced', ...PRESETS.balanced.weights, hl: PRESETS.balanced.halfLife });
            }
            commit();
          }, 'Evidence base')),
        h('div.vs-field', h('span.vs-field-label', 'Players'),
          seg([['male', 'Men'], ['female', 'Women']], st.a.g, (v) => {
            for (const s of SIDES) Object.assign(st[s], freshSide, { g: v, lg: v === 'male' ? 'ipl' : 'wpl' });
            commit();
          }, 'Gender')),
        h('div.vs-field', h('span.vs-field-label', 'Played as'),
          hist
            ? seg([['Test', 'Test'], ['ODI', 'ODI']], st.a.f, (v) => { for (const s of SIDES) Object.assign(st[s], freshSide, { f: v }); commit(); }, 'Format')
            : seg([['Test', 'Test'], ['ODI', 'ODI'], ['T20I', 'T20I'],
              ['league', 'League', !leaguesComparable, leaguesComparable ? null : 'Both sides must come from leagues of the same format']],
            st.m, (v) => { st.m = v; commit(); }, 'Match format'))),
      h('p.tiny.muted.vs-arena-note', hist
        ? 'All eras compares career records from Wikipedia’s national lists, adjusted to each decade’s average. There is no ball-by-ball projection across eras.'
        : st.m === 'league'
          ? 'Both sides come from leagues of the same format, rated by one model, so their own figures compare directly.'
          : `Pick each side from any format or league; both play ${M().a}. Each player’s own ${M().label} batting and bowling are used first: over his side’s years, or his ${M().label} record up to then if he did none in those years. Only what he never did in ${M().plural} is rated on what his other cricket predicts.`));
  }

  // --------------------------------------------------------------- sides
  function renderSides() {
    clear(sidesEl);
    sidesEl.append(sidePanel('a'),
      h('div.vs-swap', h('button.icon-btn', {
        type: 'button', 'aria-label': 'Swap the two sides', title: 'Swap sides',
        onclick: () => { const t = st.a; st.a = st.b; st.b = t; commit(); },
      }, icon('shuffle', { size: 18 }))),
      sidePanel('b'));
  }

  function sidePanel(s) {
    const t = st[s], x = side[s], hist = t.mode === 'hist';
    const panel = h(`div.card.card-pad.vs-side.${s}`, { style: { '--c': colour(s) }, 'aria-label': `Side ${s.toUpperCase()}` });
    panel.append(h('div.vs-side-head',
      h('span.vs-side-tag', s.toUpperCase()),
      h('div.vs-side-title', h('strong', x.title || name(s)))));

    if (!hist) {
      panel.append(h('div.vs-field-col', h('span.vs-field-label', 'Picked from'),
        seg([['national', 'International'], ['league', 'Leagues']], t.tier,
          (v) => set(s, { ...freshSide, tier: v, lg: t.g === 'male' ? 'ipl' : 'wpl' }), 'Competition')));
      if (t.tier === 'national') {
        panel.append(seg([['Test', 'Test'], ['ODI', 'ODI'], ['T20I', 'T20I']], t.f, (v) => set(s, { f: v }), 'Format'));
      } else {
        const opts = meta.scopes.filter((l) => l.tier === 'league' && l.gender === t.g)
          .sort((p, q) => (q.featured - p.featured) || q.matches - p.matches);
        panel.append(h('label.vs-field-col', h('span.sr-only', 'League'),
          h('select.select', { onchange: (e) => set(s, { ...freshSide, lg: e.target.value }) },
            opts.map((l) => h('option', { value: l.key, selected: l.key === t.lg }, l.label)))));
      }
    }
    const teams = hist ? x.hist.countries : x.scope.teams;
    const world = t.tier === 'league' ? 'All franchises' : 'World XI';
    panel.append(h('label.vs-field-col', h('span.vs-field-label', t.tier === 'league' ? 'Franchise' : 'Team'),
      h('select.select', { onchange: (e) => set(s, { team: e.target.value, lock: '', excl: '' }) },
        h('option', { value: '' }, world),
        selectableTeams([...teams], t.tier).map((n) => h('option', { value: n, selected: n === t.team }, n)))));

    if (!hist) {
      const [y0, y1] = x.scope.years;
      const years = []; for (let y = y0; y <= y1; y++) years.push(y);
      const chips = [['Last 2', y1 - 1], ['Last 4', y1 - 3], ['Last 10', y1 - 9], ['All', y0]]
        .filter(([label, from]) => label === 'All' || from > y0);
      panel.append(h('div.vs-field-col', h('span.vs-field-label', 'Years'),
        h('div.chips', chips.map(([label, from]) => h('button.chip', {
          type: 'button', 'aria-pressed': String(t.from === from && t.to === y1),
          onclick: () => set(s, { from, to: y1 }),
        }, label))),
        h('div.vs-years',
          h('select.select', { 'aria-label': 'From', onchange: (e) => set(s, { from: Math.min(+e.target.value, t.to) }) },
            years.map((y) => h('option', { value: y, selected: y === t.from }, y))),
          h('span.muted', 'to'),
          h('select.select', { 'aria-label': 'To', onchange: (e) => set(s, { to: Math.max(+e.target.value, t.from) }) },
            years.map((y) => h('option', { value: y, selected: y === t.to }, y))))));
      panel.append(h('div.vs-field-col', h('span.vs-field-label', 'Who is available'),
        seg([['squad', 'Squad', !x.scope.availability.squads], ['active', 'Active'], ['any', 'Everyone']], t.av,
          (v) => set(s, { av: v }), 'Availability')));
    }
    panel.append(h('label.vs-field-col', h('span.vs-field-label', 'Lens'),
      h('select.select', { onchange: (e) => set(s, { lens: e.target.value, ...PRESETS[e.target.value].weights, hl: PRESETS[e.target.value].halfLife }) },
        t.lens === 'custom' ? h('option', { value: 'custom', selected: true }, 'Custom (from Best XI)') : null,
        LENSES.map((k) => h('option', { value: k, selected: k === t.lens }, PRESETS[k].label)))));

    const other = s === 'a' ? 'b' : 'a';
    panel.append(h('div.vs-field-col', h('span.vs-field-label', 'Shape'),
      h('div.vs-shape',
        h('select.select', { 'aria-label': 'Team shape', onchange: (e) => set(s, { comp: e.target.value }, false) },
          Object.entries(COMPOSITIONS).map(([k, c]) => h('option', { value: k, selected: k === (t.comp || ''), title: c.note }, c.label))),
        (t.comp || '') !== (st[other].comp || '') ? h('button.btn.sm.ghost', {
          type: 'button', onclick: () => { st[other].comp = t.comp; commit(false); },
        }, 'Use for both') : null),
      h('span.tiny.faint', COMPOSITIONS[t.comp || '']?.note ?? '')));

    const changes = ids(t.lock).size + ids(t.excl).size;
    if (changes) {
      panel.append(h('div.vs-changes.small',
        icon('shuffle', { size: 14 }),
        h('span', `${ids(t.lock).size} picked by you, ${ids(t.excl).size} left out`),
        h('button.btn.sm.ghost', { type: 'button', onclick: () => set(s, { lock: '', excl: '' }, false) }, 'Undo changes')));
    }

    const mine = savedPage('select');
    panel.append(h('div.vs-side-actions',
      mine ? h('button.btn.sm', {
        type: 'button', title: mine.title ? `Use ${mine.title}` : 'Use the XI from the Best XI page',
        onclick: () => {
          const next = stateOf(mine.href.split('?')[1]);
          if (next.mode !== st[other].mode) Object.assign(st[other], freshSide, { mode: next.mode });
          st[s] = next;
          commit();
        },
      }, icon('room', { size: 15 }), 'Use my Best XI') : null,
      h('a.btn.sm.ghost', { href: `#/?${queryString(t)}` }, 'Edit in Best XI')));
    return panel;
  }

  // ------------------------------------------------------------- results
  /** Why a side has no eleven, in cricket terms where the engine says which slots ran short. */
  function whyNoXI(s) {
    const r = side[s].result;
    const short = (r.shortfall || []).filter((x) => x.have < x.need);
    if (!short.length) return r.error;
    return `no eleven of this shape: ${short.map((x) => `${x.need} ${(SLOT_TYPES[x.type]?.label ?? x.type).toLowerCase()}${x.need > 1 ? 's' : ''} needed, ${x.have} available`).join('; ')}.`;
  }

  function renderResults() {
    clear(results);
    const broken = SIDES.filter((s) => side[s].result.error);
    if (broken.length) {
      results.append(h('div.notice.error', h('div',
        broken.map((s) => h('p', h('strong', `${name(s)}: `), whyNoXI(s))),
        h('p.small', 'Widen the years, allow everyone, free the shape, or pick another team. Nothing is projected from an incomplete eleven.'))));
      return;
    }
    const setAside = SIDES.filter((s) => side[s].result.droppedLocks?.length)
      .map((s) => h('p.small.muted.vs-shared', icon('info', { size: 15 }),
        ` ${side[s].result.droppedLocks.length === 1 ? 'One of your picks for' : `${side[s].result.droppedLocks.length} of your picks for`} ${name(s)} ${side[s].result.droppedLocks.length === 1 ? 'has' : 'have'} no record under these settings, so ${side[s].result.droppedLocks.length === 1 ? 'is' : 'are'} left out until you change them back.`));
    const reshaped = SIDES.filter((s) => side[s].result.reshaped)
      .map((s) => h('p.small.muted.vs-shared', icon('shuffle', { size: 15 }),
        ` No ${name(s)} eleven of the usual shape could be filled from the players available, so it plays ${compositionText(side[s].result.reshaped)}.`));
    const blocks = isHist()
      ? [histBoard(), slotBySlot(), tape(), sharedPlayers(), notes()]
      : [match && board(), match && whereWon(), slotBySlot(), tape(), sharedPlayers(), notes()];
    results.append(...setAside, ...reshaped, ...blocks.filter(Boolean));
    if (!reducedMotion()) results.querySelectorAll('[data-count]').forEach(countUp);
  }

  function countUp(el) {
    const end = Number(el.dataset.count);
    const t0 = performance.now(), dur = 900;
    const step = (now) => {
      const p = Math.min(1, (now - t0) / dur), e = 1 - (1 - p) ** 3;
      el.textContent = fmt.n(end * e);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function board() {
    const { k, cal } = match;
    const score = (s, v) => h(`div.vs-score.${s}`, { style: { '--c': colour(s) } },
      h('div.vs-score-team', badge(s, 22), h('span', name(s))),
      h('div.vs-score-num', { 'data-count': Math.round(v) }, fmt.n(v)),
      h('div.vs-score-sub', `per innings · ${fmt.signed(v - k.par, 0)} on par`));
    const card = h('section.card.card-pad.vs-board', { 'aria-labelledby': 'vs-board-title' },
      h('h2.display.vs-h', { id: 'vs-board-title' }, 'The projected match'),
      h('div.vs-scoreboard', score('a', match.scoreA), h('div.vs-score-vs', 'v'), score('b', match.scoreB)),
      h('p.small.muted', `Each side bats against the other’s attack on an average pitch at a neutral venue. Par is ${fmt.n(k.par)}, the mean first innings in ${parLabel()}.`
        + (k.innings > 1.05 ? ` A Test side bats about ${fmt.n(k.innings, 1)} times, so the margin is the per-innings gap times ${fmt.n(k.innings, 2)}.` : '')));
    if (SIDES.some((s) => !comparable(side[s].scope, matchScope))) {
      const all = SIDES.flatMap((s) => side[s].prof.players);
      const n = (f) => all.filter((p) => p.from === f).length;
      const parts = [`${n('record')} of the 22 on their own ${M().label} record in their side’s years`];
      if (n('career')) parts.push(`${n('career')} on their whole ${M().label} record, having played none in those years`);
      const pred = n('prior');
      card.append(h('p.small.muted', `Rated in ${M().plural}: ${parts.join(', ')}.`,
        pred ? ` ${pred} ${pred === 1 ? 'has' : 'have'} never played ${M().plural} and ${pred === 1 ? 'is' : 'are'} rated on what ${pred === 1 ? 'his' : 'their'} other cricket predicts.` : ''));
    }
    card.append(match.chances ? calNote(cal) : noCalNote());
    return card;
  }

  function parLabel() {
    const k = match.k, sc = matchScope;
    return `${sc.tier === 'league' ? `${sc.gender === 'female' ? 'women’s' : 'men’s'} ${sc.family === 'hundred' ? 'Hundred' : 'T20 league'} matches` : sc.label.replace(/^./, (c) => c.toLowerCase())} from ${k.years[0]} to ${k.years[1]} (${fmt.n(k.n)} innings)`;
  }

  function calNote(cal) {
    const fav = Math.max(match.chances.a, match.chances.b);
    const bins = Array.isArray(cal.bins) ? cal.bins : [];
    const bin = bins.find((b, i) => b.n > 0 && fav >= b.lo && (fav < b.hi || (i === bins.length - 1 && fav <= b.hi)));
    const [y0, y1] = cal.testYears || [];
    const plural = M().plural;
    return h('p.small.muted.vs-cal',
      `Win chances are calibrated on real ${plural}: both actual elevens rated from the seasons before each game. `
      + `Checked on ${fmt.n(cal.nTest)} later ${plural}${y0 ? ` (${y0}–${y1})` : ''}, the favourite won ${fmt.pct(cal.accuracy)}${cal.model === 'ordered' ? ' of them' : ''}.`,
      bin ? ` Sides given ${fmt.pct(bin.lo)}–${fmt.pct(bin.hi)} there won ${fmt.pct(bin.observed)} of ${fmt.n(bin.n)}.` : '',
      SIDES.some((s) => !comparable(side[s].scope, matchScope) || st[s].comp)
        ? ` Those games were between real elevens picked for the format; a side picked elsewhere or built in a free shape leans more on predicted ratings and part-time bowling, which that check never saw.` : '');
  }

  /** Why a format has no win chances, from the build's own record. */
  function noCalNote() {
    const why = model?.calibrationMethod?.notCalibrated?.[groupKey(matchScope)]?.reason;
    return h('p.small.muted', `No win chances for this format${why ? `: ${why}` : ''}. The projected margin still stands.`);
  }

  function whereWon() {
    const A = side.a.prof, B = side.b.prof;
    const inn = match.k.innings;
    const att = (P, fam) => P.attack.find((x) => x.fam === fam) || { share: 0, runs: 0 };
    const rows = [
      ...A.bands.map((band, i) => [band.label + (i === 0 ? ' (1–3)' : i === 1 ? ' (4–7)' : ' (8–11)'), band.runs * inn, B.bands[i].runs * inn, 'Runs added batting']),
      ['Pace bowling', att(A, 'pace').runs * inn, att(B, 'pace').runs * inn, 'Runs saved bowling',
        `${fmt.pct(att(A, 'pace').share)} of overs`, `${fmt.pct(att(B, 'pace').share)} of overs`],
      ['Spin bowling', att(A, 'spin').runs * inn, att(B, 'spin').runs * inn, 'Runs saved bowling',
        `${fmt.pct(att(A, 'spin').share)} of overs`, `${fmt.pct(att(B, 'spin').share)} of overs`],
    ];
    const other = (P) => att(P, 'unknown');
    if (other(A).share >= 0.005 || other(B).share >= 0.005) {
      rows.push(['Bowling, type unknown', other(A).runs * inn, other(B).runs * inn, 'Runs saved bowling',
        `${fmt.pct(other(A).share)} of overs`, `${fmt.pct(other(B).share)} of overs`]);
    }
    const max = Math.max(4, ...rows.map(([, a, b]) => Math.abs(a - b)));
    const card = h('section.card.card-pad.vs-won', { 'aria-labelledby': 'vs-won-title', style: { '--ca': colour('a'), '--cb': colour('b') } },
      h('h2.display.vs-h', { id: 'vs-won-title' }, 'Where it’s won'),
      h('p.small.muted', `Runs ${M().a} against ${baseline('side')}. The bar leans towards whichever side gains more there.`),
      h('div.vs-won-head', h('span', name('a')), h('span'), h('span', name('b'))));
    for (const [label, a, b, kind, subA, subB] of rows) {
      const d = a - b;
      const pct = Math.min(50, 50 * Math.abs(d) / max);
      card.append(h('div.vs-won-row', { title: kind },
        h('div.vs-won-val.a', h('strong', fmt.signed(a, 1)), subA ? h('span.tiny.muted', subA) : null),
        h('div.vs-won-mid',
          h('div.vs-won-label', label),
          h('div.vs-won-track', h(`span.vs-won-bar.${d >= 0 ? 'a' : 'b'}`, { style: { width: `${pct}%` } }))),
        h('div.vs-won-val.b', h('strong', fmt.signed(b, 1)), subB ? h('span.tiny.muted', subB) : null)));
    }
    const sum = (P) => (P.bat + P.bowl) * inn;
    card.append(h('div.vs-won-total',
      h('span', `${name('a')} ${fmt.signed(sum(A), 1)}`), h('span.muted', 'in all'), h('span', `${name('b')} ${fmt.signed(sum(B), 1)}`)));
    const short = [['a', A], ['b', B]].filter(([, P]) => P.forced > 0.02);
    if (short.length) {
      card.append(h('p.tiny.muted', short.map(([s, P]) =>
        `${name(s)} are short of bowlers: ${fmt.pct(P.forced)} of an innings goes to occasional bowlers, charged at what part-timers really concede in ${M().plural}.`).join(' ')));
    }
    return card;
  }

  function histBoard() {
    const card = h('section.card.card-pad.vs-board', h('h2.display.vs-h', 'On the record'));
    const row = (s) => {
      const m = histMeasures(s);
      return h(`div.vs-hist-side.${s}`, { style: { '--c': colour(s) } },
        h('div.vs-score-team', badge(s, 22), h('span', name(s))),
        h('dl.vs-hist-dl',
          h('div', h('dt', 'Top seven bat'), h('dd', pctAbove(m.bat))),
          h('div', h('dt', 'Main five bowl'), h('dd', pctAbove(m.bowl)))));
    };
    card.append(h('div.vs-scoreboard.hist', row('a'), h('div.vs-score-vs', 'v'), row('b')),
      h('p.small.muted', 'Percentages compare each player’s career average with the average of the decades they played in, shrunk for short careers, then average over the top seven batters and the five leading wicket-takers. Higher is better for both.'));
    return card;
  }

  const pctAbove = (x) => (x == null ? '–' : `${x >= 1 ? '+' : '−'}${fmt.n(Math.abs(x - 1) * 100)}% on era`);
  function histMeasures(s) {
    const xi = side[s].result.xi.map((x) => x.player);
    const bat = xi.slice(0, 7).map((p) => p.stats.batIndex).filter(Number.isFinite);
    const bowl = xi.filter((p) => Number.isFinite(p.stats.bowlIndex)).sort((p, q) => q.stats.wkts - p.stats.wkts).slice(0, 5).map((p) => p.stats.bowlIndex);
    const mean = (v) => (v.length ? v.reduce((p, q) => p + q, 0) / v.length : null);
    return { bat: mean(bat), bowl: mean(bowl) };
  }
  function histVerdict() {
    const A = histMeasures('a'), B = histMeasures('b');
    const better = (k) => (A[k] == null || B[k] == null ? null : A[k] >= B[k] ? 'a' : 'b');
    const bat = better('bat'), bowl = better('bowl');
    if (!bat || !bowl) return 'Career records side by side.';
    if (bat === bowl) return `${name(bat)} have the stronger batting and bowling records, era for era.`;
    return `${name(bat)} have the stronger batting record, ${name(bowl)} the stronger bowling, era for era.`;
  }

  // ------------------------------------------------------- slot by slot
  function slotBySlot() {
    const hist = isHist();
    const card = h('section.card.card-pad.vs-slots', { 'aria-labelledby': 'vs-slots-title', style: { '--ca': colour('a'), '--cb': colour('b') } },
      h('h2.display.vs-h', { id: 'vs-slots-title' }, 'Slot by slot'),
      h('p.small.muted', hist
        ? 'Batting order against batting order. Each player’s figures sit next to the average of the decades they played in. Swap anyone out.'
        : `Batting order against batting order. Runs ${M().a} each player adds batting and saves bowling, against ${baseline('player')}. Swap anyone out.`));
    const xa = side.a.result.xi, xb = side.b.result.xi;
    const pa = side.a.prof?.players, pb = side.b.prof?.players;
    const inn = match?.k.innings ?? 1;
    const vals = [];
    for (let i = 0; i < 11; i++) {
      const va = hist ? histValue(xa[i]) : (pa ? (pa[i].bat + pa[i].bowl) * inn : null);
      const vb = hist ? histValue(xb[i]) : (pb ? (pb[i].bat + pb[i].bowl) * inn : null);
      vals.push([va, vb]);
    }
    const max = Math.max(1e-6, ...vals.flat().filter(Number.isFinite).map(Math.abs));
    for (let i = 0; i < 11; i++) {
      const [va, vb] = vals[i];
      const d = Number.isFinite(va) && Number.isFinite(vb) ? va - vb : 0;
      card.append(h('div.vs-slot',
        slotPlayer('a', i, pa?.[i], inn),
        h('div.vs-slot-mid', h('span.vs-slot-num', i + 1),
          h('div.vs-slot-track', { title: hist ? 'Era-relative value' : `${fmt.signed(d, 1)} runs` },
            h(`span.vs-slot-bar.${d >= 0 ? 'a' : 'b'}`, { style: { width: `${Math.min(50, 50 * Math.abs(d) / max)}%` } }))),
        slotPlayer('b', i, pb?.[i], inn)));
    }
    return card;
  }

  function histValue(x) {
    const s = x.player.stats;
    const bat = ['batter', 'keeper', 'allrounder'].includes(x.type) && Number.isFinite(s.batIndex) ? s.batIndex - 1 : 0;
    const bowl = ['pace', 'spin', 'bowler', 'allrounder'].includes(x.type) && Number.isFinite(s.bowlIndex) ? s.bowlIndex - 1 : 0;
    return bat + bowl;
  }

  function slotPlayer(s, i, prof, inn) {
    const x = side[s].result.xi[i], p = x.player;
    const hist = st[s].mode === 'hist';
    const href = hist ? playerHref(p.rec?.id, p.rec?.title) : playerHref(p.id);
    const nameEl = href ? h('a', { href }, p.name) : h('span', p.name);
    const lines = [];
    if (hist) {
      const ps = p.stats;
      if (Number.isFinite(ps.avg)) lines.push(`bat ${fmt.avg(ps.avg)} (era ${fmt.n(ps.eraBat, 1)})`);
      if (Number.isFinite(ps.bowlAvg) && ['pace', 'spin', 'bowler', 'allrounder'].includes(x.type)) lines.push(`bowl ${fmt.avg(ps.bowlAvg)} (era ${fmt.n(ps.eraBowl, 1)})`);
    } else if (prof) {
      lines.push(`bat ${fmt.signed(prof.bat * inn, 1)}`);
      if (prof.bowlShare >= 0.005) lines.push(`bowl ${fmt.signed(prof.bowl * inn, 1)} · ${fmt.pct(prof.bowlShare)} of overs`);
    }
    const teamName = hist ? p.team : side[s].scope.teams[p.team];
    const picked = ids(st[s].lock).has(p.id);
    return h(`div.vs-slot-p.${s}`,
      h('div.vs-slot-name', nameEl, !st[s].team && teamName ? teamBadge(teamName, { size: 14 }) : null,
        picked ? h('span.badge.vs-pick', { title: 'You put this player in' }, 'your pick') : null,
        prof?.from === 'career' ? h('span.badge.vs-pred', { title: `No ${M().plural} in these years: rated on his whole ${M().label} record` }, `earlier ${M().plural}`) : null,
        prof?.from === 'prior' ? h('span.badge.vs-pred', { title: `Never played ${M().plural}: rated on what his other cricket predicts` }, 'predicted') : null),
      h('div.vs-slot-role', h('span.role-ico', icon(ROLE_ICON[x.type] || 'ball', { size: 14 })), SLOT_TYPES[x.type]?.label ?? x.type,
        h('button.vs-swap-btn', { type: 'button', 'aria-label': `Swap ${p.name} out of ${name(s)}`, onclick: () => openSwap(s, i) },
          icon('shuffle', { size: 13 }), 'Swap')),
      lines.length ? h('div.vs-slot-vals', lines.join(' · ')) : null);
  }

  // ---------------------------------------------------------------- swap
  /** Everyone who could take this place, with what the swap does to the side. */
  function swapCandidates(s, i) {
    const x = side[s], t = st[s];
    const inXI = new Set(x.result.xi.map((y) => y.player.id));
    const out = [];
    if (t.mode === 'hist') {
      const { pool } = historicPool(x.hist, { country: t.team || null, fullOnly: !!t.fo,
        weights: { quality: t.quality, legacy: t.legacy, experience: t.experience, leadership: t.leadership } });
      const now = histValue(x.result.xi[i]);
      for (const c of pool) {
        if (inXI.has(c.id)) continue;
        const role = c.pick?.any ?? [...c.roles][0];
        const v = histValue({ type: role, player: c });
        out.push({ player: c, role, delta: v - now, available: true, from: 'record',
                   line: [Number.isFinite(c.stats.avg) ? `bat ${fmt.avg(c.stats.avg)}` : null,
                          Number.isFinite(c.stats.bowlAvg) && c.stats.wkts >= 20 ? `bowl ${fmt.avg(c.stats.bowlAvg)}` : null].filter(Boolean).join(' · ') });
      }
    } else {
      const settings = { ...engineSettings(t, x.scope), evidence: 0, slots: [{ type: 'any', count: 11 }], locks: new Set() };
      const { pool } = buildPool(x.scope, settings);
      if (!match) {   // no projection for this format: rank by the selector's own utility
        const now = x.result.xi[i].u ?? 0;
        for (const c of pool) {
          if (inXI.has(c.id)) continue;
          out.push({ player: c, role: c.pick?.any ?? [...c.roles][0], delta: (c.util.any ?? 0) - now, available: c.available, from: 'record', line: '' });
        }
        return out.sort((p, q) => q.delta - p.delta);
      }
      const k = match.k, inn = k.innings;
      const now = (x.prof.bat + x.prof.bowl) * inn;
      for (const c of pool) {
        if (inXI.has(c.id)) continue;
        const role = c.pick?.any ?? [...c.roles][0] ?? 'batter';
        const xi = x.result.xi.slice();
        xi[i] = { type: role, player: c };
        const one = ratesFor(s, [xi[i]], k)[0];
        const rates = x.rates.slice(); rates[i] = one;
        const prof = sideProfile(xi, x.scope, k, rates);
        const me = prof.players[i];
        out.push({ player: c, role, delta: (prof.bat + prof.bowl) * inn - now, available: c.available, from: one.from,
                   line: [`bat ${fmt.signed(me.bat * inn, 1)}`, me.bowlShare >= 0.005 ? `bowl ${fmt.signed(me.bowl * inn, 1)}` : null].filter(Boolean).join(' · ') });
      }
    }
    return out.sort((p, q) => q.delta - p.delta);
  }

  function applySwap(s, outId, inId) {
    const lock = ids(st[s].lock), excl = ids(st[s].excl);
    lock.delete(outId); excl.add(outId); excl.delete(inId); lock.add(inId);
    set(s, { lock: [...lock].join(','), excl: [...excl].join(',') }, false);
  }

  function openSwap(s, i) {
    swapDialog?.close();
    const x = side[s].result.xi[i], p = x.player;
    const hist = st[s].mode === 'hist';
    const inn = match?.k.innings ?? 1;
    const prof = side[s].prof?.players?.[i];
    const all = swapCandidates(s, i);
    const recommended = all.find((c) => c.available) ?? all[0] ?? null;
    let showAll = false, limit = SWAP_PAGE, query = '';

    const dlg = h('dialog.vs-dialog', { 'aria-labelledby': 'vs-dlg-title', style: { '--c': colour(s) } });
    swapDialog = dlg;
    const close = () => dlg.close();
    const card = (who, role, line, extra) => h('div.vs-swap-card',
      h('span.avatar', { 'aria-hidden': 'true' }, initials(who.name)),
      h('div.vs-swap-who', h('strong', who.name),
        h('span.tiny.muted', [SLOT_TYPES[role]?.label ?? role, teamOf(s, who)].filter(Boolean).join(' · ')),
        line ? h('span.tiny', line) : null),
      extra);
    const nowLine = hist ? [Number.isFinite(p.stats.avg) ? `bat ${fmt.avg(p.stats.avg)}` : null].filter(Boolean).join('')
      : prof ? [`bat ${fmt.signed(prof.bat * inn, 1)}`, prof.bowlShare >= 0.005 ? `bowl ${fmt.signed(prof.bowl * inn, 1)}` : null].filter(Boolean).join(' · ') : '';
    const deltaText = (d) => (hist ? `${fmt.signed(d * 100, 0)} on era` : `${fmt.signed(d, 1)} runs ${M().a}`);
    const swapBtn = (c) => h('button.btn.sm.primary', { type: 'button', onclick: () => { close(); applySwap(s, p.id, c.player.id); } }, 'Swap in');

    const list = h('ul.vs-swap-list', { 'aria-label': 'Players who could take this place' });
    const count = h('p.tiny.muted.vs-swap-count');
    const search = h('input.input', { type: 'search', placeholder: 'Search players or teams', 'aria-label': 'Search players or teams',
      oninput: (e) => { query = e.target.value.trim().toLowerCase(); limit = SWAP_PAGE; draw(); } });
    const everyone = h('label.vs-swap-toggle.small', h('input', { type: 'checkbox', onchange: (e) => { showAll = e.target.checked; limit = SWAP_PAGE; draw(); } }),
      ' Include players not available to this side');

    function draw() {
      clear(list);
      const shown = all.filter((c) => (showAll || c.available)
        && (!query || c.player.name.toLowerCase().includes(query) || (teamOf(s, c.player) || '').toLowerCase().includes(query)));
      for (const c of shown.slice(0, limit)) {
        list.append(h('li', h('button.vs-swap-row', { type: 'button', onclick: () => { close(); applySwap(s, p.id, c.player.id); } },
          h('span.vs-swap-row-name', c.player.name,
            !c.available ? h('span.badge', { title: 'Not available under this side’s settings' }, 'unavailable') : null,
            c.from === 'prior' ? h('span.badge.vs-pred', 'predicted') : c.from === 'career' ? h('span.badge.vs-pred', `earlier ${M().plural}`) : null),
          h('span.tiny.muted.vs-swap-row-meta', [SLOT_TYPES[c.role]?.label ?? c.role, teamOf(s, c.player), c.line].filter(Boolean).join(' · ')),
          h(`span.vs-delta${c.delta >= 0 ? '.up' : '.down'}`, deltaText(c.delta)))));
      }
      if (shown.length > limit) {
        list.append(h('li', h('button.btn.sm.ghost.vs-swap-more', { type: 'button', onclick: () => { limit += SWAP_PAGE; draw(); } },
          `Show ${Math.min(SWAP_PAGE, shown.length - limit)} more of ${fmt.n(shown.length - limit)}`)));
      }
      count.textContent = shown.length ? `${fmt.n(shown.length)} players, best change first` : 'No players match.';
    }

    dlg.append(
      h('header.vs-dlg-head',
        h('h2.display', { id: 'vs-dlg-title' }, `Swap ${p.name}`),
        h('button.icon-btn', { type: 'button', 'aria-label': 'Close', onclick: close }, h('span', { 'aria-hidden': 'true' }, '×'))),
      h('div.vs-swap-pair',
        card(p, x.type, nowLine, h('span.tiny.faint', 'In the side now')),
        h('div.vs-swap-arrow', { 'aria-hidden': 'true' }, icon('arrow', { size: 22 })),
        recommended
          ? card(recommended.player, recommended.role, recommended.line,
            h('div.vs-swap-rec', h('span.tiny.faint', 'Recommended'), h(`span.vs-delta${recommended.delta >= 0 ? '.up' : '.down'}`, deltaText(recommended.delta)), swapBtn(recommended)))
          : h('div.vs-swap-card.muted', 'No one else qualifies under these settings.')),
      h('div.vs-swap-tools', search, everyone),
      count, list,
      h('p.tiny.muted.vs-swap-note', (st[s].comp || '') === ''
        ? 'The Best XI shape stays in force, so the rest of the side may be rebalanced around your pick. Set the shape to Free to change only this place.'
        : 'Only this place changes. The figure beside each player is what the swap does to the side’s projected runs.'));
    dlg.addEventListener('close', () => { dlg.remove(); if (swapDialog === dlg) swapDialog = null; });
    dlg.addEventListener('click', (e) => { if (e.target === dlg) close(); });
    document.body.append(dlg);
    draw();
    dlg.showModal();
    search.focus();
  }

  function teamOf(s, player) {
    if (st[s].mode === 'hist') return player.team || '';
    return side[s].scope.teams[player.team] ?? '';
  }

  // ----------------------------------------------------- tale of the tape
  /**
   * What each player brings to the tape: his record in the match format (in his
   * side's years, else his whole record there), so both elevens are measured in
   * the same cricket. A side picked from the match format keeps its own figures.
   */
  function playerFacts(s) {
    const x = side[s], P0 = x.scope.players;
    if (comparable(x.scope, matchScope)) {
      return x.result.xi.map((y) => ({ stats: y.player.stats, caps: y.player.sc.expMatches, capt: y.player.sc.captMatches,
        dob: P0.dob?.[y.player.pi], hand: P0.hand?.[y.player.pi], has: true }));
    }
    const ctx = matchCtx(s), P = matchScope.players;
    return x.result.xi.map((y) => {
      // Batting and bowling each from their own record, as in the projection.
      const { pi, bat, bowl } = matchRecord(y.player.id, ctx);
      const bs = bat.rec ? statsOf(bat.rec) : null, ws = bowl.rec ? statsOf(bowl.rec) : null;
      const stats = bs || ws ? { ...(bs || {}), wkts: ws?.wkts ?? 0, econ: ws?.econ ?? null,
        ballsPerMatchBowled: ws?.ballsPerMatchBowled ?? 0, fiveW: ws?.fiveW ?? 0, matches: ws?.matches ?? bs?.matches ?? 0,
        catches: (bs ?? ws).catches, stumpings: (bs ?? ws).stumpings } : null;
      const career = pi != null ? ctx.career.get(pi) : null;
      return { stats, caps: (career?.raw.m || 0) + (pi != null ? P.pre?.[pi] || 0 : 0),
        capt: pi != null ? P.capt?.[pi] || 0 : 0, dob: P0.dob?.[y.player.pi], hand: P0.hand?.[y.player.pi], has: !!stats };
    });
  }

  function tape() {
    const hist = isHist();
    const rows = hist ? histTape() : bbbTape();
    const missing = hist ? 0 : SIDES.reduce((a, s) => a + playerFacts(s).filter((f) => !f.has).length, 0);
    const card = h('section.card.card-pad.vs-tape', { 'aria-labelledby': 'vs-tape-title', style: { '--ca': colour('a'), '--cb': colour('b') } },
      h('h2.display.vs-h', { id: 'vs-tape-title' }, 'Tale of the tape'),
      h('p.small.muted', hist ? 'Career totals of each eleven.'
        : SIDES.every((s) => comparable(side[s].scope, matchScope)) ? 'Each eleven’s record over its own years, from Cricsheet’s ball-by-ball data.'
          : `Both elevens in ${M().plural}: each player’s ${M().label} batting and bowling over his side’s years, or his whole ${M().label} record up to then where he did none in those years.`
          + (missing ? ` ${missing} ${missing === 1 ? 'player has' : 'players have'} never played ${M().plural} and ${missing === 1 ? 'adds' : 'add'} nothing here.` : '')));
    const table = h('table.data.vs-tape-table', h('caption.sr-only', `${name('a')} and ${name('b')} compared`),
      h('thead', h('tr', h('th.r', { scope: 'col' }, name('a')), h('th', { scope: 'col' }, h('span.sr-only', 'Measure')), h('th', { scope: 'col' }, name('b')))));
    const body = h('tbody');
    for (const r of rows) {
      const [label, a, b, better, f, hint] = r;
      const win = better === 0 || a == null || b == null || a === b ? null : (better > 0 ? a > b : a < b) ? 'a' : 'b';
      body.append(h('tr',
        h(`td.r.vs-tape-v${win === 'a' ? '.win' : ''}`, f(a)),
        h('th.vs-tape-label', { scope: 'row', title: hint || null }, label),
        h(`td.vs-tape-v${win === 'b' ? '.win' : ''}`, f(b))));
    }
    table.append(body);
    card.append(h('div.table-wrap', table));
    return card;
  }

  function bbbTape() {
    const m = (s) => {
      const facts = playerFacts(s), top = facts.slice(0, 7);
      const sum = (fs, f) => fs.reduce((a, q) => a + (q.stats && Number.isFinite(f(q.stats)) ? f(q.stats) : 0), 0);
      const runs = sum(top, (q) => q.runs), outs = sum(top, (q) => (q.avg ? q.runs / q.avg : 0));
      const balls = sum(top, (q) => (q.sr ? 100 * q.runs / q.sr : 0));
      const bowlers = facts.filter((q, i) => (side[s].prof?.players[i]?.bowlShare ?? 0) > 0);
      const wk = sum(bowlers, (q) => q.wkts), bb = sum(bowlers, (q) => (q.ballsPerMatchBowled || 0) * q.matches);
      const conc = sum(bowlers, (q) => (q.econ ? q.econ * (q.ballsPerMatchBowled || 0) * q.matches / 6 : 0));
      const end = new Date(Date.UTC(st[s].to, 6, 1));
      const ages = facts.map((q) => q.dob).filter(Boolean).map((d) => (end - new Date(d)) / (365.25 * 864e5)).filter((x) => x > 10 && x < 60);
      return {
        caps: facts.reduce((a, q) => a + (q.caps || 0), 0), capt: facts.reduce((a, q) => a + (q.capt || 0), 0),
        age: ages.length ? ages.reduce((p, q) => p + q, 0) / ages.length : null,
        avg: outs > 0 ? runs / outs : null, sr: balls > 0 ? 100 * runs / balls : null,
        h100: sum(facts, (q) => q.hundreds), h50: sum(facts, (q) => q.fifties),
        bavg: wk > 0 ? conc / wk : null, econ: bb > 0 ? 6 * conc / bb : null, w5: sum(facts, (q) => q.fiveW),
        ct: sum(facts, (q) => q.catches), stp: sum(facts, (q) => q.stumpings),
        left: top.filter((q) => q.hand === 'left').length,
      };
    };
    const A = m('a'), B = m('b'), n = (d) => (x) => fmt.n(x, d);
    const unit = st.m === 'league' ? 'League' : M().label;
    return [
      [`${unit} caps between them`, A.caps, B.caps, 1, n(0), `${unit} matches each player has played, including any before ball-by-ball coverage`],
      [`${unit} matches as captain`, A.capt, B.capt, 1, n(0)],
      ['Average age', A.age, B.age, 0, n(1), 'At the middle of each side’s last year'],
      ['Top-seven batting average', A.avg, B.avg, 1, fmt.avg],
      ['Top-seven runs per 100 balls', A.sr, B.sr, 1, fmt.sr],
      ['Hundreds', A.h100, B.h100, 1, n(0)],
      ['Fifties', A.h50, B.h50, 1, n(0)],
      ['Bowling average', A.bavg, B.bavg, -1, fmt.avg, 'Of the bowlers who bowl in the projection'],
      ['Economy', A.econ, B.econ, -1, (x) => (x == null ? '–' : x.toFixed(2))],
      ['Five-wicket hauls', A.w5, B.w5, 1, n(0)],
      ['Catches', A.ct, B.ct, 1, n(0), 'Including catches as keeper'],
      ['Stumpings', A.stp, B.stp, 1, n(0)],
      ['Left-handers in the top seven', A.left, B.left, 0, n(0)],
    ];
  }

  function histTape() {
    const m = (s) => {
      const xi = side[s].result.xi.map((x) => x.player), top = xi.slice(0, 7);
      const sum = (ps, f) => ps.reduce((a, p) => a + (Number.isFinite(f(p)) ? f(p) : 0), 0);
      const runs = sum(top, (p) => p.rec.runs), outs = sum(top, (p) => p.rec.outs);
      const bowlers = xi.filter((p) => p.rec.wkts > 0).sort((p, q) => q.rec.wkts - p.rec.wkts).slice(0, 5);
      const wk = sum(bowlers, (p) => p.rec.wkts), rc = sum(bowlers, (p) => p.rec.rc);
      return {
        caps: sum(xi, (p) => p.rec.m), capt: sum(xi, (p) => p.rec.capt), runs: sum(xi, (p) => p.rec.runs),
        avg: outs > 0 ? runs / outs : null, h100: sum(xi, (p) => p.rec.h100), wkts: sum(xi, (p) => p.rec.wkts),
        bavg: wk > 0 ? rc / wk : null, ct: sum(xi, (p) => p.rec.ct), st: sum(xi, (p) => p.rec.st),
        left: top.filter((p) => p.rec.hand === 'left').length,
      };
    };
    const A = m('a'), B = m('b'), n = (x) => fmt.n(x);
    return [
      ['Caps between them', A.caps, B.caps, 1, n],
      ['Matches as captain', A.capt, B.capt, 1, n],
      ['Career runs', A.runs, B.runs, 1, n],
      ['Top-seven batting average', A.avg, B.avg, 1, fmt.avg, 'Raw career averages; eras differ'],
      ['Hundreds', A.h100, B.h100, 1, n],
      ['Career wickets', A.wkts, B.wkts, 1, n],
      ['Bowling average, main five', A.bavg, B.bavg, -1, fmt.avg, 'Raw career averages; eras differ'],
      ['Catches', A.ct, B.ct, 1, n],
      ['Stumpings', A.st, B.st, 1, n],
      ['Left-handers in the top seven', A.left, B.left, 0, n],
    ];
  }

  function sharedPlayers() {
    const list = (s) => side[s].result.xi.map((x) => x.player.id);
    const both = list('a').filter((id) => list('b').includes(id));
    if (!both.length) return null;
    const names = side.a.result.xi.filter((x) => both.includes(x.player.id)).map((x) => x.player.name);
    return h('p.small.muted.vs-shared', icon('info', { size: 15 }),
      ` ${names.join(', ')} ${names.length === 1 ? 'is' : 'are'} in both elevens.`);
  }

  function notes() {
    return h('section.panel.vs-notes', h('div.eyebrow', 'Reading this'),
      h('ul.small',
        isHist()
          ? [h('li', 'Each eleven is picked by the same exact solver as the Best XI page, in the shape you choose.'),
            h('li', 'Career records cannot say who would win: there is no ball-by-ball evidence before the 2000s, so this page compares records rather than projecting a match.')]
          : [h('li', 'Each eleven is picked by the same exact solver as the Best XI page, in the shape you choose; swaps lock a player in and another out, exactly as on that page.'),
            h('li', 'Batting value is spread over a typical innings by batting position. The best bowlers take the most overs, each within the format’s limit and near his usual workload; overs a side cannot cover go to part-timers at the rate occasional bowlers really concede.'),
            h('li', 'Short records are pulled towards what a player’s other cricket predicts, using transitions measured on players who played both. Those predictions beat an average-player assumption on debutants the fit never saw (see Method & data).'),
            h('li', 'The projection knows nothing about pitch, weather, toss, venue or form beyond each side’s years. Treat it as a well-informed argument, not a forecast.'),
            h('li', h('a', { href: '#/method' }, 'Method & data'), ' explains the ratings and the checks behind them.')]));
  }

  function renderAll() {
    renderHero();
    renderArena();
    renderSides();
    renderResults();
  }

  await load();
  if (!isLive(route)) return { destroy() { dead = true; } };
  compute();
  setQuery({ a: queryString(st.a), b: queryString(st.b), m: st.m }, route);
  renderAll();

  return {
    destroy() { dead = true; swapDialog?.close(); swapDialog?.remove(); swapDialog = null; },
    update(r) {
      if (r.query.get('a') == null) return;
      const next = { a: stateOf(r.query.get('a')), b: stateOf(r.query.get('b')), m: r.query.get('m') || st.m };
      if (queryString(next.a) === queryString(st.a) && queryString(next.b) === queryString(st.b) && next.m === st.m) return;
      Object.assign(st, next);
      commit();
    },
  };
}
