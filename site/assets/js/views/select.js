// Selection room: choose a scope and priorities, get the exact Best XI.
import { h, clear, fmt, initials, tooltip, debounce, drawer } from '../ui/dom.js';
import * as data from '../data.js';
import { setQuery, isLive } from '../app.js';
import { rememberTitle, saved as savedPage } from '../memory.js';
import { whyNot, stability, PRESETS, SLOT_TYPES } from '../engine/select.js';
import { defaults, fromQuery, toQuery, parseSlots, slotsStr, selectableTeams, resolve, engineSettings,
  selectFor, xiTitle, windowText, queryString, compositionText, COMPOSITIONS } from '../xistate.js';
import { FAMILY_RULES } from '../engine/metrics.js';
import { icon, ROLE_ICON } from '../ui/icons.js';
import { teamLabel } from '../ui/teams.js';
import { playerHref } from '../ui/links.js';

const COMPONENTS = [
  { key: 'quality', label: 'Quality', hint: 'Opposition- and era-adjusted output per ball (per innings for Test batting), shrunk for small samples', colour: 'var(--pitch)' },
  { key: 'legacy', label: 'Legacy', hint: 'Total adjusted value over the window: long careers of sustained output score highest', colour: 'var(--sky)' },
  { key: 'experience', label: 'Experience', hint: 'Matches played in this format up to the end of the window', colour: 'var(--gold)' },
  { key: 'leadership', label: 'Leadership', hint: 'Matches formally captained in this format (Wikipedia captaincy records), plus current vice-captaincy', colour: 'var(--ball)' },
];
const SLOT_ORDER = ['opener', 'batter', 'finisher', 'keeper', 'allrounder', 'pace', 'spin', 'bowler'];
const SLOT_COLOUR = { opener: 'var(--pitch)', batter: 'var(--pitch-2)', finisher: 'var(--sky)', keeper: 'var(--sky)',
                      allrounder: 'var(--gold)', pace: 'var(--ball)', spin: '#8a5cc2', bowler: 'var(--ball)' };

// -------------------------------------------------------------------- view
export async function mount(root, route) {
  const meta = await data.meta();
  const page = h('div.page.select-page');
  root.append(page);
  let st = defaults(fromQuery(route.query));
  let dead = false;
  let scope = null, hist = null, result = null, stab = null, stabToken = 0;

  const hero = h('header.select-hero');
  const rail = h('aside.rail', { 'aria-label': 'Selection settings' });
  const board = h('section.board', { 'aria-live': 'polite' });
  page.append(hero, h('div.select-layout', rail, board));

  const leagues = meta.scopes.filter((s) => s.tier === 'league');

  async function ensureData() {
    ({ scope, hist } = await resolve(st, meta));
  }

  const settings = () => engineSettings(st, scope);

  function compute() {
    result = selectFor(st, { scope, hist });
    stab = null;
    if (st.mode === 'hist') return;
    const token = ++stabToken;
    if (!result.error) {
      const run = () => { if (token === stabToken) { stab = stability(scope, settings(), 20); renderBoard(); } };
      (window.requestIdleCallback || ((f) => setTimeout(f, 60)))(run);
    }
  }

  const commit = debounce(async (recomputeOnly = false) => {
    if (dead) return;
    setQuery(toQuery(st), route);
    if (!recomputeOnly) await ensureData();
    if (dead) return;
    compute();
    renderAll();
  }, 60);

  function set(patch, opts = {}) {
    Object.assign(st, patch);
    if (opts.lensCustom) st.lens = 'custom';
    commit(opts.recomputeOnly);
  }

  /** XI vs XI with this XI as side A; a saved side B stays when there is one. */
  function versusHref() {
    const prev = savedPage('versus');
    const q = new URLSearchParams(prev ? prev.href.split('?')[1] || '' : '');
    q.set('a', queryString(st));
    return `#/versus?${q}`;
  }

  // ---------------------------------------------------------------- hero
  function renderHero() {
    clear(hero);
    const title = xiTitle(st, { scope, hist });
    const sub = st.mode === 'hist'
      ? `Career records across all eras, ${hist.years[0]}–${hist.years[1]}`
      : `${scope.label}, ${windowText(st)} · ${PRESETS[st.lens]?.label ?? 'Custom'} lens`;
    rememberTitle('select', title);
    hero.append(
      h('div.hero-text', h('div.eyebrow', 'Best XI'), h('h1.display', title), h('p.lede', sub)),
      result && !result.error ? h('a.btn.hero-cta', { href: versusHref() }, icon('compare', { size: 16 }), 'Take this XI to XI vs XI') : null,
    );
  }

  // ---------------------------------------------------------------- rail
  function seg(options, value, onPick, labelText) {
    return h('div.seg.block', { role: 'group', 'aria-label': labelText },
      options.map(([v, label, disabled]) => h('button', {
        type: 'button', 'aria-pressed': String(value === v), disabled: !!disabled,
        onclick: () => onPick(v),
      }, label)));
  }

  function section(title, ...children) {
    return h('div.rail-section', h('div.rail-title', title), ...children);
  }

  function slider(key, label, hint, min, max, step = 1, suffix = '') {
    const out = h('output', { for: `s-${key}` }, `${st[key]}${suffix}`);
    const input = h('input', { type: 'range', id: `s-${key}`, min, max, step, value: st[key],
      oninput: (e) => { out.textContent = `${e.target.value}${suffix}`; set({ [key]: Number(e.target.value) }, { lensCustom: ['quality', 'legacy', 'experience', 'leadership', 'hl'].includes(key), recomputeOnly: true }); } });
    return h('div.slider-row', h('label', { for: `s-${key}` }, label), out, input, hint ? h('div.hint', hint) : null);
  }

  function renderRail() {
    clear(rail);
    const isHist = st.mode === 'hist';
    rail.append(section('Evidence',
      seg([['bbb', ['Ball by ball ', h('span.nowrap', '2002–26')]], ['hist', 'All eras']], st.mode,
        (v) => set({ mode: v, team: '', lock: '', excl: '', ...(v === 'hist' ? { ...PRESETS.legacy.weights, lens: 'legacy' } : {}) }), 'Evidence base'),
      h('p.tiny.faint', isHist
        ? 'All eras uses career totals from Wikipedia’s national player lists (Tests from 1877, ODIs from 1971), adjusted to each decade’s average.'
        : 'Every delivery in Cricsheet, valued by run expectancy and adjusted for opposition, era, phase and venue.')));

    const compRows = [
      seg([['national', 'International'], ['league', 'Leagues', isHist]], st.tier, (v) => set({ tier: v, team: '', from: null, to: null, lock: '', excl: '' }), 'Competition'),
      seg([['male', 'Men'], ['female', 'Women']], st.g, (v) => {
        const lg = v === 'female' ? (leagues.find((l) => l.gender === 'female' && l.featured)?.key ?? 'wbbl') : 'ipl';
        set({ g: v, team: '', lg: st.tier === 'league' ? lg : st.lg, from: null, to: null, lock: '', excl: '' });
      }, 'Gender'),
    ];
    if (st.tier === 'national') {
      compRows.push(seg([['Test', 'Test'], ['ODI', 'ODI'], ['T20I', 'T20I', isHist]], st.f, (v) => set(isHist ? { f: v, lock: '', excl: '' } : { f: v, slots: '' }), 'Format'));
    } else {
      const opts = leagues.filter((l) => l.gender === st.g).sort((a, b) => (b.featured - a.featured) || b.matches - a.matches);
      compRows.push(h('div.field', h('label', { for: 'lg' }, 'League'),
        h('select.select', { id: 'lg', onchange: (e) => set({ lg: e.target.value, team: '', from: null, to: null, mos: null, lock: '', excl: '' }) },
          opts.map((l) => h('option', { value: l.key, selected: l.key === st.lg }, `${l.label}${l.featured ? '' : ' ·'}`)))));
    }
    const teams = isHist ? hist.countries : scope.teams;
    const teamLabel = st.tier === 'league' ? 'Franchise' : 'Team';
    const worldLabel = st.tier === 'league' ? 'All franchises' : 'World XI';
    const teamList = selectableTeams([...teams], st.tier);
    compRows.push(h('div.field', h('label', { for: 'team' }, teamLabel),
      h('select.select', { id: 'team', onchange: (e) => set({ team: e.target.value, lock: '', excl: '' }) },
        h('option', { value: '' }, worldLabel), teamList.map((t) => h('option', { value: t, selected: t === st.team }, t)))));
    rail.append(section('Scope', ...compRows));

    if (!isHist) {
      const [y0, y1] = scope.years;
      // A preset that reaches back past the first season is the same as All, so it is not shown twice.
      const presets = [['2', 'Last 2 yrs', y1 - 1], ['4', 'Last 4', y1 - 3], ['10', 'Last 10', y1 - 9], ['all', 'All', y0]]
        .filter(([k, , from]) => k === 'all' || from > y0);
      rail.append(section('Window',
        h('div.chips', presets.map(([k, label, from]) => h('button.chip', { type: 'button',
          'aria-pressed': String(st.to === y1 && st.from === Math.max(y0, from)),
          onclick: () => set({ from: Math.max(y0, from), to: y1, ...(k === 'all' && st.lens !== 'custom' ? { ...PRESETS.alltime.weights, hl: 0, lens: 'alltime' } : {}) }) }, label))),
        h('div.year-range',
          h('div.field', h('label', { for: 'from' }, 'From'), h('select.select', { id: 'from', onchange: (e) => set({ from: +e.target.value }) },
            range(y0, st.to).map((y) => h('option', { value: y, selected: y === st.from }, y)))),
          h('div.field', h('label', { for: 'to' }, 'To'), h('select.select', { id: 'to', onchange: (e) => set({ to: +e.target.value }) },
            range(st.from, y1).map((y) => h('option', { value: y, selected: y === st.to }, y))))),
        slider('hl', 'Recency half-life', st.hl ? `A season ${st.hl} year${st.hl > 1 ? 's' : ''} before the window end counts half` : 'Off: every season in the window counts equally', 0, 8, 1, st.hl ? ' yrs' : ''),
      ));
      const squadOk = scope.availability.squads;
      rail.append(section('Availability',
        seg([['squad', 'Current squad', !squadOk], ['active', 'Active'], ['any', 'Everyone']], st.av, (v) => set({ av: v }), 'Availability'),
        h('p.tiny.faint', st.av === 'squad' ? 'Players named in the current squad on Wikipedia for this format.'
          : st.av === 'active' ? `In a current squad, or played this format in the last ${scope.tier === 'league' || scope.format === 'Test' ? 24 : 18} months, and not reported retired from it.`
            : 'Anyone with enough evidence in the window, retired or not.')));
    }

    const lensChips = Object.entries(PRESETS).map(([k, p]) => h('button.chip', { type: 'button', 'aria-pressed': String(st.lens === k),
      onclick: () => set({ lens: k, ...p.weights, hl: isHist ? st.hl : p.halfLife }) }, p.label));
    rail.append(section('Priorities',
      h('div.chips', lensChips),
      ...COMPONENTS.map((c) => slider(c.key, c.label, c.hint, 0, 100, 5)),
      !isHist && !scope.availability.leadership ? h('p.tiny.faint', 'No captaincy records for this competition; the leadership weight has no effect here.') : null));

    // Shape: the Best XI's own composition, or a free one shared with XI vs XI.
    const shapeSeg = h('div.field', h('label', { for: 'comp' }, 'Shape'),
      h('select.select', { id: 'comp', onchange: (e) => set({ comp: e.target.value }, { recomputeOnly: true }) },
        Object.entries(COMPOSITIONS).map(([k, c]) => h('option', { value: k, selected: k === (st.comp || '') }, c.label))));
    if (st.comp) {
      rail.append(section('Composition', shapeSeg, h('p.tiny.faint', COMPOSITIONS[st.comp]?.note ?? '')));
    } else if (isHist) {
      rail.append(section('Composition', shapeSeg));
    }
    if (!isHist && !st.comp) {
      const slots = parseSlots(st.slots, scope.family);
      const types = scope.family === 'multi' ? ['opener', 'batter', 'keeper', 'allrounder', 'pace', 'spin', 'bowler']
        : ['opener', 'batter', 'finisher', 'keeper', 'allrounder', 'pace', 'spin', 'bowler'];
      const count = (t) => slots.find((s) => s.type === t)?.count ?? 0;
      const total = slots.reduce((a, s) => a + s.count, 0);
      const change = (t, d) => {
        const next = types.map((x) => ({ type: x, count: x === t ? Math.max(0, count(x) + d) : count(x) }));
        set({ slots: slotsStr(next) }, { recomputeOnly: true });
      };
      rail.append(section(`Composition · ${total}/11`, shapeSeg,
        h('div', types.map((t) => h('div.stepper',
          h('span.small.step-label', h('span.role-ico', { style: { color: SLOT_COLOUR[t] } }, icon(ROLE_ICON[t], { size: 17 })), SLOT_TYPES[t].label),
          h('span.ctrl',
            h('button', { type: 'button', 'aria-label': `Fewer ${SLOT_TYPES[t].label}`, disabled: count(t) === 0, onclick: () => change(t, -1) }, '−'),
            h('span', { 'aria-live': 'polite' }, count(t)),
            h('button', { type: 'button', 'aria-label': `More ${SLOT_TYPES[t].label}`, disabled: total >= 11, onclick: () => change(t, +1) }, '+'))))),
        total !== 11 ? h('p.tiny', { style: { color: 'var(--weakness)' } }, `Slots add up to ${total}; an XI needs 11.`) : null,
        h('button.btn.sm.ghost', { type: 'button', onclick: () => set({ slots: '' }, { recomputeOnly: true }) }, 'Reset composition')));
    }

    const cons = [];
    if (!st.team && st.tier === 'national') {
      cons.push(h('label.toggle', h('input', { type: 'checkbox', checked: !!st.fo, onchange: (e) => set({ fo: e.target.checked ? 1 : 0 }) }),
        'Full-Member cricket only'));
      cons.push(h('div.field', h('label', { for: 'mpt' }, 'Most players from one country'),
        h('select.select', { id: 'mpt', onchange: (e) => set({ mpt: +e.target.value }, { recomputeOnly: true }) },
          [0, 2, 3, 4, 5, 6].map((n) => h('option', { value: n, selected: (st.mpt || 0) === n }, n === 0 ? 'No limit' : n)))));
    }
    if (!isHist && st.tier === 'league' && !st.team) {
      cons.push(h('div.field', h('label', { for: 'mos' }, 'Most overseas players'),
        h('select.select', { id: 'mos', onchange: (e) => set({ mos: e.target.value === '' ? null : +e.target.value }, { recomputeOnly: true }) },
          h('option', { value: '' }, 'No limit'),
          [2, 3, 4, 5, 6].map((n) => h('option', { value: n, selected: st.mos === n }, n)))),
        h('p.tiny.faint', scope.maxOverseas ? `League rule: ${scope.maxOverseas} in the XI. ${scope.overseasNote || ''} ` : '',
          scope.overseasSource ? h('a', { href: scope.overseasSource, rel: 'noopener' }, 'Source') : null,
          scope.maxOverseas ? '. ' : '',
          'Overseas means the player’s national side (from international appearances or Wikipedia) differs from the host country.'));
    }
    if (!isHist) {
      cons.push(slider('ev', 'Evidence bar', 'Multiplies the minimum balls needed for each role', 0.5, 2, 0.25, '×'));
    }
    if (cons.length) rail.append(section('Constraints', ...cons));
    const locks = st.lock ? st.lock.split(',') : [], excl = st.excl ? st.excl.split(',') : [];
    if (locks.length || excl.length) {
      rail.append(section('Locked and excluded',
        h('p.tiny.muted', `${locks.length} locked, ${excl.length} excluded`),
        h('button.btn.sm', { type: 'button', onclick: () => set({ lock: '', excl: '' }, { recomputeOnly: true }) }, 'Clear all')));
    }
    rail.append(h('div.rail-foot', h('button.btn.sm.ghost', { type: 'button', onclick: () => { st = defaults({ mode: st.mode, tier: st.tier, g: st.g, f: st.f, lg: st.lg }); commit(); } }, 'Reset everything'),
      h('button.btn.sm', { type: 'button', onclick: copyLink }, icon('link', { size: 15 }), 'Copy link to this XI')));
  }

  async function copyLink() {
    try { await navigator.clipboard.writeText(location.href); toast('Link copied'); } catch (e) { toast('Copy the address bar to share this XI'); }
  }

  // ---------------------------------------------------------------- board
  function renderBoard() {
    clear(board);
    if (!result) return;
    const notes = [];
    if (st.mode === 'bbb') {
      if (scope.tier === 'national' && scope.gender === 'male') notes.push('Cricsheet withholds matches involving Afghanistan’s men, so those games and players are absent.');
      if (result.relaxed) notes.push(`Not enough players met the evidence bar for every slot, so it was lowered to ${Math.round(result.relaxed * 100)}%.`);
      if (scope.tier === 'league' && !scope.featured) notes.push('A secondary league: squads and captaincy records are not tracked for it.');
    } else {
      notes.push('Career totals come from Wikipedia’s national player lists; batting positions are not recorded there, so openers are not separated from other top-order batters.');
    }
    if (result.error) {
      board.append(h('div.notice.error', h('div', h('strong', 'No eleven fits these settings. '), result.error,
        result.shortfall ? h('ul.small', result.shortfall.filter((s) => s.have < s.need).map((s) => h('li', `${SLOT_TYPES[s.type].label}: need ${s.need}, ${s.have} eligible`))) : null,
        h('p.small', 'Try a longer window, a lower evidence bar, “Everyone” availability, or fewer slots of the scarce type.'))));
      renderCandidates(board, result.pool || []);
      return;
    }
    if (result.relaxed) {
      board.append(h('div.callout.caution', h('span.badge-ico', icon('warn', { size: 24 })),
        h('div', h('div.k', 'Small sample caution'), h('div.t', 'Use with caution'),
          h('p', `Not enough players met the evidence bar for every slot, so it was lowered to ${Math.round(result.relaxed * 100)}%. Some picks rest on thin records.`))));
    }
    if (result.reshaped) {
      board.append(h('div.callout', h('span.badge-ico', icon('shuffle', { size: 22 })),
        h('div', h('div.k', 'Composition'), h('div.t', 'Shaped to fit the players available'),
          h('p', `No eleven of the usual shape could be filled from these players, so this one plays ${compositionText(result.reshaped)}. Set your own composition below to change it.`))));
    }
    const plain = notes.filter((n) => !n.startsWith('Not enough players'));
    if (plain.length) board.append(h('div.notes', plain.map((n) => h('p.tiny.muted', n))));

    const summary = summarise(result);
    board.append(h('div.board-head',
      h('div', h('div.rule-title.left', 'The eleven'), h('div.small.muted', { style: { marginTop: '8px' } }, summary)),
      st.mode === 'bbb' ? h('div.legend', COMPONENTS.map((c) => h('span.legend-item', h('span.swatch', { style: { background: c.colour } }), c.label))) : null));

    const list = h('ol.xi', { 'aria-label': 'Selected eleven in batting order' });
    result.xi.forEach((x, i) => list.append(playerRow(x, i)));
    board.append(list);

    if (st.mode === 'bbb') {
      board.append(h('div.grid-2.mt', benchCard(), whyNotCard()));
    }
    renderCandidates(board, result.pool);
  }

  function summarise(res) {
    const xi = res.xi;
    const bat = xi.filter((x) => ['opener', 'batter', 'finisher', 'keeper', 'allrounder'].includes(x.type)).length;
    const bowl = xi.filter((x) => ['allrounder', 'pace', 'spin', 'bowler'].includes(x.type)).length;
    const pace = xi.filter((x) => x.type === 'pace').length, spin = xi.filter((x) => x.type === 'spin').length;
    const teams = new Set(xi.map((x) => x.player.team));
    return `${bat} batting options · ${bowl} bowling options (${pace} pace, ${spin} spin) · ${teams.size} ${st.tier === 'league' ? 'franchise' : 'team'}${teams.size > 1 ? 's' : ''}`;
  }

  function teamName(p) {
    if (st.mode === 'hist') return p.team;
    return scope.teams[p.team] ?? '';
  }

  function statLine(x) {
    const s = x.player.stats;
    const isBowl = ['pace', 'spin', 'bowler'].includes(x.type);
    const isAR = x.type === 'allrounder';
    const bat = s.runs ? (st.mode === 'hist'
      ? `${fmt.n(s.runs)} runs · avg ${fmt.avg(s.avg)}`
      : scope.family === 'multi' ? `${fmt.n(s.runs)} runs · avg ${fmt.avg(s.avg)} · ${s.hundreds}×100`
        : `${fmt.n(s.runs)} runs · avg ${fmt.avg(s.avg)} · SR ${fmt.sr(s.sr)}`) : '';
    const bowl = s.wkts ? (st.mode === 'hist' ? `${s.wkts} wkts · avg ${fmt.avg(s.bowlAvg)}`
      : `${s.wkts} wkts · avg ${fmt.avg(s.bowlAvg)} · econ ${s.econ?.toFixed(2)}`) : '';
    if (isAR) return [bat, bowl].filter(Boolean).join('  |  ');
    if (isBowl) return bowl || bat;
    return bat || bowl;
  }

  function playerRow(x, i) {
    const p = x.player;
    const tname = teamName(p);
    const isC = p.id === result.captain, isK = p.id === result.keeper;
    const locked = (st.lock || '').split(',').includes(p.id);
    const parts = x.parts || null;
    const bar = h('div.contrib', { 'aria-hidden': 'true' });
    if (st.mode === 'bbb' && parts) {
      for (const c of COMPONENTS) {
        const v = parts[c.key] || 0;
        if (v > 0) bar.append(tooltip(h('span', { style: { width: `${v}%`, background: c.colour } }), `${c.label}: ${v.toFixed(1)} points`));
      }
    } else {
      bar.append(h('span', { style: { width: `${Math.min(100, x.u)}%`, background: 'var(--pitch)' } }));
    }
    const kept = stab ? stab.get(p.id) : null;
    const link = st.mode === 'bbb' ? playerHref(p.id) : playerHref(p.rec?.id, p.rec?.title);
    return h('li.xi-row.fade-in', { style: { animationDelay: `${i * 25}ms` } },
      h('span.xi-num', String(i + 1)),
      h('span.avatar', { style: { '--tc': data.teamColour(tname) }, 'aria-hidden': 'true' }, initials(p.name)),
      h('div.xi-main',
        h('div.xi-name',
          link ? h('a', { href: link }, p.name) : h('span', p.name),
          isC ? h('span.badge.c', { title: 'Captain' }, icon('captain', { size: 12 }), 'C') : null,
          isK ? h('span.badge.wk', { title: 'Wicketkeeper' }, icon('keeper', { size: 12 }), 'WK') : null,
          locked ? h('span.badge', icon('lock', { size: 12 }), 'Locked') : null),
        h('div.xi-meta', h('span.role-ico', { style: { color: SLOT_COLOUR[x.type] } }, icon(ROLE_ICON[x.type] || 'ball', { size: 16 })),
          h('span', SLOT_TYPES[x.type]?.label ?? x.type), h('span.faint', '·'), teamLabel(tname, { size: 16 }),
          st.mode === 'hist' ? h('span.faint', `· ${p.stats.span}`) : null),
        h('div.xi-stats.small', statLine(x))),
      h('div.xi-score',
        h('div.xi-u', { title: 'Utility on a 0–100 scale' }, fmt.score(x.u)),
        bar,
        kept != null ? tooltip(h('div.tiny.faint', `kept ${Math.round(kept * 100)}%`), 'Share of 20 reselections, with every weight randomly varied by up to ±25%, that kept this player') : null),
      h('button.btn.sm.ghost.xi-more', { type: 'button', 'aria-label': `Details for ${p.name}`, onclick: () => details(x) }, 'Details'));
  }

  function benchCard() {
    const card = h('div.card.card-pad.bench-card', h('h3.with-ico', icon('shuffle', { size: 18 }), 'Next in line'), h('p.tiny.muted', 'Best unselected candidates for each slot type, with the gap to the weakest selected player in that slot.'));
    // Bench lists are per slot; a free shape has one slot type for all eleven.
    const slotOf = (x) => x.slot ?? x.type;
    const types = [...new Set(result.xi.map(slotOf))].sort((a, b) => SLOT_ORDER.indexOf(a) - SLOT_ORDER.indexOf(b));
    for (const t of types) {
      const weakest = Math.min(...result.xi.filter((x) => slotOf(x) === t).map((x) => x.u));
      const alts = (result.bench[t] || []).slice(0, 3);
      if (!alts.length) continue;
      card.append(h('div.bench-type', h('div.tiny.eyebrow', SLOT_TYPES[t].label),
        alts.map((a) => h('div.bench-row',
          h('a', { href: playerHref(a.player.id) }, a.player.name),
          h('span.bench-team.faint.small', teamLabel(scope.teams[a.player.team] ?? '', { size: 14 })),
          h('span.bench-u.num.small', fmt.score(a.u)),
          h('span.bench-gap.num.tiny', fmt.signed(a.u - weakest)),
          h('button.btn.sm.ghost', { type: 'button', onclick: () => lock(a.player.id), 'aria-label': `Lock ${a.player.name} into the XI` }, icon('lock', { size: 14 }), h('span.btn-label', 'Lock'))))));
    }
    return card;
  }

  function whyNotCard() {
    const out = h('div.whynot-out');
    const input = h('input.input', { type: 'search', placeholder: 'Why not…? Search any candidate', 'aria-label': 'Why not this player', list: 'wn-list' });
    const searchWrap = h('div.input-icon', icon('search', { size: 16 }), input);
    const dl = h('datalist', { id: 'wn-list' }, result.pool.filter((c) => !result.xi.some((x) => x.player.id === c.id))
      .sort((a, b) => Math.max(...Object.values(b.util), 0) - Math.max(...Object.values(a.util), 0)).slice(0, 400)
      .map((c) => h('option', { value: c.name })));
    const run = () => {
      clear(out);
      const c = result.pool.find((p) => p.name.toLowerCase() === input.value.trim().toLowerCase());
      if (!c) return;
      if (result.xi.some((x) => x.player.id === c.id)) { out.append(h('p.small', `${c.name} is already in the eleven.`)); return; }
      const types = Object.keys(c.util);
      if (!types.length) { out.append(h('p.small', `${c.name} is not eligible for any slot in this composition.`)); return; }
      const w = whyNot(scope, settings(), c.id, result);
      if (w.error) { out.append(h('p.small', w.error)); return; }
      out.append(h('p.small', h('strong', c.name), ` would cost the eleven ${Math.abs(w.delta).toFixed(1)} utility points.`,
        w.dropped.length ? ` They would replace ${w.dropped.map((d) => d.player.name).join(', ')}.` : ''),
        h('button.btn.sm', { type: 'button', onclick: () => lock(c.id) }, `Lock ${c.name} in`));
    };
    input.addEventListener('change', run);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });
    return h('div.card.card-pad', h('h3.with-ico', icon('search', { size: 18 }), 'Why not someone else?'),
      h('p.tiny.muted', 'Forces a player in, re-solves the whole eleven, and reports what it costs and who drops out.'),
      searchWrap, dl, out);
  }

  function lock(id) {
    const locks = new Set(st.lock ? st.lock.split(',') : []); locks.add(id);
    const ex = new Set(st.excl ? st.excl.split(',') : []); ex.delete(id);
    set({ lock: [...locks].join(','), excl: [...ex].join(',') }, { recomputeOnly: true });
  }
  function exclude(id) {
    const ex = new Set(st.excl ? st.excl.split(',') : []); ex.add(id);
    const locks = new Set(st.lock ? st.lock.split(',') : []); locks.delete(id);
    set({ excl: [...ex].join(','), lock: [...locks].join(',') }, { recomputeOnly: true });
  }

  function details(x) {
    const p = x.player;
    const d = drawer(p.name, `${SLOT_TYPES[x.type]?.label ?? x.type} · ${teamName(p)}`);
    const s = p.stats, sc = p.sc;
    const rows = st.mode === 'hist'
      ? [['Matches', s.matches], ['Runs', fmt.n(s.runs)], ['Batting average', fmt.avg(s.avg)], ['Era batting average', fmt.avg(s.eraBat)],
         ['Hundreds', s.hundreds || '–'], ['Wickets', s.wkts], ['Bowling average', fmt.avg(s.bowlAvg)], ['Era bowling average', fmt.avg(s.eraBowl)],
         ['Catches / stumpings', `${s.catches} / ${s.stumpings}`], ['Career', s.span]]
      : [['Matches (window)', s.matches], ['Runs', fmt.n(s.runs)], ['Batting average', fmt.avg(s.avg)], ['Strike rate', fmt.sr(s.sr)],
         ['Hundreds / fifties', `${s.hundreds} / ${s.fifties}`], ['Wickets', s.wkts], ['Bowling average', fmt.avg(s.bowlAvg)],
         ['Economy', s.econ?.toFixed(2) ?? '–'], ['Five-fors', s.fiveW], ['Catches / stumpings', `${s.catches} / ${s.stumpings}`],
         ['Usual position', s.posAvg ? s.posAvg.toFixed(1) : '–']];
    d.body.append(h('div.stat-cards', [
      ['Utility', fmt.score(x.u), 'star'], ['Bat quality', fmt.score(sc.batQ), 'bat'], ['Bowl quality', fmt.score(sc.bowlQ), 'ball'],
      ['Experience', fmt.score(sc.exp), 'calendar'], ['Leadership', sc.lead == null ? '–' : fmt.score(sc.lead), 'captain'],
    ].map(([l, v, ic]) => h('div.stat-card', h('span.badge-ico', icon(ic, { size: 22 })), h('div', h('div.label', l), h('div.value', v))))));
    d.body.append(h('p.tiny.muted.mt', 'Scores are on a 0–100 scale where 50 is the average qualified player in this competition and window, and each 15 points is one standard deviation.'));
    d.body.append(h('table.data.mt', h('tbody', rows.map(([k, v]) => h('tr', h('td.muted', k), h('td.r', String(v)))))));
    if (st.mode === 'bbb') {
      d.body.append(h('div.mt', h('div.field-label', 'Eligible roles'),
        h('div.chips.mt', [...p.roles].sort((a, b) => SLOT_ORDER.indexOf(a) - SLOT_ORDER.indexOf(b)).map((r) => h('span.badge', SLOT_TYPES[r].label)))));
      const raw = sc.raw;
      d.body.append(h('p.small.mt', raw.batQ != null ? `Batting adds ${fmt.signed(raw.batQ)} runs ${FAMILY_RULES[scope.family].label} against an average Full-Member batter facing the same bowlers. ` : '',
        raw.bowlQ != null ? `Bowling saves ${fmt.signed(raw.bowlQ)} runs per 100 balls against an average bowler facing the same batters.` : ''));
    }
    d.body.append(h('div.row.mt',
      (st.mode === 'bbb' ? playerHref(p.id) : playerHref(p.rec?.id, p.rec?.title))
        ? h('a.btn.primary', { href: st.mode === 'bbb' ? playerHref(p.id) : playerHref(p.rec?.id, p.rec?.title) }, st.mode === 'bbb' ? 'Full profile' : 'Player page') : null,
      h('button.btn', { type: 'button', onclick: () => { d.close(); exclude(p.id); } }, icon('exclude', { size: 15 }), 'Exclude from XI')));
  }

  // ------------------------------------------------------------ candidates
  let candSort = { key: 'best', dir: -1 }, candFilter = '', candRole = '', candLimit = 40;
  function renderCandidates(parent, pool) {
    const wrap = h('section.card.mt-l', h('div.card-head', h('div', h('h2.display', { style: { fontSize: '22px' } }, 'Every candidate'),
      h('p.tiny.muted', `${pool.length} players with enough evidence for at least one role. Selected players are highlighted.`))));
    const chosen = new Set(result && !result.error ? result.xi.map((x) => x.player.id) : []);
    const controls = h('div.cand-controls',
      h('input.input', { type: 'search', placeholder: 'Filter by name or team', value: candFilter, 'aria-label': 'Filter candidates',
        oninput: debounce((e) => { candFilter = e.target.value; candLimit = 40; draw(); }, 150) }),
      h('select.select', { 'aria-label': 'Filter by role', onchange: (e) => { candRole = e.target.value; draw(); } },
        h('option', { value: '' }, 'All roles'),
        SLOT_ORDER.filter((t) => pool.some((c) => c.roles.has(t))).map((t) => h('option', { value: t, selected: candRole === t }, SLOT_TYPES[t].label))));
    const table = h('div.table-wrap');
    wrap.append(h('div.card-pad', controls, table));
    parent.append(wrap);
    const bestU = (c) => Math.max(...Object.values(c.util), -Infinity);
    const cols = st.mode === 'hist'
      ? [['name', 'Player'], ['team', 'Country'], ['m', 'M', 'r'], ['runs', 'Runs', 'r'], ['avg', 'Avg', 'r'], ['wkts', 'Wkts', 'r'], ['bowlAvg', 'Bowl avg', 'r'], ['batQ', 'Bat Q', 'r'], ['bowlQ', 'Bowl Q', 'r'], ['best', 'Utility', 'r'], ['act', '']]
      : [['name', 'Player'], ['team', st.tier === 'league' ? 'Franchise' : 'Team'], ['m', 'M', 'r'], ['runs', 'Runs', 'r'], ['avg', 'Avg', 'r'], ['sr', 'SR', 'r'], ['wkts', 'Wkts', 'r'], ['econ', 'Econ', 'r'], ['batQ', 'Bat Q', 'r'], ['bowlQ', 'Bowl Q', 'r'], ['best', 'Utility', 'r'], ['act', '']];
    const val = (c, k) => ({ name: c.name, team: teamName(c), m: c.stats.matches, runs: c.stats.runs, avg: c.stats.avg, sr: c.stats.sr,
      wkts: c.stats.wkts, econ: c.stats.econ != null ? -c.stats.econ : null, bowlAvg: c.stats.bowlAvg != null ? -c.stats.bowlAvg : null,
      batQ: c.sc.batQ, bowlQ: c.sc.bowlQ, best: bestU(c) })[k];
    function draw() {
      clear(table);
      const q = candFilter.trim().toLowerCase();
      let rows = pool.filter((c) => (!q || c.name.toLowerCase().includes(q) || teamName(c).toLowerCase().includes(q)) && (!candRole || c.roles.has(candRole)));
      rows.sort((a, b) => {
        const x = val(a, candSort.key), y = val(b, candSort.key);
        if (x == null) return 1; if (y == null) return -1;
        return (typeof x === 'string' ? x.localeCompare(y) : x - y) * candSort.dir;
      });
      const shown = rows.slice(0, candLimit);
      table.append(h('table.data', h('thead', h('tr', cols.map(([k, label, cls]) => h('th', { class: cls || '' },
        k === 'act' ? h('span.sr-only', 'Actions') : h('button', { type: 'button', 'aria-sort': candSort.key === k ? (candSort.dir < 0 ? 'descending' : 'ascending') : null,
          onclick: () => { candSort = { key: k, dir: candSort.key === k ? -candSort.dir : (k === 'name' || k === 'team' ? 1 : -1) }; draw(); } }, label))))),
        h('tbody', shown.map((c) => h('tr', { class: chosen.has(c.id) ? 'is-selected' : '' },
          h('td', (st.mode === 'bbb' ? playerHref(c.id) : playerHref(c.rec?.id, c.rec?.title)) ? h('a', { href: st.mode === 'bbb' ? playerHref(c.id) : playerHref(c.rec?.id, c.rec?.title) }, c.name) : c.name,
            h('div.tiny.faint', [...c.roles].filter((r) => r !== 'bowler' || c.roles.size === 1).map((r) => SLOT_TYPES[r].short).join(' · '))),
          h('td.small', teamLabel(teamName(c), { size: 16 })),
          h('td.r', c.stats.matches), h('td.r', fmt.n(c.stats.runs)), h('td.r', fmt.avg(c.stats.avg)),
          st.mode === 'bbb' ? h('td.r', fmt.sr(c.stats.sr)) : null,
          h('td.r', c.stats.wkts || '–'),
          st.mode === 'bbb' ? h('td.r', c.stats.econ != null ? c.stats.econ.toFixed(2) : '–') : h('td.r', fmt.avg(c.stats.bowlAvg)),
          h('td.r', fmt.score(c.sc.batQ)), h('td.r', fmt.score(c.sc.bowlQ)), h('td.r', h('strong', Number.isFinite(bestU(c)) ? fmt.score(bestU(c)) : '–')),
          h('td.r', chosen.has(c.id)
            ? h('button.btn.sm.ghost', { type: 'button', onclick: () => exclude(c.id), 'aria-label': `Exclude ${c.name}` }, icon('exclude', { size: 14 }), 'Exclude')
            : h('button.btn.sm.ghost', { type: 'button', onclick: () => lock(c.id), 'aria-label': `Lock ${c.name} in` }, icon('lock', { size: 14 }), 'Lock')))))));
      if (rows.length > candLimit) {
        table.append(h('div.card-pad', h('button.btn.sm', { type: 'button', onclick: () => { candLimit += 60; draw(); } }, `Show more (${rows.length - candLimit} left)`)));
      }
    }
    draw();
  }

  function renderAll() {
    renderHero();
    renderRail();
    renderBoard();
  }

  await ensureData();
  if (!isLive(route)) return { destroy() { dead = true; } };
  compute();
  setQuery(toQuery(st), route);
  renderAll();
  return {
    update(r) {
      const q = fromQuery(r.query);
      if (JSON.stringify(toQuery(st)) === JSON.stringify(toQuery({ ...st, ...q }))) return;
      st = defaults(q);
      commit();
    },
    destroy() { stabToken++; dead = true; },
  };
}

function range(a, b) { const out = []; for (let y = a; y <= b; y++) out.push(y); return out; }

function toast(msg) {
  const t = h('div.toast', { role: 'status' }, msg);
  document.body.append(t);
  setTimeout(() => t.classList.add('show'), 10);
  setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 300); }, 2200);
}
