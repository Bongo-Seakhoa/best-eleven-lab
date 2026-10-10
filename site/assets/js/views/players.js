// Player directory: search and filter every profiled player, entirely in memory.
import { h, s, clear, fmt, initials, debounce } from '../ui/dom.js';
import { teamBadge } from '../ui/teams.js';
import * as data from '../data.js';
import { setQuery } from '../app.js';
import { rememberTitle } from '../memory.js';

const PAGE = 60;
const MAX_CHIPS = 6;

export const BOWL_LABELS = {
  RF: 'Right-arm fast', RFM: 'Right-arm fast-medium', RMF: 'Right-arm medium-fast', RM: 'Right-arm medium',
  LF: 'Left-arm fast', LFM: 'Left-arm fast-medium', LMF: 'Left-arm medium-fast', LM: 'Left-arm medium',
  OB: 'Off-spin', LB: 'Leg-spin', SLA: 'Left-arm orthodox', LWS: 'Left-arm wrist-spin',
};
const FAMILY_LABELS = { pace: 'pace', spin: 'spin' };

const ROLE_GROUPS = [
  { key: 'batter', label: 'Batters', any: 'Any batter' },
  { key: 'keeper', label: 'Wicket-keepers', any: 'Any wicket-keeper' },
  { key: 'allrounder', label: 'All-rounders', any: 'Any all-rounder' },
  { key: 'bowler', label: 'Bowlers', any: 'Any bowler' },
  { key: 'other', label: 'Other roles', any: 'Any other role' },
];
const ROLE_SUB_LABELS = {
  'opening batter': 'Opening batters', 'top-order batter': 'Top-order batters', 'middle-order batter': 'Middle-order batters',
  'wicket-keeper-batter': 'Keeper-batters', 'batting all-rounder': 'Batting all-rounders', 'bowling all-rounder': 'Bowling all-rounders',
};
// Role strings that simply restate their group get no sub-option of their own.
const GENERIC_ROLES = new Set(['batter', 'wicket-keeper', 'all-rounder', 'bowler']);

const SORTS = [
  ['match', 'Best match'],
  ['comps', 'Most competitions'],
  ['name', 'Name A–Z'],
  ['country', 'Country'],
];
const NATIONAL_CHIP = { Test: 'Tests', ODI: 'ODIs', T20I: 'T20Is' };

// The pipeline writes a few formatting variants of the same nation; fold them for filtering.
// The authoritative fix belongs in the export, not here.
const COUNTRY_ALIASES = { 'south african': 'South Africa', bharat: 'India' };

// ------------------------------------------------------------- text helpers
const FOLD = { ø: 'o', æ: 'ae', œ: 'oe', ß: 'ss', ł: 'l', đ: 'd', ð: 'd', þ: 'th', ı: 'i' };
function norm(str) {
  return String(str || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[øæœßłđðþı]/g, (c) => FOLD[c])
    .replace(/['’‘`ʻ.]/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}
const cap = (str) => (str ? str[0].toUpperCase() + str.slice(1) : str);
const plural = (n, one, many = `${one}s`) => `${fmt.n(n)} ${n === 1 ? one : many}`;

function cleanCountry(raw) {
  const x = raw.replace(/\(.*?\)/g, '').replace(/\d+$/, '').replace(/\s+/g, ' ').trim();
  return COUNTRY_ALIASES[x.toLowerCase()] ?? x;
}

function roleGroup(role) {
  const x = role.toLowerCase();
  if (!x) return 'none';
  if (/wicket-?keeper/.test(x)) return 'keeper';
  if (/all-?rounder/.test(x)) return 'allrounder';
  if (/bat(ter|sman|swoman)/.test(x)) return 'batter';
  if (/bowl/.test(x)) return 'bowler';
  return 'other';
}
const roleSlug = (role) => role.toLowerCase().trim().replace(/\s+/g, '-');
const SUB_ORDER = Object.keys(ROLE_SUB_LABELS).map(roleSlug);
const subRank = (slug) => { const i = SUB_ORDER.indexOf(slug); return i < 0 ? SUB_ORDER.length : i; };

// Cricsheet names lead with initials ("AB de Villiers"); sort on what follows them.
function sortName(name) {
  const parts = String(name).split(' ');
  while (parts.length > 1 && /^[A-Z]{1,4}$/.test(parts[0])) parts.shift();
  return norm(parts.join(' '));
}

// Cricsheet names carry the familiar form ("Sikandar Raza", "SP Narine"); full names can add family names.
function avatarText(e) {
  for (const src of [e.name, e.full]) {
    const t = src ? initials(src) : '';
    if (/^[A-Za-z]{1,2}$/.test(t)) return t.toUpperCase();
  }
  return '?';
}

// ---------------------------------------------------------- data preparation
let prepared = null;

function prepare(index, meta) {
  if (prepared && prepared.src === index && prepared.meta === meta) return prepared;

  const scopeMeta = new Map(meta.scopes.map((sc) => [sc.key, sc]));
  const order = [...meta.scopes].sort((a, b) => scopeRank(a) - scopeRank(b) || a.label.localeCompare(b.label));
  const scopeOrder = new Map(order.map((sc, i) => [sc.key, i]));
  const chipLabel = (k) => {
    const sc = scopeMeta.get(k);
    if (!sc) return k;
    return sc.tier === 'national' ? (NATIONAL_CHIP[sc.format] ?? sc.label) : (sc.short || sc.label);
  };
  const scopeLabel = (k) => scopeMeta.get(k)?.label ?? k;

  // Fold case variants of each country onto its most common spelling.
  const spellings = new Map();
  for (const p of index) {
    for (const raw of String(p.c || '').split(';')) {
      const c = cleanCountry(raw);
      if (!c) continue;
      const key = c.toLowerCase();
      if (!spellings.has(key)) spellings.set(key, new Map());
      const m = spellings.get(key);
      m.set(c, (m.get(c) || 0) + 1);
    }
  }
  const canon = new Map();
  for (const [key, m] of spellings) canon.set(key, [...m].sort((a, b) => b[1] - a[1])[0][0]);

  const entries = index.map((p) => {
    const name = String(p.n || p.id);
    const full = String(p.f || '').replace(/https?:\/\/\S+/g, '').replace(/\s+/g, ' ').trim();
    const countries = [...new Set(String(p.c || '').split(';').map(cleanCountry).filter(Boolean)
      .map((c) => canon.get(c.toLowerCase()) ?? c))];
    const role = String(p.r || '').trim();
    const nn = norm(name), nf = norm(full);
    const scopes = (Array.isArray(p.s) ? p.s : []).slice()
      .sort((a, b) => (scopeOrder.get(a) ?? 999) - (scopeOrder.get(b) ?? 999));
    const e = {
      id: String(p.id), name, full, showFull: !!nf && nf !== nn,
      countries, countryLabel: countries.join(' / '), countryKey: countries.length ? norm(countries[0]) : '￿',
      tc: countries.length ? data.teamColour(countries[0]) : null,
      role, rg: roleGroup(role), rslug: role ? roleSlug(role) : '',
      bowl: String(p.b || ''), scopes, active: new Set(Array.isArray(p.a) ? p.a : []),
      nn, nf, hay: nf ? `${nn} ${nf}` : nn, sortName: sortName(name),
    };
    e.compact = e.hay.replace(/ /g, '');
    e.words = e.hay.split(' ');
    e.ini = avatarText(e);
    return e;
  });

  // Country options: Full Members first, then everyone else, alphabetically.
  const allCountries = [...new Set(entries.flatMap((e) => e.countries))].sort((a, b) => a.localeCompare(b));
  const full = allCountries.filter((c) => data.FULL_MEMBERS.includes(c));
  const other = allCountries.filter((c) => !data.FULL_MEMBERS.includes(c));

  // Role options: four groups, each with the specific role strings found in the data.
  const subsByGroup = new Map();
  for (const e of entries) {
    if (!e.role || GENERIC_ROLES.has(e.role.toLowerCase())) continue;
    if (!subsByGroup.has(e.rg)) subsByGroup.set(e.rg, new Map());
    subsByGroup.get(e.rg).set(e.rslug, ROLE_SUB_LABELS[e.role.toLowerCase()] ?? `${cap(e.role)}s`);
  }
  const groupsPresent = new Set(entries.map((e) => e.rg));
  const roleGroups = ROLE_GROUPS.filter((g) => groupsPresent.has(g.key)).map((g) => ({
    ...g, subs: [...(subsByGroup.get(g.key) || [])].sort((a, b) => subRank(a[0]) - subRank(b[0]) || a[1].localeCompare(b[1])),
  }));
  const roleValues = new Set(['none', ...roleGroups.flatMap((g) => [g.key, ...g.subs.map(([v]) => v)])]);

  const used = new Set(entries.flatMap((e) => e.scopes));
  const present = order.filter((sc) => used.has(sc.key));
  const scopeGroups = [
    { label: 'International', items: present.filter((sc) => sc.tier === 'national') },
    { label: 'Men’s leagues', items: present.filter((sc) => sc.tier !== 'national' && sc.gender !== 'female') },
    { label: 'Women’s leagues', items: present.filter((sc) => sc.tier !== 'national' && sc.gender === 'female') },
  ].filter((g) => g.items.length);
  for (const g of scopeGroups) if (g.label !== 'International') g.items.sort((a, b) => a.label.localeCompare(b.label));

  prepared = {
    src: index, meta, entries, canon, full, other,
    hasNoCountry: entries.some((e) => !e.countries.length),
    roleGroups, roleValues, hasNoRole: groupsPresent.has('none'),
    scopeGroups, scopeKeys: new Set(present.map((sc) => sc.key)), chipLabel, scopeLabel,
  };
  return prepared;
}

function scopeRank(sc) {
  if (sc.tier === 'national') {
    const f = ['Test', 'ODI', 'T20I'].indexOf(sc.format);
    return (sc.gender === 'female' ? 3 : 0) + (f < 0 ? 2 : f);
  }
  return 10 + (sc.featured ? 0 : 1);
}

// --------------------------------------------------------------- searching
function matchTier(e, qn, toks, qc) {
  if (e.nn === qn || e.nf === qn) return 0;
  if (e.nn.startsWith(qn) || (e.nf && e.nf.startsWith(qn))) return 1;
  if (toks.every((t) => e.words.includes(t))) return 2;
  if (toks.every((t) => e.words.some((w) => w.startsWith(t)))) return 3;
  if (toks.every((t) => e.hay.includes(t)) || (qc.length > 2 && e.compact.includes(qc))) return 4;
  return -1;
}

const byName = (a, b) => (a.sortName < b.sortName ? -1 : a.sortName > b.sortName ? 1 : a.nn < b.nn ? -1 : a.nn > b.nn ? 1 : 0);
const byComps = (a, b) => b.scopes.length - a.scopes.length || b.active.size - a.active.size || byName(a, b);
const byCountry = (a, b) => (a.countryKey < b.countryKey ? -1 : a.countryKey > b.countryKey ? 1 : 0) || byName(a, b);

function inc(map, key) { map.set(key, (map.get(key) || 0) + 1); }

// --------------------------------------------------------------------- view
export async function mount(root, route) {
  const page = h('div.page.pl-page');
  root.append(page);
  let alive = true, view = null, latest = route;

  async function boot() {
    clear(page);
    page.append(heroBlock(null), skeleton());
    try {
      const [meta, index] = await Promise.all([data.meta(), data.playerIndex()]);
      // The router may have moved on (and detached this page) while the data loaded.
      if (!alive || !page.isConnected) return;
      if (!Array.isArray(index) || !Array.isArray(meta?.scopes)) throw new Error('The player list is not in the expected format.');
      clear(page);
      view = directory(page, prepare(index, meta), latest, () => alive);
    } catch (err) {
      if (!alive || !page.isConnected) return;
      clear(page);
      page.append(heroBlock(null), h('div.notice.error', { role: 'alert' }, h('div',
        h('strong', 'The player list could not load. '), String(err?.message || err),
        h('div.mt', h('button.btn.sm', { type: 'button', onclick: boot }, 'Try again')))));
    }
  }
  await boot();

  return {
    update(r) { latest = r; view?.update(r); },
    destroy() { alive = false; view?.destroy(); },
  };
}

function heroBlock(P) {
  const lede = P
    ? h('p.lede', `${fmt.n(P.entries.length)} cricketers with a ball-by-ball profile in at least one of ${P.scopeKeys.size} competitions. Search by name, or narrow the list by country, role and competition.`)
    : h('p.lede', h('span.skeleton.pl-skel-line', { 'aria-hidden': 'true' }), h('span.sr-only', 'Loading the player list'));
  return h('header.pl-hero', h('div.eyebrow', 'Directory'), h('h1.display', 'Players'), lede);
}

function skeleton() {
  return h('div.pl-skel', { 'aria-hidden': 'true' },
    h('div.skeleton.pl-skel-search'),
    h('ul.pl-grid', { role: 'presentation' }, Array.from({ length: 9 }, () => h('li.pl-item', h('div.skeleton.pl-skel-card')))));
}

function directory(page, P, route, isAlive) {
  const st = { q: '', c: '', r: '', s: '', a: false, sort: '' };
  let ignored = [];
  let results = [], counts = null, shown = 0, animate = true;

  // ------------------------------------------------------------ query sync
  function readQuery(q) {
    const next = { q: '', c: '', r: '', s: '', a: false, sort: '' };
    const notes = [];
    next.q = (q.get('q') || '').slice(0, 80);
    const c = (q.get('c') || '').trim();
    if (c) {
      if (c.toLowerCase() === 'none' && P.hasNoCountry) next.c = 'none';
      else {
        const hit = P.canon.get(cleanCountry(c).toLowerCase());
        if (hit) next.c = hit; else notes.push(`no players from “${c}”`);
      }
    }
    const r = (q.get('r') || '').trim().toLowerCase();
    if (r) { if (P.roleValues.has(r)) next.r = r; else notes.push(`no role called “${r}”`); }
    const sc = (q.get('s') || '').trim().toLowerCase();
    if (sc) { if (P.scopeKeys.has(sc)) next.s = sc; else notes.push(`no competition with the key “${sc}”`); }
    next.a = ['1', 'true', 'yes'].includes((q.get('a') || '').toLowerCase());
    const so = (q.get('sort') || '').trim().toLowerCase();
    if (so && SORTS.some(([k]) => k === so)) next.sort = so;
    return { next, notes };
  }

  const defaultSort = () => (st.q.trim() ? 'match' : 'comps');
  const effectiveSort = () => (st.sort && (st.sort !== 'match' || st.q.trim()) ? st.sort : defaultSort());

  function toQuery() {
    const out = {};
    if (st.q.trim()) out.q = st.q.trim();
    if (st.c) out.c = st.c;
    if (st.r) out.r = st.r;
    if (st.s) out.s = st.s;
    if (st.a) out.a = 1;
    if (effectiveSort() !== defaultSort()) out.sort = effectiveSort();
    return out;
  }
  const sameAs = (a) => ['q', 'c', 'r', 's', 'a', 'sort'].every((k) => (k === 'q' ? a.q.trim() === st.q.trim() : a[k] === st[k]));
  const hasFilters = () => !!(st.c || st.r || st.s || st.a);

  // ------------------------------------------------------------- controls
  const searchIcon = s('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', class: 'pl-search-icon', 'aria-hidden': 'true' },
    s('circle', { cx: '11', cy: '11', r: '7' }), s('path', { d: 'm20 20-3.5-3.5' }));
  const input = h('input.input.pl-search-input', {
    type: 'search', id: 'pl-q', placeholder: 'Search by name, e.g. Kohli or Ellyse Perry', autocomplete: 'off',
    spellcheck: 'false', enterkeyhint: 'search', 'aria-keyshortcuts': '/', 'aria-controls': 'pl-results', 'aria-describedby': 'pl-q-hint',
  });
  const clearQ = h('button.pl-clear-q', { type: 'button', 'aria-label': 'Clear search', hidden: true },
    s('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'aria-hidden': 'true' },
      s('path', { d: 'M6 6l12 12M18 6 6 18' })));
  const kbd = h('kbd.pl-kbd', { 'aria-hidden': 'true' }, '/');
  const searchBox = h('div.pl-search',
    h('label.sr-only', { for: 'pl-q' }, 'Search players by name'), searchIcon, input, kbd, clearQ,
    h('span.sr-only', { id: 'pl-q-hint' }, 'Matches Cricsheet names and full names. Press the down arrow to move to the results.'));

  const countrySel = h('select.select', { id: 'pl-c' });
  const roleSel = h('select.select', { id: 'pl-r' });
  const scopeSel = h('select.select', { id: 'pl-s' });
  const sortSel = h('select.select', { id: 'pl-sort' });
  const activeBox = h('input', { type: 'checkbox', id: 'pl-a', 'aria-describedby': 'pl-a-hint' });
  const activeCount = h('span.pl-opt-count');

  // Each option remembers its base label so counts can be refreshed in place.
  const opt = (value, label) => { const o = h('option', { value }, label); o.dataset.base = label; return o; };
  const countryOpts = new Map([['', opt('', 'All countries')]]);
  const fullGroup = h('optgroup', { label: 'Full Members' }, P.full.map((c) => countryOpts.set(c, opt(c, c)).get(c)));
  const otherGroup = h('optgroup', { label: 'Other teams' }, P.other.map((c) => countryOpts.set(c, opt(c, c)).get(c)));
  countrySel.append(countryOpts.get(''), P.full.length ? fullGroup : null, P.other.length ? otherGroup : null);
  if (P.hasNoCountry) { countryOpts.set('none', opt('none', 'Country not recorded')); countrySel.append(countryOpts.get('none')); }

  const roleOpts = new Map([['', opt('', 'All roles')]]);
  roleSel.append(roleOpts.get(''));
  for (const g of P.roleGroups) {
    roleOpts.set(g.key, opt(g.key, g.any));
    roleSel.append(h('optgroup', { label: g.label }, roleOpts.get(g.key),
      g.subs.map(([v, label]) => roleOpts.set(v, opt(v, label)).get(v))));
  }
  if (P.hasNoRole) { roleOpts.set('none', opt('none', 'Role not recorded')); roleSel.append(roleOpts.get('none')); }

  const scopeOpts = new Map([['', opt('', 'All competitions')]]);
  scopeSel.append(scopeOpts.get(''));
  for (const g of P.scopeGroups) {
    scopeSel.append(h('optgroup', { label: g.label }, g.items.map((sc) => scopeOpts.set(sc.key, opt(sc.key, sc.label)).get(sc.key))));
  }
  sortSel.append(...SORTS.map(([k, label]) => h('option', { value: k }, label)));

  const field = (id, label, control) => h('div.field', h('label', { for: id }, label), control);
  const controls = h('section.pl-controls', { role: 'search', 'aria-label': 'Find players' },
    searchBox,
    h('div.pl-filters',
      field('pl-c', 'Country', countrySel),
      field('pl-r', 'Role', roleSel),
      field('pl-s', 'Competition', scopeSel),
      field('pl-sort', 'Sort by', sortSel),
      h('div.pl-active',
        h('label.toggle', { for: 'pl-a' }, activeBox, h('span', 'Active only', activeCount)),
        h('span.sr-only', { id: 'pl-a-hint' }, 'In a current squad, or played recently and not reported retired. With a competition chosen, active in that competition.'))));

  const notice = h('div.pl-notice');
  const countEl = h('p.pl-count', { 'aria-live': 'polite', 'aria-atomic': 'true' });
  const clearAllBtn = h('button.btn.sm.ghost', { type: 'button', onclick: () => resetAll(hasFilters()) }, 'Clear filters');
  const bar = h('div.pl-bar', countEl, clearAllBtn);
  const legend = h('p.pl-legend.tiny.muted',
    h('span.pl-legend-item', h('span.pl-dot', { 'aria-hidden': 'true' }), 'Active there: in a current squad, or played in the last 18 to 24 months and not reported retired.'),
    h('span.pl-legend-item', h('span.badge.model', 'family only'), 'Bowling known only as pace or spin, almost always the model’s estimate from ball-by-ball data. The profile names the source.'));
  const grid = h('ul.pl-grid', { id: 'pl-results', role: 'list', 'aria-label': 'Players' });
  const more = h('div.pl-more');
  const empty = h('div.pl-empty-wrap');

  page.append(heroBlock(P), controls, notice, bar, legend, grid, empty, more);

  // --------------------------------------------------------------- events
  const onType = debounce(() => { if (isAlive()) apply(); }, 120);
  input.addEventListener('input', () => {
    st.q = input.value;
    syncSearchChrome();
    onType();
  });
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); st.q = input.value; apply(); }
    else if (ev.key === 'Escape' && input.value) { ev.preventDefault(); input.value = ''; st.q = ''; syncSearchChrome(); apply(); }
    else if (ev.key === 'ArrowDown') {
      const first = grid.querySelector('.pl-name a');
      if (first) { ev.preventDefault(); first.focus(); }
    }
  });
  clearQ.addEventListener('click', () => { input.value = ''; st.q = ''; syncSearchChrome(); apply(); input.focus(); });
  countrySel.addEventListener('change', () => { st.c = countrySel.value; apply(); });
  roleSel.addEventListener('change', () => { st.r = roleSel.value; apply(); });
  scopeSel.addEventListener('change', () => { st.s = scopeSel.value; apply(); });
  sortSel.addEventListener('change', () => { st.sort = sortSel.value; apply(); });
  activeBox.addEventListener('change', () => { st.a = activeBox.checked; apply(); });

  const onSlash = (ev) => {
    if (ev.key !== '/' || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const t = ev.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    ev.preventDefault();
    input.focus();
    input.select();
  };
  document.addEventListener('keydown', onSlash);

  function syncSearchChrome() {
    const has = input.value.length > 0;
    clearQ.hidden = !has;
    searchBox.classList.toggle('has-value', has);
  }

  function syncControls() {
    if (input.value !== st.q) input.value = st.q;
    countrySel.value = st.c;
    roleSel.value = st.r;
    scopeSel.value = st.s;
    activeBox.checked = st.a;
    syncSearchChrome();
  }

  function resetAll(keepSearch) {
    Object.assign(st, { c: '', r: '', s: '', a: false, sort: '' });
    if (!keepSearch) st.q = '';
    ignored = [];
    syncControls();
    apply();
    (keepSearch ? countrySel : input).focus();
  }

  // -------------------------------------------------------------- compute
  function compute() {
    const qn = norm(st.q);
    const toks = qn ? qn.split(' ') : [];
    const qc = qn.replace(/ /g, '');
    const c = { country: new Map(), role: new Map(), scope: new Map(), totC: 0, totR: 0, totS: 0, active: 0 };
    const out = [];
    for (const e of P.entries) {
      let tier = 0;
      if (qn) { tier = matchTier(e, qn, toks, qc); if (tier < 0) continue; }
      const okC = !st.c || (st.c === 'none' ? e.countries.length === 0 : e.countries.includes(st.c));
      const okR = !st.r || e.rg === st.r || e.rslug === st.r;
      const okS = !st.s || e.scopes.includes(st.s);
      const isActive = st.s ? e.active.has(st.s) : e.active.size > 0;
      const okA = !st.a || isActive;
      if (okR && okS && okA) {
        c.totC++;
        if (e.countries.length) for (const k of e.countries) inc(c.country, k); else inc(c.country, 'none');
      }
      if (okC && okS && okA) {
        c.totR++;
        inc(c.role, e.rg);
        if (e.rslug && e.rslug !== e.rg) inc(c.role, e.rslug);
      }
      if (okC && okR) {
        if (!st.a || e.active.size > 0) c.totS++;
        for (const k of e.scopes) if (!st.a || e.active.has(k)) inc(c.scope, k);
      }
      if (okC && okR && okS && isActive) c.active++;
      if (okC && okR && okS && okA) { e._tier = tier; out.push(e); }
    }
    const sort = effectiveSort();
    if (sort === 'match') out.sort((a, b) => a._tier - b._tier || byComps(a, b));
    else if (sort === 'name') out.sort(byName);
    else if (sort === 'country') out.sort(byCountry);
    else out.sort(byComps);
    results = out;
    counts = c;
  }

  function refreshOptions(map, countsMap, total, selected) {
    for (const [value, o] of map) {
      const n = value === '' ? total : (countsMap.get(value) || 0);
      o.textContent = `${o.dataset.base} (${fmt.n(n)})`;
      o.disabled = n === 0 && value !== '' && value !== selected;
    }
  }

  function renderControls() {
    refreshOptions(countryOpts, counts.country, counts.totC, st.c);
    refreshOptions(roleOpts, counts.role, counts.totR, st.r);
    refreshOptions(scopeOpts, counts.scope, counts.totS, st.s);
    activeCount.textContent = ` (${fmt.n(counts.active)})`;
    const hasQ = !!st.q.trim();
    for (const o of sortSel.options) if (o.value === 'match') o.disabled = !hasQ;
    sortSel.value = effectiveSort();
    syncControls();
  }

  function renderNotice() {
    clear(notice);
    if (!ignored.length) return;
    notice.append(h('div.notice.info', h('div', h('strong', 'Part of this link was ignored. '),
      `The data has ${ignored.join(', and ')}, so ${ignored.length > 1 ? 'those filters are' : 'that filter is'} off.`)));
  }

  function renderCount() {
    clear(countEl);
    const total = results.length;
    const q = st.q.trim();
    countEl.append(h('strong', fmt.n(total)), ` ${total === 1 ? 'player' : 'players'}`);
    if (q) countEl.append(` matching “${q}”`);
    if (total > shown) countEl.append(h('span.muted', ` · showing ${fmt.n(shown)}`));
    clearAllBtn.hidden = !hasFilters() && !q;
    clearAllBtn.textContent = hasFilters() ? 'Clear filters' : 'Clear search';
  }

  function renderResults() {
    clear(grid);
    clear(empty);
    shown = Math.min(PAGE, results.length);
    grid.hidden = results.length === 0;
    legend.hidden = results.length === 0;
    const frag = document.createDocumentFragment();
    results.slice(0, shown).forEach((e, i) => frag.append(card(e, animate ? i : -1)));
    grid.append(frag);
    animate = false;
    if (!results.length) empty.append(emptyState());
    renderMore();
  }

  function renderMore() {
    clear(more);
    const left = results.length - shown;
    if (left <= 0) return;
    more.append(h('button.btn', { type: 'button', onclick: showMore },
      `Show ${fmt.n(Math.min(PAGE, left))} more`, h('span.muted.small', `${fmt.n(left)} left`)));
  }

  function showMore() {
    const start = shown;
    shown = Math.min(results.length, shown + PAGE);
    const frag = document.createDocumentFragment();
    results.slice(start, shown).forEach((e) => frag.append(card(e, -1)));
    grid.append(frag);
    renderMore();
    renderCount();
    grid.children[start]?.querySelector('.pl-name a')?.focus();
  }

  function emptyState() {
    const q = st.q.trim();
    const filters = hasFilters();
    const lines = [];
    if (q && filters) lines.push(`Nobody called “${q}” fits these filters.`);
    else if (q) lines.push(`Nobody in the data is called “${q}”.`);
    else lines.push('Nobody fits this combination of filters.');
    if (q) lines.push('Cricsheet lists most players by initials and surname, such as “V Kohli”. Full names come from Wikipedia where a match was found, so try a surname alone.');
    const actions = [];
    if (q && filters) {
      actions.push(h('button.btn.primary', { type: 'button', onclick: () => resetAll(true) }, 'Keep the search, clear filters'));
      actions.push(h('button.btn', { type: 'button', onclick: () => resetAll(false) }, 'Clear everything'));
    } else {
      actions.push(h('button.btn.primary', { type: 'button', onclick: () => resetAll(false) }, q ? 'Clear search' : 'Clear filters'));
    }
    return h('div.card.pl-empty',
      h('h2.display', 'No players match'),
      lines.map((l, i) => h(i ? 'p.small.muted' : 'p', l)),
      h('div.row.pl-empty-actions', actions));
  }

  function card(e, delayIndex) {
    const link = h('a', { href: `#/player/${encodeURIComponent(e.id)}` }, e.name);
    const avatar = h('span.pl-avatar', { 'aria-hidden': 'true' }, e.ini);
    if (e.tc) avatar.style.setProperty('--tc', e.tc);
    const sep = () => h('span.pl-sep', { 'aria-hidden': 'true' }, '·');
    const facts = !e.countries.length && !e.role
      ? h('div.pl-fact', h('span.faint', 'Country and role not recorded'))
      : h('div.pl-fact',
        e.countries.length ? h('span.team-label', e.countries.map((c) => teamBadge(c, { size: 16 })), e.countryLabel) : h('span.faint', 'Country not recorded'),
        sep(),
        e.role ? h('span', cap(e.role)) : h('span.faint', 'Role not recorded'));
    const el = h('article.pl-card', delayIndex >= 0 ? { class: 'fade-in', style: { animationDelay: `${Math.min(delayIndex, 12) * 18}ms` } } : null,
      h('div.pl-top', avatar,
        h('div.pl-id', h('h3.pl-name', link), e.showFull ? h('div.pl-full', e.full) : null)),
      h('div.pl-facts', facts, bowlLine(e.bowl)),
      comps(e));
    return h('li.pl-item', el);
  }

  function bowlLine(code) {
    if (!code) return null;
    if (BOWL_LABELS[code]) return h('div.pl-bowl', h('span.muted', 'Bowls'), ' ', BOWL_LABELS[code].toLowerCase());
    if (FAMILY_LABELS[code]) {
      return h('div.pl-bowl', h('span.muted', 'Bowls'), ' ', FAMILY_LABELS[code],
        h('span.badge.model.pl-badge', { title: 'Arm and speed not recorded. For almost every such player the pace or spin call is the model’s estimate; the profile names the source.' }, 'family only'));
    }
    return h('div.pl-bowl', h('span.muted', 'Bowling'), ' ', code);
  }

  function comps(e) {
    if (!e.scopes.length) return null;
    // Where a player is active now matters most, so those chips come first; a chosen competition always shows.
    let keys = [...e.scopes.filter((k) => e.active.has(k)), ...e.scopes.filter((k) => !e.active.has(k))];
    if (st.s && keys.indexOf(st.s) >= MAX_CHIPS - 1) keys = [st.s, ...keys.filter((k) => k !== st.s)];
    const vis = keys.length > MAX_CHIPS ? keys.slice(0, MAX_CHIPS - 1) : keys;
    const rest = keys.slice(vis.length);
    const list = h('ul.pl-comps', { 'aria-label': 'Competitions with a profile' },
      vis.map((k) => {
        const act = e.active.has(k);
        return h('li.pl-comp', { class: [act ? 'is-active' : '', st.s === k ? 'is-match' : ''].join(' ').trim() || null },
          P.chipLabel(k), act ? h('span.sr-only', ', active') : null);
      }));
    if (rest.length) {
      const actRest = rest.filter((k) => e.active.has(k)).length;
      list.append(h('li.pl-comp.more', h('span', { 'aria-hidden': 'true' }, `+${rest.length}`),
        h('span.sr-only', `and ${rest.length} more: ${rest.map((k) => P.chipLabel(k) + (e.active.has(k) ? ', active' : '')).join('; ')}`),
        actRest ? h('span.pl-dot.sm', { 'aria-hidden': 'true' }) : null));
    }
    return list;
  }

  /** Short title for the return link to this directory, naming the search and filters in force. */
  function directoryTitle() {
    const bits = [];
    const q = st.q.trim();
    if (q) bits.push(`“${q.length > 20 ? `${q.slice(0, 19)}…` : q}”`);
    if (st.c) bits.push(st.c === 'none' ? 'no country' : st.c);
    if (st.r) bits.push(st.r === 'none' ? 'no role' : (ROLE_GROUPS.find((g) => g.key === st.r)?.label || roleOpts.get(st.r)?.dataset.base || st.r).toLowerCase());
    if (st.s) bits.push(P.meta.scopes.find((x) => x.key === st.s)?.tier === 'national' ? P.scopeLabel(st.s).replace(/'/g, '’') : P.chipLabel(st.s));
    if (st.a) bits.push('active');
    const t = bits.length ? `Directory: ${bits.join(', ')}` : 'Directory';
    return t.length > 40 ? `${t.slice(0, 39).trimEnd()}…` : t;
  }

  // ----------------------------------------------------------------- flow
  function apply() {
    compute();
    renderControls();
    renderResults();
    renderCount();
    renderNotice();
    setQuery(toQuery(), route);
    rememberTitle('players', directoryTitle());
  }

  const first = readQuery(route.query);
  Object.assign(st, first.next);
  ignored = first.notes;
  syncControls();
  apply();

  return {
    update(r) {
      const { next, notes } = readQuery(r.query);
      if (sameAs(next) && !notes.length) return;
      Object.assign(st, next);
      ignored = notes;
      syncControls();
      apply();
    },
    destroy() { document.removeEventListener('keydown', onSlash); },
  };
}
