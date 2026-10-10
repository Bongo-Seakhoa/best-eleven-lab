// Captains: formal captaincy records from Wikipedia's captaincy lists, with a
// sortable leaderboard and up to four captains compared side by side.
import { h, clear, fmt, initials, tooltip, debounce } from '../ui/dom.js';
import { teamLabel } from '../ui/teams.js';
import * as data from '../data.js';
import { resultBar } from '../ui/charts.js';
import { setQuery } from '../app.js';
import { playerHref } from '../ui/links.js';
import { recordKey, careerRows, careerFigures, MAX_COMPARE, SCOPE_DEFAULTS } from '../ui/captaincy.js';
import { rememberTitle } from '../memory.js';

const BEST_MIN = 20;
const PAGE_ROWS = 60;
const MIN_MAX = 100;
const FORMATS = ['Test', 'ODI', 'T20I'];
const DEFAULTS = { ...SCOPE_DEFAULTS, comp: '', team: '', min: 10, q: '', ids: '', sort: 'win' };
const LEAGUE_SHORT = {
  'Indian Premier League': 'IPL', 'Big Bash League': 'BBL', 'Pakistan Super League': 'PSL',
  'Bangladesh Premier League': 'BPL', 'Champions League Twenty20': 'CLT20',
};
const RESULTS = [['won', 'W', 'Won'], ['lost', 'L', 'Lost'], ['drawn', 'D', 'Drawn'], ['tied', 'T', 'Tied'], ['nr', 'NR', 'No result']];
const LEGEND = [['Won', 'var(--strength)'], ['Lost', 'var(--weakness)'], ['Drawn', 'var(--faint)'], ['Tied', 'var(--gold)'], ['No result', 'var(--line)']];
// Natural direction per sort key: 1 ascending, -1 descending.
const SORTS = {
  name: { dir: 1, val: (c) => c.name },
  team: { dir: 1, val: (c) => c.team },
  format: { dir: 1, val: (c) => c.fmtLabel },
  span: { dir: 1, val: (c) => c.first },
  played: { dir: -1, val: (c) => c.played },
  won: { dir: -1, val: (c) => c.won },
  lost: { dir: -1, val: (c) => c.lost },
  drawn: { dir: -1, val: (c) => c.drawn },
  tied: { dir: -1, val: (c) => c.tied },
  nr: { dir: -1, val: (c) => c.nr },
  win: { dir: -1, val: (c) => c.win },
};
const NOTE_TEXT = {
  'drawn includes tied': 'The source counts ties among the draws.',
  'tied includes no result': 'The source counts no-results among the ties.',
  'tied exceeds lost': 'The source page may have its Lost and Tied figures swapped.',
};

// ------------------------------------------------------------------ helpers
const toNum = (v) => {
  if (v == null || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
const fold = (s) => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];
const word = (n) => (n >= 0 && n <= 10 ? WORDS[n] : String(n));
const plural = (n, one, many) => `${n === 1 ? one : many}`;
const wikiUrl = (title) => `https://en.wikipedia.org/wiki/${encodeURIComponent(title.replace(/ /g, '_'))}`;
const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/** Family name for short titles: "Smith", "de Villiers". */
function surname(name) {
  const parts = String(name).trim().split(/\s+/);
  let i = parts.length - 1;
  while (i > 0 && /^[a-z]/.test(parts[i - 1])) i--;
  return parts.slice(i).join(' ');
}

/** "Smith", "Smith and Waugh", "Smith, Ponting and Waugh", shortened past ~38 characters. */
function nameList(names) {
  const join = (xs) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);
  const full = join(names);
  return full.length <= 38 || names.length < 3 ? full : `${names.slice(0, 2).join(', ')} and ${names.length - 2} more`;
}

function matchNoun(c, n) {
  if (c.level === 'franchise') return `${c.fmtLabel} ${n === 1 ? 'match' : 'matches'}`;
  return n === 1 ? c.format : `${c.format}s`;
}

function spanText(c) {
  if (c.first == null) return '–';
  if (c.ongoing) return `${c.first}–present`;
  return c.last == null || c.last === c.first ? String(c.first) : `${c.first}–${c.last}`;
}

function teamText(c, max = 0) {
  if (!max || c.teams.length <= max) return c.teams.join(', ');
  return `${c.teams.slice(0, max).join(', ')} +${c.teams.length - max} more`;
}

/** "as Australia captain" or "as captain of A and B" for multi-team franchise records. */
function captainOf(c) {
  if (c.teams.length <= 1) return `as ${c.team} captain`;
  const list = c.teams.length > 3 ? [...c.teams.slice(0, 2), `${c.teams.length - 2} other teams`] : c.teams;
  return `as captain of ${list.slice(0, -1).join(', ')} and ${list[list.length - 1]}`;
}

function scopeTitle(c) {
  const g = c.gender === 'female' ? 'Women’s ' : '';
  return c.level === 'franchise' ? c.fmtLabel : `${g}${c.format}`;
}

function mismatchText(c) {
  if (c.played == null) return '';
  if (c.resultSum < c.played) {
    return c.resultSum === 0 ? 'The source gives no results for these matches.'
      : `The source’s results account for ${c.resultSum} of the ${c.played} matches listed.`;
  }
  if (c.resultSum > c.played) return `The source’s results add up to ${c.resultSum}, more than the ${c.played} matches listed.`;
  return '';
}

/** Result bar with a hatched remainder for matches the source leaves unaccounted for. */
function results(c, size = '') {
  const rec = {};
  for (const [k] of RESULTS) rec[k === 'nr' ? 'no_result' : k] = c[k] ?? 0;
  const label = [`${c.played ?? 'unknown'} played`,
    ...RESULTS.filter(([k]) => c[k] != null).map(([k, , long]) => `${long.toLowerCase()} ${c[k]}`)];
  const gap = c.played != null && c.resultSum < c.played ? c.played - c.resultSum : 0;
  if (gap) label.push(`${gap} not accounted for in the source`);
  const wrap = h(`div.cap-rbar${size ? '.' + size : ''}`, { role: 'img', 'aria-label': `Results: ${label.join(', ')}` });
  if (c.resultSum > 0) {
    const bar = resultBar(rec);
    bar.removeAttribute('role');
    bar.removeAttribute('aria-label');
    bar.setAttribute('aria-hidden', 'true');
    bar.style.flexBasis = gap ? `${(100 * c.resultSum) / c.played}%` : '100%';
    wrap.append(bar);
  }
  if (gap) wrap.append(tooltip(h('span.cap-rbar-gap', { 'aria-hidden': 'true' }), `${gap} ${plural(gap, 'match', 'matches')} not accounted for in the source`));
  return wrap;
}

function legend(withGap = true) {
  return h('div.legend.cap-legend', { 'aria-hidden': 'true' },
    LEGEND.map(([l, col]) => h('span.legend-item', h('span.swatch', { style: { background: col } }), l)),
    withGap ? h('span.legend-item', h('span.swatch.cap-swatch-gap'), 'Not in source') : null);
}

function keepFocus(container, fn) {
  const a = document.activeElement;
  const fk = a && container.contains(a) ? a.dataset.fk : null;
  fn();
  if (fk) container.querySelector(`[data-fk="${CSS.escape(fk)}"]`)?.focus();
}

// -------------------------------------------------------------------- state
function readQuery(q) {
  const st = { ...DEFAULTS };
  if (q.get('level') === 'franchise') st.level = 'franchise';
  if (q.get('g') === 'female') st.g = 'female';
  if (q.has('f')) {
    const f = q.get('f');
    if (f === '' || f === 'all') st.f = '';
    else if (FORMATS.includes(f)) st.f = f;
  }
  st.comp = q.get('comp') || '';
  st.team = q.get('team') || '';
  const m = parseInt(q.get('min'), 10);
  if (Number.isFinite(m)) st.min = Math.min(MIN_MAX, Math.max(1, m));
  st.q = (q.get('q') || '').slice(0, 60);
  st.ids = q.get('ids') || '';
  const [key, dir] = (q.get('sort') || '').split('.');
  if (SORTS[key] && (!dir || dir === 'asc' || dir === 'desc')) st.sort = dir ? `${key}.${dir}` : key;
  return st;
}

function writeQuery(st) {
  const out = {};
  if (st.level !== DEFAULTS.level) out.level = st.level;
  if (st.g !== DEFAULTS.g) out.g = st.g;
  if (st.level === 'international' && st.f !== DEFAULTS.f) out.f = st.f;
  if (st.level === 'franchise' && st.comp) out.comp = st.comp;
  if (st.team) out.team = st.team;
  if (st.min !== DEFAULTS.min) out.min = st.min;
  if (st.q) out.q = st.q;
  if (st.ids) out.ids = st.ids;
  if (st.sort !== DEFAULTS.sort) out.sort = st.sort;
  return out;
}

function parseSort(sort) {
  const [key, dir] = sort.split('.');
  const natural = SORTS[key].dir;
  return { key, dir: dir === 'asc' ? 1 : dir === 'desc' ? -1 : natural, natural };
}

function sortString(key, dir) {
  if (dir === SORTS[key].dir) return key;
  return `${key}.${dir > 0 ? 'asc' : 'desc'}`;
}

// --------------------------------------------------------------------- data
function prepare(rows, profiles, leagues) {
  const seen = new Set();
  return rows.map((r) => {
    let key = recordKey(r);
    while (seen.has(key)) key += 'x';
    seen.add(key);
    const c = {
      key, level: r.level, gender: r.gender, format: r.format, comp: r.competition || '',
      name: r.name, wiki: r.wikipedia_title, source: r.source_page,
      team: r.country_or_team, teams: r.country_or_team.split(/;\s*/).filter(Boolean),
      id: r.cricsheet_id || '',
      first: toNum(r.first_year), last: toNum(r.last_year),
      played: toNum(r.played), won: toNum(r.won), lost: toNum(r.lost), drawn: toNum(r.drawn),
      tied: toNum(r.tied), nr: toNum(r.no_result), win: toNum(r.win_pct),
    };
    // Without the player list, try the profile and let it report a failure.
    c.hasProfile = !!c.id && (!profiles || profiles.has(c.id));
    c.ongoing = c.last == null && c.first != null;
    const league = leagues.get(c.comp);
    c.fmtLabel = c.level === 'franchise' ? (LEAGUE_SHORT[c.comp] || league?.short || c.comp) : c.format;
    c.scopeKey = c.level === 'international'
      ? `${c.gender === 'male' ? 'men' : 'women'}-${c.format.toLowerCase()}` : (league?.key || null);
    c.careerKey = c.level === 'international' ? `${c.gender === 'female' ? 'W' : ''}${c.format}` : null;
    c.resultSum = RESULTS.reduce((a, [k]) => a + (c[k] || 0), 0);
    c.flag = mismatchText(c);
    c.search = fold(`${c.name} ${c.team}`);
    return c;
  });
}

// --------------------------------------------------------------------- view
export async function mount(root, route) {
  const page = h('div.page.cap-page');
  root.append(page);
  let st = readQuery(route.query);
  let all = [], byKey = new Map(), meta = null, notices = [];
  let limit = PAGE_ROWS;
  let observer = null;
  const cardCache = new Map();
  const rowChecks = new Map();

  const live = h('div.sr-only', { role: 'status', 'aria-live': 'polite' });
  const hero = h('header.cap-hero');
  const compareEl = h('section.card.cap-compare', { 'aria-labelledby': 'cap-compare-title', hidden: true });
  const filtersEl = h('section.card.card-pad.cap-filters', { 'aria-label': 'Filters' });
  const insightsEl = h('div.cap-insights');
  const resultsEl = h('section.card.cap-results', { 'aria-labelledby': 'cap-results-title' });
  const tray = h('div.cap-tray', { hidden: true, role: 'region', 'aria-label': 'Comparison shortcut' });

  let destroyed = false;
  const announce = (msg) => { live.textContent = ''; requestAnimationFrame(() => { live.textContent = msg; }); };
  // Guard: a debounced write must not land on another page after navigation.
  const syncUrl = debounce(() => {
    if (!destroyed && /^#\/captains(\?|$)/.test(location.hash || '#/captains')) persist();
  }, 120);

  /** Write the state to the URL and give the saved page a short title. */
  function persist() {
    setQuery(writeQuery(st), route);
    const list = selected().list;
    let title;
    if (list.length === 1) title = `${surname(list[0].name)}’s record`;
    else if (list.length) title = nameList(list.map((c) => surname(c.name)));
    else {
      title = `${scopeLabel()} captains`;
      title = title.charAt(0).toUpperCase() + title.slice(1);
      if (st.q.trim() && title.length + st.q.trim().length < 34) title += ` “${st.q.trim()}”`;
    }
    rememberTitle('captains', title);
  }

  // ------------------------------------------------------------- loading
  function skeleton() {
    return h('div', { 'aria-busy': 'true' },
      h('header.cap-hero', h('div.eyebrow', 'Captains'), h('h1.display', 'Captaincy records, side by side'),
        h('div.skeleton', { style: { height: '20px', maxWidth: '560px' } })),
      h('div.skeleton', { style: { height: '120px', marginBottom: '18px' } }),
      h('div.skeleton', { style: { height: '420px' } }),
      h('span.sr-only', 'Loading captaincy records'));
  }

  async function load() {
    clear(page);
    page.append(skeleton());
    const [capR, metaR, ixR] = await Promise.allSettled([data.captains(), data.meta(), data.playerIndex()]);
    clear(page);
    if (capR.status === 'rejected' || !Array.isArray(capR.value?.rows)) {
      const msg = capR.status === 'rejected' ? String(capR.reason?.message || capR.reason) : 'The file has no rows.';
      page.append(h('header.cap-hero', h('div.eyebrow', 'Captains'), h('h1.display', 'Captaincy records, side by side')),
        h('div.notice.error', { role: 'alert' }, h('div',
          h('strong', 'The captaincy records could not load. '), msg,
          h('div.mt', h('button.btn.sm', { type: 'button', onclick: load }, 'Try again')))));
      return false;
    }
    meta = metaR.status === 'fulfilled' ? metaR.value : null;
    const profiles = ixR.status === 'fulfilled' ? new Set(ixR.value.map((p) => p.id)) : null;
    const leagues = new Map((meta?.scopes || []).filter((s) => s.tier === 'league').map((s) => [s.label, s]));
    notices = [];
    if (ixR.status === 'rejected') notices.push('The player list could not load, so playing records in the comparison may be missing.');
    all = prepare(capR.value.rows, profiles, leagues);
    byKey = new Map(all.map((c) => [c.key, c]));
    page.append(live, hero, compareEl, filtersEl, insightsEl, resultsEl, tray);
    renderAll();
    watchCompare();
    return true;
  }

  // --------------------------------------------------------------- state
  function selected() {
    const keys = [...new Set(st.ids.split(',').filter(Boolean))];
    const known = keys.filter((k) => byKey.has(k));
    return { list: known.slice(0, MAX_COMPARE).map((k) => byKey.get(k)), missing: keys.length - known.length, extra: Math.max(0, known.length - MAX_COMPARE) };
  }

  function setIds(keys) {
    st.ids = keys.join(',');
    syncUrl();
  }

  function scopeRows() {
    return all.filter((c) => {
      if (c.level !== st.level || c.gender !== st.g) return false;
      if (st.level === 'international' && st.f && c.format !== st.f) return false;
      if (st.level === 'franchise' && st.comp && c.comp !== st.comp) return false;
      return true;
    });
  }

  function filtered() {
    const scoped = scopeRows().filter((c) => !st.team || c.teams.includes(st.team));
    const q = fold(st.q.trim());
    const shown = scoped.filter((c) => c.played != null && c.played >= st.min && (!q || c.search.includes(q)));
    return { scoped, shown };
  }

  function change(patch, parts = 'results') {
    Object.assign(st, patch);
    limit = PAGE_ROWS;
    syncUrl();
    if (parts === 'all') keepFocus(filtersEl, renderFilters);
    else renderFiltersFoot();
    keepFocus(insightsEl, renderInsights);
    renderResults();
  }

  // ---------------------------------------------------------------- hero
  function renderHero() {
    clear(hero);
    const nations = new Set(all.filter((c) => c.level === 'international').map((c) => c.team)).size;
    const comps = new Set(all.filter((c) => c.level === 'franchise').map((c) => c.comp)).size;
    hero.append(
      h('div.eyebrow', 'Captains'),
      h('h1.display', 'Captaincy records, side by side'),
      h('p.lede', `Compare any captain from any team. These are the formal records in Wikipedia’s captaincy lists: `
        + `${nations} national sides across Tests, ODIs and T20Is, men and women, plus ${word(comps)} men’s franchise competitions. `
        + 'Filter the table, then tick up to four captains to set their records next to each other.'));
    if (notices.length) hero.append(h('div.notice', notices.map((n) => h('div', n))));
  }

  // ------------------------------------------------------------- filters
  function seg(options, value, onPick, label, fkPrefix) {
    return h('div.seg.block', { role: 'group', 'aria-label': label },
      options.map(([v, text, disabled, title]) => h('button', {
        type: 'button', 'aria-pressed': String(value === v), disabled: !!disabled && value !== v, title: title || null,
        'data-fk': `${fkPrefix}-${v || 'all'}`, onclick: () => { if (value !== v) onPick(v); },
      }, text)));
  }

  function teamOptions() {
    const counts = new Map();
    for (const c of scopeRows()) for (const t of c.teams) counts.set(t, (counts.get(t) || 0) + 1);
    const teams = [...counts.keys()];
    if (st.level === 'international') {
      teams.sort((a, b) => (data.FULL_MEMBERS.includes(b) - data.FULL_MEMBERS.includes(a)) || a.localeCompare(b));
    } else {
      teams.sort((a, b) => a.localeCompare(b));
    }
    return teams;
  }

  function renderFilters() {
    clear(filtersEl);
    const has = (level, g) => all.some((c) => c.level === level && c.gender === g);
    const noWomenFr = !has('franchise', 'female') ? 'No women’s franchise captaincy lists yet' : '';
    const levelSeg = seg([['international', 'International'], ['franchise', 'Franchise', !has('franchise', st.g), st.g === 'female' ? noWomenFr : '']], st.level,
      (v) => change({ level: v, team: '', comp: '' }, 'all'), 'Level', 'level');
    const genderSeg = seg([
      ['male', 'Men', !has(st.level, 'male')],
      ['female', 'Women', !has(st.level, 'female'), st.level === 'franchise' ? noWomenFr : ''],
    ], st.g, (v) => change({ g: v, team: '', comp: '' }, 'all'), 'Gender', 'g');

    let formatField;
    if (st.level === 'international') {
      const hasF = (f) => all.some((c) => c.level === 'international' && c.gender === st.g && c.format === f);
      formatField = h('div.field', h('span.field-label', { id: 'cap-f-label' }, 'Format'),
        seg([...FORMATS.map((f) => [f, f, !hasF(f)]), ['', 'All']], st.f, (v) => {
          const keepTeam = !st.team || all.some((c) => c.level === 'international' && c.gender === st.g && (!v || c.format === v) && c.teams.includes(st.team));
          change({ f: v, team: keepTeam ? st.team : '' }, 'all');
        }, 'Format', 'f'));
    } else {
      const comps = [...new Set(all.filter((c) => c.level === 'franchise' && c.gender === st.g).map((c) => c.comp))]
        .sort((a, b) => a.localeCompare(b));
      const sel = h('select.select', { id: 'cap-comp', 'data-fk': 'comp', onchange: (e) => change({ comp: e.target.value, team: '' }, 'all') },
        h('option', { value: '' }, 'All competitions'),
        comps.map((c) => h('option', { value: c, selected: c === st.comp }, c)),
        st.comp && !comps.includes(st.comp) ? h('option', { value: st.comp, selected: true }, `${st.comp} (no records)`) : null);
      formatField = h('div.field', h('label', { for: 'cap-comp' }, 'Competition'), sel);
    }

    const teams = teamOptions();
    const teamSel = h('select.select', { id: 'cap-team', 'data-fk': 'team', onchange: (e) => change({ team: e.target.value }) },
      h('option', { value: '' }, st.level === 'franchise' ? 'All franchises' : 'All teams'),
      teams.map((t) => h('option', { value: t, selected: t === st.team }, t)),
      st.team && !teams.includes(st.team) ? h('option', { value: st.team, selected: true }, `${st.team} (no records)`) : null);

    const out = h('output', { for: 'cap-min', id: 'cap-min-out' }, String(st.min));
    const minInput = h('input', {
      type: 'range', id: 'cap-min', 'data-fk': 'min', min: 1, max: MIN_MAX, step: 1, value: st.min,
      'aria-describedby': 'cap-min-hint',
      oninput: (e) => { out.textContent = e.target.value; change({ min: Number(e.target.value) }); },
    });
    const search = h('input.input', {
      type: 'search', id: 'cap-q', 'data-fk': 'q', value: st.q, placeholder: 'Name or team', autocomplete: 'off',
      oninput: debounce((e) => change({ q: e.target.value.slice(0, 60) }), 150),
    });

    filtersEl.append(
      h('div.field', h('span.field-label', 'Level'), levelSeg),
      h('div.field', h('span.field-label', 'Gender'), genderSeg),
      formatField,
      h('div.field', h('label', { for: 'cap-team' }, st.level === 'franchise' ? 'Franchise' : 'Team'), teamSel),
      h('div.field.slider-row.cap-min', h('label', { for: 'cap-min' }, 'Minimum matches as captain'), out, minInput,
        h('div.hint', { id: 'cap-min-hint' }, `Most successful only counts captains with ${BEST_MIN} or more.`)),
      h('div.field', h('label', { for: 'cap-q' }, 'Find a captain'), search),
      filtersFoot);
    renderFiltersFoot();
  }

  const filtersFoot = h('div.cap-filters-foot');
  function renderFiltersFoot() {
    clear(filtersFoot);
    const isDefault = ['level', 'g', 'f', 'comp', 'team', 'min', 'q'].every((k) => st[k] === DEFAULTS[k]);
    filtersFoot.hidden = isDefault;
    if (isDefault) return;
    filtersFoot.append(h('button.btn.sm.ghost', {
      type: 'button',
      onclick: () => {
        change({ level: DEFAULTS.level, g: DEFAULTS.g, f: DEFAULTS.f, comp: '', team: '', min: DEFAULTS.min, q: '' }, 'all');
        document.getElementById('cap-team')?.focus();
        announce('Filters reset.');
      },
    }, 'Reset filters'));
  }

  // ------------------------------------------------------------ insights
  function scopeLabel(withTeam = true) {
    const g = st.g === 'male' ? 'men’s' : 'women’s';
    const what = st.level === 'franchise' ? (st.comp ? (LEAGUE_SHORT[st.comp] || st.comp) : 'franchise')
      : `${g} ${st.f || 'international'}`;
    return `${withTeam && st.team ? `${st.team} ` : ''}${what}`;
  }

  function renderInsights() {
    clear(insightsEl);
    const { scoped } = filtered();
    const threshold = Math.max(BEST_MIN, st.min);
    const pool = scoped.filter((c) => c.played != null && c.played >= threshold && c.win != null)
      .sort((a, b) => b.win - a.win || b.played - a.played || a.name.localeCompare(b.name));
    const best = pool[0];
    const card = h('section.card.card-pad.cap-best', { 'aria-labelledby': 'cap-best-title' },
      h('div.eyebrow', { id: 'cap-best-title' }, 'Most successful'));
    if (!best) {
      card.append(h('p.small.muted.cap-best-empty', scoped.length
        ? `No ${scopeLabel()} captain here has led in ${threshold} or more matches, so there is no fair pick.`
        : 'No captaincy records match these filters.'));
    } else {
      const ids = selected().list.map((c) => c.key);
      const inCompare = ids.includes(best.key);
      const next = pool.slice(1, 3);
      card.append(
        h('div.cap-best-head',
          h('div.cap-best-name', nameNode(best)),
          h('div.cap-best-pct', h('span.cap-best-num', `${fmt.n(best.win, 1)}%`), h('span.tiny.muted', 'win rate'))),
        h('p.small.cap-best-line', `Won ${best.won} of ${best.played} ${matchNoun(best, best.played)} ${captainOf(best)}, ${spanText(best)}.`),
        results(best),
        h('p.tiny.muted.cap-best-foot', pool.length === 1
          ? `The only captain with ${threshold} or more matches in these filters.`
          : `Highest win rate among ${pool.length} captains with ${threshold} or more matches in these filters.`,
          next.length ? ` Next: ${next.map((c) => `${c.name} ${fmt.n(c.win, 1)}% of ${c.played}`).join('; ')}.` : ''),
        h('div', h('button.btn.sm', {
          type: 'button', 'data-fk': 'best-add', 'aria-pressed': String(inCompare),
          disabled: !inCompare && ids.length >= MAX_COMPARE,
          title: !inCompare && ids.length >= MAX_COMPARE ? 'The comparison already holds four captains' : null,
          onclick: () => toggle(best, !inCompare),
        }, inCompare ? 'In the comparison' : 'Add to comparison')));
    }

    const flagged = scoped.filter((c) => c.flag).length;
    const notes = h('section.panel.cap-notes', { 'aria-labelledby': 'cap-notes-title' },
      h('div.eyebrow', { id: 'cap-notes-title' }, 'Reading these records'),
      h('ul.small',
        h('li', 'Win rate is wins divided by matches played, as the source lists them. Draws, ties and no-results all count as not won.'),
        h('li', 'Test figures are added up from the source’s series-by-series tables. ODI, T20I and franchise figures are each captain’s listed totals.'),
        st.level === 'franchise' ? h('li', 'A franchise record covers every team the captain led in that competition. The source does not split it by team.') : null,
        h('li', 'A dash means the source leaves that count blank. It is not a zero.'),
        flagged ? h('li', `${flagged} ${plural(flagged, 'record', 'records')} in these filters ${plural(flagged, 'does', 'do')} not add up in the source. They are marked “Totals off” and left as published.`) : null),
      h('p.tiny.faint', 'Source: Wikipedia captaincy lists (CC BY-SA 4.0). Names link to the player’s page: a ball-by-ball profile where Cricsheet holds enough of their deliveries, otherwise their career record. A name the list links to no article stays unlinked.'));
    insightsEl.append(card, notes);
  }

  function nameNode(c) {
    const href = playerHref(c.id, c.wiki);
    return href ? h('a', { href }, c.name) : h('span', c.name);
  }

  // ------------------------------------------------------------- results
  function renderResults() {
    keepFocus(resultsEl, drawResults);
  }

  function drawResults() {
    clear(resultsEl);
    rowChecks.clear();
    const { scoped, shown } = filtered();
    const sort = parseSort(st.sort);
    const val = SORTS[sort.key].val;
    shown.sort((a, b) => {
      const x = val(a), y = val(b);
      if (x == null && y == null) return (b.played ?? -1) - (a.played ?? -1);
      if (x == null) return 1;
      if (y == null) return -1;
      const d = typeof x === 'string' ? x.localeCompare(y) : x - y;
      return d * sort.dir || (b.played ?? -1) - (a.played ?? -1) || a.name.localeCompare(b.name);
    });

    const summary = h('p.small.muted.cap-summary', { 'aria-live': 'polite' },
      `Showing ${shown.length} of ${scoped.length} ${scopeLabel()} captaincy ${plural(scoped.length, 'record', 'records')}`,
      st.min > 1 ? ` with ${st.min} or more matches` : '',
      st.q.trim() ? ` matching “${st.q.trim()}”` : '',
      st.level === 'franchise' ? '. Each record is one captain in one competition, across every team they led.'
        : '. Each record is one captain for one side in one format.');
    resultsEl.append(h('div.card-head.cap-results-head',
      h('div', h('h2.display', { id: 'cap-results-title', tabindex: '-1' }, 'Leaderboard'), summary),
      shown.length ? legend(shown.some((c) => c.played != null && c.resultSum < c.played)) : null));

    const body = h('div.card-pad');
    resultsEl.append(body);

    if (!shown.length) {
      body.append(emptyState(scoped));
      return;
    }

    const show = {
      format: new Set(shown.map((c) => c.fmtLabel)).size > 1,
      drawn: shown.some((c) => c.drawn != null),
      tied: shown.some((c) => c.tied != null),
      nr: shown.some((c) => c.nr != null),
    };
    const ids = selected().list.map((c) => c.key);
    const cols = [
      ['name', 'Captain'],
      ['team', st.level === 'franchise' ? 'Franchises' : 'Team'],
      show.format ? ['format', st.level === 'franchise' ? 'League' : 'Format'] : null,
      ['span', 'Span'],
      ['played', 'P', 'r', 'Matches played'],
      ...RESULTS.filter(([k]) => k === 'won' || k === 'lost' || show[k]).map(([k, s, long]) => [k, s, 'r', long]),
      ['win', 'Win %', 'r', 'Win rate'],
    ].filter(Boolean);

    const th = ([k, label, cls, long]) => {
      const active = sort.key === k;
      return h('th', { class: cls || '', scope: 'col', 'aria-sort': active ? (sort.dir < 0 ? 'descending' : 'ascending') : null },
        h('button', {
          type: 'button', 'data-fk': `sort-${k}`, title: `Sort by ${(long || label).toLowerCase()}`,
          onclick: () => {
            const dir = active ? -sort.dir : SORTS[k].dir;
            st.sort = sortString(k, dir);
            syncUrl();
            renderResults();
          },
        }, long && long !== label && label.length <= 2
          ? [h('span', { 'aria-hidden': 'true' }, label), h('span.sr-only', long)] : label));
    };

    const visible = shown.slice(0, limit);
    const table = h('table.data.cap-table',
      h('caption.sr-only', `${scopeLabel()} captains. Column headers sort the table.`),
      h('thead', h('tr',
        h('th.cap-check', { scope: 'col' }, h('span.sr-only', 'Compare')),
        cols.map(th),
        h('th.cap-bar-col', { scope: 'col' }, 'Results'))),
      h('tbody', visible.map((c) => row(c, ids.includes(c.key), show, cols))));
    body.append(h('div.table-wrap', table));
    if (shown.length > limit) {
      const left = shown.length - limit;
      body.append(h('div.cap-more', h('button.btn.sm', {
        type: 'button', 'data-fk': 'more',
        onclick: () => { limit += PAGE_ROWS; renderResults(); },
      }, `Show ${Math.min(PAGE_ROWS, left)} more (${left} left)`)));
    }
  }

  function row(c, isSel, show, cols) {
    const check = h('input', {
      type: 'checkbox', checked: isSel, 'data-fk': `chk-${c.key}`,
      'aria-label': `Compare ${c.name}, ${teamText(c)}, ${scopeTitle(c)}`,
      onchange: (e) => {
        if (!toggle(c, e.target.checked)) e.target.checked = !e.target.checked;
      },
    });
    const tr = h('tr', { class: isSel ? 'is-selected' : '' },
      h('td.cap-check', check),
      h('td.cap-name',
        h('div.cap-name-line', nameNode(c),
          c.flag ? tooltip(h('span.badge.bad.cap-flag', { tabindex: '0', 'aria-label': `Totals off: ${c.flag}` }, 'Totals off'), c.flag) : null),
      ),
      h('td.small.cap-team', { title: c.teams.length > 2 ? teamText(c) : null }, c.teams.length === 1 ? teamLabel(c.teams[0], { size: 16 }) : teamText(c, 2)),
      show.format ? h('td.small', c.fmtLabel) : null,
      h('td.small.cap-span', spanText(c)),
      h('td.r', fmt.n(c.played)),
      RESULTS.filter(([k]) => k === 'won' || k === 'lost' || show[k]).map(([k]) => h('td.r', fmt.n(c[k]))),
      h('td.r.cap-win', h('strong', c.win == null ? '–' : fmt.n(c.win, 1))),
      h('td.cap-bar-col', results(c, 'sm')));
    rowChecks.set(c.key, { check, tr });
    return tr;
  }

  function emptyState(scoped) {
    const box = h('div.cap-empty');
    if (!scoped.length) {
      if (st.level === 'franchise' && !all.some((c) => c.level === 'franchise' && c.gender === st.g)) {
        box.append(h('p', h('strong', 'No women’s franchise records. '),
          'The captaincy lists used here cover men’s franchise competitions only.'),
        h('button.btn.sm', { type: 'button', onclick: () => change({ g: 'male', team: '', comp: '' }, 'all') }, 'Show men’s franchise captains'));
      } else if (st.team) {
        box.append(h('p', h('strong', `No records for ${st.team}. `), 'There are no captaincy records for that team in these filters.'),
          h('button.btn.sm', { type: 'button', onclick: () => change({ team: '' }, 'all') }, 'Show every team'));
      } else {
        box.append(h('p', h('strong', 'No records. '), 'There are no captaincy records for these filters.'),
          h('button.btn.sm', { type: 'button', onclick: () => change({ level: DEFAULTS.level, g: DEFAULTS.g, f: DEFAULTS.f, comp: '', team: '' }, 'all') }, 'Reset filters'));
      }
      return box;
    }
    const q = st.q.trim();
    const most = Math.max(...scoped.map((c) => c.played ?? 0));
    box.append(h('p', h('strong', 'No captain matches. '),
      q ? `Nobody in these filters matches “${q}”${st.min > 1 ? ` with ${st.min} or more matches` : ''}.`
        : `No captain here has led in ${st.min} or more matches. The most is ${most}.`));
    const actions = h('div.row');
    if (q) actions.append(h('button.btn.sm', { type: 'button', onclick: () => { change({ q: '' }, 'all'); document.getElementById('cap-q')?.focus(); } }, 'Clear the search'));
    if (st.min > 1) actions.append(h('button.btn.sm', { type: 'button', onclick: () => change({ min: 1 }, 'all') }, 'Include every captain'));
    box.append(actions);
    return box;
  }

  // ---------------------------------------------------------- comparison
  function toggle(c, on) {
    const keys = selected().list.map((x) => x.key);
    if (on) {
      if (keys.includes(c.key)) return true;
      if (keys.length >= MAX_COMPARE) {
        announce(`The comparison holds four captains. Remove one before adding ${c.name}.`);
        flashLimit();
        return false;
      }
      keys.push(c.key);
      announce(`${c.name} added to the comparison, ${keys.length} of ${MAX_COMPARE}.`);
    } else {
      const i = keys.indexOf(c.key);
      if (i < 0) return true;
      keys.splice(i, 1);
      announce(`${c.name} removed from the comparison, ${keys.length} of ${MAX_COMPARE}.`);
    }
    setIds(keys);
    syncChecks();
    renderCompare();
    keepFocus(insightsEl, renderInsights);
    updateTray();
    return true;
  }

  function flashLimit() {
    const el = compareEl.querySelector('.cap-count');
    if (!el) return;
    el.classList.remove('cap-flash');
    void el.offsetWidth;
    el.classList.add('cap-flash');
  }

  function syncChecks() {
    const keys = new Set(selected().list.map((c) => c.key));
    for (const [k, { check, tr }] of rowChecks) {
      check.checked = keys.has(k);
      tr.classList.toggle('is-selected', keys.has(k));
    }
  }

  function renderCompare() {
    const { list, missing, extra } = selected();
    clear(compareEl);
    compareEl.hidden = !list.length && !missing;
    if (compareEl.hidden) { cardCache.clear(); return; }
    const formats = new Set(list.map((c) => (c.level === 'franchise' ? 'T20' : c.format)));
    compareEl.append(h('div.card-head.cap-compare-head',
      h('div', h('h2.display', { id: 'cap-compare-title', tabindex: '-1' }, 'Side by side'),
        h('p.small.muted.cap-count', list.length
          ? `${list.length} of ${MAX_COMPARE} captains. Tick more in the leaderboard, or remove one here.`
          : 'Tick captains in the leaderboard to compare them.')),
      list.length ? h('div.row', legend(list.some((c) => c.played != null && c.resultSum < c.played)),
        h('button.btn.sm.ghost', { type: 'button', onclick: clearAll }, 'Clear all')) : null));
    const body = h('div.card-pad.stack');
    compareEl.append(body);
    if (missing || extra) {
      body.append(h('div.notice', h('div', [
        missing ? `${missing} ${plural(missing, 'captain', 'captains')} in this link ${plural(missing, 'is', 'are')} not in the current records and ${plural(missing, 'was', 'were')} left out.` : '',
        extra ? ` Only the first ${MAX_COMPARE} captains in the link are shown.` : '',
      ].join(' ').trim())));
    }
    if (!list.length) return;
    const cards = h('div.cap-cards');
    const keep = new Set(list.map((c) => c.key));
    for (const k of cardCache.keys()) if (!keep.has(k)) cardCache.delete(k);
    list.forEach((c, i) => {
      if (!cardCache.has(c.key)) cardCache.set(c.key, compareCard(c));
      const card = cardCache.get(c.key);
      card.querySelector('.cap-remove').dataset.idx = String(i);
      cards.append(card);
    });
    body.append(cards);
    if (formats.size > 1) {
      body.append(h('p.small.muted', 'These records come from different formats. Draws only happen in Tests, so win rates are not like for like.'));
    }
    body.append(h('div.notice.info', h('div',
      h('strong', 'Captain or not, the playing figures are the same. '),
      'Each player’s batting and bowling above covers all their matches in that format. Splitting it into matches as captain and matches not as captain is not available in the source data: the captaincy lists give totals, not match-by-match records, and the ball-by-ball data does not name the captain.')));
  }

  function clearAll() {
    setIds([]);
    syncChecks();
    renderCompare();
    keepFocus(insightsEl, renderInsights);
    updateTray();
    announce('Comparison cleared.');
    document.getElementById('cap-results-title')?.focus?.();
  }

  function removeFromCard(c, idx) {
    toggle(c, false);
    const btns = compareEl.querySelectorAll('.cap-remove');
    const target = btns[Math.min(idx, btns.length - 1)];
    if (target) target.focus();
    else document.getElementById('cap-results-title')?.focus?.();
  }

  function compareCard(c) {
    const colour = data.teamColour(c.teams[0] || c.team);
    const remove = h('button.icon-btn.cap-remove', {
      type: 'button', 'aria-label': `Remove ${c.name} from the comparison`,
      onclick: (e) => removeFromCard(c, Number(e.currentTarget.dataset.idx || 0)),
    }, h('span', { 'aria-hidden': 'true' }, '×'));
    const winPct = c.win == null ? null : Math.max(0, Math.min(100, c.win));
    const flags = h('ul.cap-flags.tiny');
    if (c.flag) flags.append(h('li', c.flag));
    const own = h('div.cap-own', h('div.eyebrow', `Own record in ${c.level === 'franchise' ? 'the ' + c.fmtLabel : c.format + 's'}`));
    const card = h('article.cap-card.fade-in', { style: { '--tc': colour }, 'aria-label': `${c.name}, ${scopeTitle(c)}` },
      h('header.cap-card-head',
        h('span.avatar', { 'aria-hidden': 'true' }, initials(c.name)),
        h('div.cap-card-title', h('h3', nameNode(c)), h('div.small.muted', `${teamText(c)} · ${scopeTitle(c)}`)),
        remove),
      h('div.cap-win',
        h('div', h('div.cap-win-num', winPct == null ? '–' : `${fmt.n(c.win, 1)}%`),
          h('div.small.muted', c.won == null ? `${fmt.n(c.played)} ${matchNoun(c, c.played)}, wins not recorded`
            : `won ${c.won} of ${c.played} ${matchNoun(c, c.played)}`)),
        h('div.meter', { role: 'img', 'aria-label': winPct == null ? 'Win rate not recorded' : `Win rate ${fmt.n(c.win, 1)} per cent` },
          winPct == null ? null : h('span', { style: { width: `${winPct}%` } }))),
      results(c),
      h('dl.cap-rec',
        [['played', 'Played'], ...RESULTS.map(([k, , long]) => [k, long])].map(([k, l]) =>
          h('div', h('dt', l), h('dd', fmt.n(c[k]))))),
      h('div.small', h('span.muted', 'Span '), spanText(c),
        c.first != null && c.last != null ? h('span.muted', ` · ${c.last - c.first + 1} ${plural(c.last - c.first + 1, 'calendar year', 'calendar years')}`) : null),
      own,
      h('div.cap-source.stack-s', flags,
        h('div.tiny.faint', 'Source: ', h('a', { href: wikiUrl(c.source), rel: 'noopener', target: '_blank' }, c.source))));
    if (!c.flag) flags.hidden = true;
    fillOwn(c, own, flags);
    return card;
  }

  async function fillOwn(c, own, flags) {
    if (!c.hasProfile) {
      await fillCareer(c, own);
      return;
    }
    const loading = h('div.stack-s', { 'aria-busy': 'true' },
      h('div.skeleton', { style: { height: '14px', width: '70%' } }),
      h('div.skeleton', { style: { height: '56px' } }));
    own.append(loading);
    let p;
    try {
      p = await data.player(c.id);
    } catch (err) {
      loading.remove();
      own.append(h('p.small.cap-err', 'The player profile could not load.'),
        h('a.small', { href: playerHref(c.id) }, 'Try the full profile'));
      return;
    }
    loading.remove();
    // Source flags held only in the profile copy of the captaincy record.
    const rec = (p.captaincy || []).find((x) => x.level === c.level && x.format === c.format
      && x.country_or_team === c.team && (x.competition || '') === c.comp);
    if (rec) {
      const extra = [];
      for (const n of String(rec.notes || '').split(';').map((x) => x.trim()).filter(Boolean)) if (NOTE_TEXT[n]) extra.push(NOTE_TEXT[n]);
      if (rec.page_total === 'mismatch') extra.push(`The source page’s own totals disagree with its rows${rec.page_total_detail ? ` (${rec.page_total_detail})` : ''}.`);
      if (rec.ongoing === '1') extra.push('Listed as the current captain in the source.');
      for (const t of extra) flags.append(h('li', t));
      if (extra.length) flags.hidden = false;
    }
    const sc = c.scopeKey ? p.scopes?.[c.scopeKey] : null;
    if (sc) {
      const seasons = sc.seasons || [];
      const years = seasons.map((s) => s.y).filter(Number.isFinite);
      const matches = seasons.reduce((a, s) => a + (s.m || 0), 0);
      const y0 = Math.min(...years), y1 = Math.max(...years);
      own.append(h('div.tiny.muted', 'Ball by ball, Cricsheet',
        years.length ? `, ${y0 === y1 ? y0 : `${y0}–${y1}`}` : '', matches ? ` · ${matches} ${plural(matches, 'match', 'matches')}` : ''));
      const bat = sc.batting, bowl = sc.bowling;
      const line = (label, value, sample) => h('div', h('dt', label), h('dd', h('span.num', value), sample ? h('span.tiny.faint', ` ${sample}`) : null));
      const dl = h('dl.cap-own-list');
      if (bat) {
        dl.append(line('Batting average', fmt.avg(bat.avg), `${fmt.n(bat.runs)} runs, ${fmt.n(bat.outs)} outs`),
          line('Strike rate', fmt.sr(bat.sr), `${fmt.n(bat.balls)} balls`));
      } else {
        dl.append(line('Batting', '–', 'too few balls faced for a profile'));
      }
      if (bowl) {
        dl.append(line('Bowling average', fmt.avg(bowl.avg), `${fmt.n(bowl.wkts)} wkts`),
          line('Economy', bowl.econ == null ? '–' : bowl.econ.toFixed(2), `${fmt.n(bowl.balls)} balls`));
      } else {
        dl.append(line('Bowling', '–', 'too few balls bowled for a profile'));
      }
      own.append(dl);
    } else {
      own.append(h('p.small.muted', c.scopeKey
        ? 'No ball-by-ball profile in this format: too few balls in the archive.'
        : `This site has no ball-by-ball data for the ${c.comp || 'competition'}, so there is no playing record to show.`));
    }
    const k = c.careerKey ? p.career?.[c.careerKey] : null;
    if (k && k.matches) {
      const bits = [`${k.matches} ${plural(k.matches, c.format, c.format + 's')}`];
      if (k.runs != null) bits.push(`${fmt.n(k.runs)} runs${k.bat_avg != null ? ` at ${fmt.avg(k.bat_avg)}` : ''}`);
      if (k.wickets) bits.push(`${k.wickets} wickets${k.bowl_avg != null ? ` at ${fmt.avg(k.bowl_avg)}` : ''}`);
      own.append(h('p.tiny.muted.cap-career', h('span', 'Whole career, Wikipedia: '), bits.join(' · ')));
    }
    own.append(h('a.btn.sm.cap-profile', { href: playerHref(c.id) }, 'Full profile'));
  }

  /** A captain without a ball-by-ball profile: totals from the all-eras career list, when it covers the format. */
  async function fillCareer(c, own) {
    const sc = meta?.scopes?.find((s) => s.key === c.scopeKey);
    const what = c.level === 'franchise' ? `the ${c.fmtLabel}` : `${c.gender === 'female' ? 'women’s' : 'men’s'} ${c.format}s`;
    own.append(h('p.small.muted', !c.id ? 'Not matched to a player in Cricsheet’s ball-by-ball archive.'
      : sc?.years?.length ? `No ball-by-ball profile. Cricsheet’s record of ${what} starts in ${sc.years[0]}.` : 'No ball-by-ball profile in the archive.'));
    const histKey = c.level === 'international' && (c.format === 'Test' || c.format === 'ODI') ? c.scopeKey : null;
    if (histKey) {
      const loading = h('div.skeleton', { style: { height: '56px' }, 'aria-busy': 'true' });
      own.append(loading);
      let H = null;
      try { H = await data.historic(histKey); } catch (err) { /* reported below */ }
      loading.remove();
      if (!H) {
        own.append(h('p.small.cap-err', 'The career list could not load.'));
      } else {
        const ids = new Set(c.id ? [c.id] : []), titles = new Set(c.wiki ? [c.wiki] : []);
        for (const r of careerRows(H, ids, titles).filter((x) => x.country === c.team)) {
          const f = careerFigures(r);
          const line = (label, value, sample) => h('div', h('dt', label), h('dd', h('span.num', value), sample ? h('span.tiny.faint', ` ${sample}`) : null));
          own.append(h('div.tiny.muted', 'Career totals, Wikipedia',
            r.first ? `, ${r.first === r.last ? r.first : `${r.first}–${r.last}`}` : '',
            f.matches ? ` · ${f.matches} ${plural(f.matches, c.format, c.format + 's')}` : ''),
          h('dl.cap-own-list',
            line('Batting average', fmt.avg(f.avg), f.runs ? `${fmt.n(f.runs)} runs, ${fmt.n(r.outs)} outs` : 'no runs listed'),
            line('Bowling average', fmt.avg(f.bowlAvg), f.wkts ? `${fmt.n(f.wkts)} wkts` : 'no wickets listed')));
        }
      }
    }
    const href = playerHref(c.id, c.wiki);
    if (href) own.append(h('a.btn.sm.cap-profile', { href }, 'Career record'));
  }

  // ---------------------------------------------------------------- tray
  let compareVisible = true;
  function watchCompare() {
    observer?.disconnect();
    if (!('IntersectionObserver' in window)) return;
    observer = new IntersectionObserver((entries) => {
      compareVisible = entries.some((e) => e.isIntersecting);
      updateTray();
    }, { threshold: 0 });
    observer.observe(compareEl);
  }

  function updateTray() {
    const n = selected().list.length;
    const show = n > 0 && !compareVisible && !compareEl.hidden;
    tray.hidden = !show;
    page.classList.toggle('cap-has-tray', show);
    if (!show) return;
    clear(tray);
    tray.append(
      h('span.small', `${n} of ${MAX_COMPARE} selected`),
      h('button.btn.sm.primary', {
        type: 'button',
        onclick: () => {
          compareEl.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' });
          document.getElementById('cap-compare-title')?.focus({ preventScroll: true });
        },
      }, n > 1 ? 'Compare' : 'View'),
      h('button.btn.sm.ghost', { type: 'button', onclick: clearAll }, 'Clear'));
  }

  // ---------------------------------------------------------------- all
  function renderAll() {
    renderHero();
    renderCompare();
    keepFocus(filtersEl, renderFilters);
    renderInsights();
    renderResults();
    updateTray();
  }

  await load();
  if (all.length) persist();

  return {
    update(r) {
      const next = readQuery(r.query);
      if (JSON.stringify(writeQuery(next)) === JSON.stringify(writeQuery(st))) return;
      st = next;
      limit = PAGE_ROWS;
      if (!all.length) { load(); return; }
      renderAll();
      persist();
    },
    destroy() {
      destroyed = true;
      observer?.disconnect();
      observer = null;
    },
  };
}
