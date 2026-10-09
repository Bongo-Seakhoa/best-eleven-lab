// Player profile: who they are, what Wikipedia says they have done, and where
// the ball-by-ball record shows them strong or weak in each competition.
import { h, clear, fmt, initials } from '../ui/dom.js';
import { divergingBars, seasonChart, compareDots, fieldPlan, percentile, resultBar } from '../ui/charts.js';
import * as data from '../data.js';
import { setQuery } from '../app.js';

const ID_RE = /^[0-9a-f]{8}$/;
const FORMAT_RANK = { Test: 0, ODI: 1, T20I: 2 };
const NATIONAL_TAB = { Test: 'Tests', ODI: 'ODIs', T20I: 'T20Is' };
// These mirror src/best_eleven/model/profiles.py, which wrote the files.
const PHASES = {
  multi: ['New ball (overs 1-20)', 'Overs 21-80', 'Second new ball (80+)'],
  fifty: ['Powerplay (1-10)', 'Middle (11-40)', 'Death (41-50)'],
  t20: ['Powerplay (1-6)', 'Middle (7-15)', 'Death (16-20)'],
  hundred: ['Powerplay (1-25)', 'Middle (26-75)', 'Death (76-100)'],
};
const MIN_BALLS = { multi: 300, fifty: 150, t20: 90, hundred: 75 };
const MIN_MATCHUP = { multi: 60, fifty: 30, t20: 18, hundred: 15 };
const SIGNALS = {
  keeper: 'Edges caught behind', field: 'Caught in the field', boundary: 'Boundaries',
  rot: 'Ones, twos and threes', straight: 'Bowled and LBW', stumped: 'Stumpings',
};
const CAREER_ROWS = [
  ['Test', 'Test'], ['WTest', 'Test'], ['ODI', 'ODI'], ['WODI', 'ODI'], ['T20I', 'T20I'], ['WT20I', 'T20I'],
  ['WT20I_2', 'T20I, second team'], ['FC', 'First-class'], ['LA', 'List A'], ['T20', 'All T20s'],
];

// ---------------------------------------------------------------- helpers
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : '');
const num = (x) => x != null && Number.isFinite(x);
const dash = (x) => (x == null || x === '' ? '–' : String(x));
const pctText = (x) => (num(x) ? `${x.toFixed(1)}%` : '–');
const signed = (x) => fmt.signed(x, 1);
const plural = (k, one, many = `${one}s`) => `${fmt.n(k)} ${k === 1 ? one : many}`;
const sum = (rows, k) => rows.reduce((a, r) => a + (Number(r[k]) || 0), 0);
const valueClass = (v) => (!num(v) || Math.abs(v) < 0.05 ? '' : v > 0 ? 'pp-pos' : 'pp-neg');

function day(s) {
  if (!s) return '';
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(s) ? `${s}T00:00:00Z` : s);
  if (Number.isNaN(+d)) return s;
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
}

function wikiUrl(title) {
  return `https://en.wikipedia.org/wiki/${encodeURIComponent(title.replace(/ /g, '_')).replace(/%2F/g, '/')}`;
}

/** National side to show: the team they played for, unless that is a composite XI. */
function homeCountry(nat, country) {
  const listed = String(country || '').split(';').map((x) => x.trim()).filter(Boolean);
  const composite = (c) => /world xi/i.test(c);
  if (nat && !composite(nat)) return nat;
  return listed.find((c) => !composite(c)) || nat || '';
}

function coverage(sc) {
  const ss = sc.seasons || [];
  const played = ss.filter((x) => x.m > 0).map((x) => x.y);
  return { matches: sum(ss, 'm'), from: played.length ? Math.min(...played) : null, to: played.length ? Math.max(...played) : null };
}

const years = (a, b) => (a == null ? '' : a === b ? String(a) : `${a}–${b}`);

function statGrid(rows) {
  return h('div.stat-grid.pp-stats', rows.map(([label, value]) =>
    h('div.stat', h('div.stat-value', value), h('div.stat-label', label))));
}

function card(id, title, { sub, action } = {}, ...body) {
  const hid = `pp-h-${id}`;
  return h('section.card.pp-card', { 'aria-labelledby': hid },
    h('div.card-head.pp-card-head',
      h('div', h('h2.display.pp-h2', { id: hid }, title), sub ? h('p.small.muted.pp-card-sub', sub) : null),
      action || null),
    h('div.card-pad', ...body));
}

/** A titled chart or table inside a tab panel. */
function block(title, sub, ...body) {
  return h('div.pp-chart', h('h5.pp-h5', title), sub ? h('p.tiny.muted.pp-sub', sub) : null, ...body);
}

const scroller = (el, extra = '') => h(`div.pp-scroll${extra}`, el);
const empty = (text) => h('p.small.muted.pp-empty', text);

// ------------------------------------------------------------------ view
export async function mount(root, route) {
  const id = String(route.arg || '').trim().toLowerCase();
  const page = h('div.page.player-page');
  root.append(page);
  const prevTitle = document.title;
  let ctl = null;

  const view = {
    update(r) {
      if (!ctl) return;
      const key = r.query.get('s');
      ctl.select(key && ctl.has(key) ? key : ctl.first, { fromUrl: true });
    },
    destroy() { document.title = prevTitle; },
  };

  if (!ID_RE.test(id)) {
    notFound(page, route.arg);
    return view;
  }

  async function load() {
    clear(page);
    page.append(skeleton());
    let p, meta = null;
    try {
      [p, meta] = await Promise.all([data.player(id), data.meta().catch(() => null)]);
    } catch (err) {
      if (!page.isConnected) return;
      await missing(page, id, err, load);
      return;
    }
    if (!page.isConnected) return;
    clear(page);
    document.title = `${p.name} · Best Eleven Lab`;
    const scopes = orderScopes(p, meta);
    const female = scopes.some((s) => (s.info?.gender || (s.key.includes('women') ? 'female' : '')) === 'female');
    page.append(hero(p, scopes, meta));
    page.append(careerCard(p, female));
    if (scopes.length) {
      const tabs = scopeTabs(p, scopes, meta, route.query.get('s'));
      ctl = tabs.ctl;
      page.append(tabs.el);
    }
    page.append(captaincyCard(p));
    page.append(squadsCard(p));
  }

  await load();
  return view;
}

function skeleton() {
  return h('div.pp-loading', { 'aria-busy': 'true' },
    h('span.sr-only', { role: 'status' }, 'Loading player profile'),
    h('div.pp-hero',
      h('div.skeleton.pp-avatar-skel'),
      h('div.stack-s', h('div.skeleton', { style: { height: '12px', width: '180px' } }),
        h('div.skeleton', { style: { height: '44px', width: 'min(380px, 80%)' } }),
        h('div.skeleton', { style: { height: '22px', width: 'min(460px, 90%)' } }))),
    h('div.skeleton', { style: { height: '160px', borderRadius: 'var(--r-l)' } }),
    h('div.skeleton', { style: { height: '520px', borderRadius: 'var(--r-l)' } }));
}

function notFound(page, arg) {
  const shown = String(arg || '').slice(0, 40);
  clear(page);
  page.append(h('div.pp-missing.fade-in',
    h('div.eyebrow', 'Player profile'),
    h('h1.display', 'Player not found'),
    h('p.lede', shown ? `No player in the archive has the id “${shown}”. Profile links use Cricsheet’s eight-character player ids.`
      : 'This link does not name a player.'),
    h('div.row', h('a.btn.primary', { href: '#/players' }, 'Browse all players'), h('a.btn', { href: '#/' }, 'Pick an XI'))));
}

async function missing(page, id, err, retry) {
  const is404 = /HTTP 404/.test(String(err?.message || ''));
  let entry = null, meta = null;
  if (is404) {
    try {
      const [idx, m] = await Promise.all([data.playerIndex(), data.meta().catch(() => null)]);
      entry = idx.find((e) => e.id === id) || null;
      meta = m;
    } catch (e) { /* fall through to not found */ }
  }
  if (!page.isConnected) return;
  clear(page);
  if (entry) {
    const labels = (entry.s || []).map((k) => meta?.scopes?.find((x) => x.key === k)?.label || k);
    page.append(h('section.card.card-pad.pp-thin.fade-in',
      h('div.eyebrow', [homeCountry(entry.c, ''), cap(entry.r)].filter(Boolean).join(' · ') || 'Player profile'),
      h('h1.display', entry.n),
      entry.f && entry.f !== entry.n ? h('p.lede.pp-fullname', entry.f) : null,
      h('p', 'There is not enough ball-by-ball evidence for a full profile of this player yet.'),
      labels.length ? h('p.small.muted', `Appears in: ${labels.join(', ')}.`) : null,
      h('div.row', h('a.btn.primary', { href: '#/players' }, 'Browse all players'))));
    document.title = `${entry.n} · Best Eleven Lab`;
    return;
  }
  if (is404) { notFound(page, id); return; }
  page.append(h('div.notice.error', { role: 'alert' }, h('div',
    h('strong', 'This profile could not load. '), String(err?.message || err),
    h('div.row.mt', h('button.btn.sm', { type: 'button', onclick: retry }, 'Try again'),
      h('a.btn.sm.ghost', { href: '#/players' }, 'Browse all players')))));
}

function orderScopes(p, meta) {
  const size = (sc) => (sc.batting?.balls || 0) + (sc.bowling?.balls || 0);
  return Object.entries(p.scopes || {})
    .map(([key, sc]) => ({ key, sc, info: meta?.scopes?.find((x) => x.key === key) || null }))
    .sort((a, b) => {
      const na = a.sc.tier === 'national', nb = b.sc.tier === 'national';
      if (na !== nb) return na ? -1 : 1;
      if (na) return (FORMAT_RANK[a.sc.format] ?? 9) - (FORMAT_RANK[b.sc.format] ?? 9);
      return size(b.sc) - size(a.sc);
    });
}

const tabLabel = (s) => (s.sc.tier === 'national' ? NATIONAL_TAB[s.sc.format] || s.sc.label : s.info?.short || s.sc.label);

function groupOf(key, meta) {
  const groups = meta?.model?.groups || {};
  return Object.values(groups).find((g) => (g.scopes || []).includes(key)) || null;
}

function statusOf(sc) {
  const st = sc.status || {};
  if (st.squad) return { text: 'In current squad', cls: '.good' };
  if (st.retired) return { text: 'Retired', cls: '.pp-retired' };
  if (st.active) return { text: 'Active', cls: '' };
  return null;
}

// ------------------------------------------------------------------ hero
function hero(p, scopes, meta) {
  const country = homeCountry(p.nat, p.country);
  const avatar = h('span.avatar.pp-avatar', { 'aria-hidden': 'true' }, initials(p.name));
  if (country) avatar.style.setProperty('--tc', data.teamColour(country));

  const cov = scopes.map((s) => coverage(s.sc));
  const total = sum(cov, 'matches');
  const from = Math.min(...cov.map((c) => c.from ?? Infinity));
  const to = Math.max(...cov.map((c) => c.to ?? -Infinity));
  const record = scopes.length
    ? `Ball-by-ball record: ${plural(total, 'match', 'matches')} in ${plural(scopes.length, 'competition')}${Number.isFinite(from) ? `, ${years(from, to)}` : ''}.`
    : 'No competition in the archive holds enough of their deliveries for a profile.';

  const chips = [];
  if (p.hand === 'right' || p.hand === 'left') chips.push(h('span.pp-chip', `${cap(p.hand)}-hand bat`));
  const b = p.bowl || {};
  if (b.source === 'wikipedia' && b.label) chips.push(h('span.pp-chip', b.label));
  else if (b.source === 'wikipedia' && b.family) chips.push(h('span.pp-chip', `Bowls ${b.family}`));
  else if (b.source === 'model' && b.family) {
    chips.push(h('span.pp-chip', `Bowls ${b.family}`,
      h('span.badge.model', { title: 'Wikipedia gives no bowling style; pace or spin is inferred from the ball-by-ball record.' }, 'style inferred')));
  }
  if (p.dob) {
    const last = scopes.map((s) => s.sc.lastPlayed).filter(Boolean).sort().pop();
    const end = new Date(meta?.dataEnd || Date.now());
    // Age only for recent players: the sources carry no date of death.
    const recent = last && (end - new Date(last)) / 864e5 < 3 * 365.25;
    const age = recent ? fmt.age(p.dob) : null;
    chips.push(h('span.pp-chip', `Born ${day(p.dob)}${age != null ? `, age ${age}` : ''}`));
  }
  if (p.wiki) {
    chips.push(h('a.pp-chip.pp-link', { href: wikiUrl(p.wiki), rel: 'noopener' }, 'Wikipedia',
      h('span.sr-only', `: ${p.wiki}`)));
  }

  const status = scopes.map((s) => {
    const st = statusOf(s.sc);
    return st ? h(`span.badge${st.cls}`, `${tabLabel(s)}: ${st.text.toLowerCase()}`) : null;
  }).filter(Boolean);

  return h('header.pp-hero.fade-in', avatar,
    h('div.pp-hero-text',
      h('div.eyebrow', [country, cap(p.role)].filter(Boolean).join(' · ') || 'Player profile'),
      h('h1.display.pp-name', p.name),
      p.fullName && p.fullName !== p.name ? h('p.pp-fullname', p.fullName) : null,
      h('p.lede.pp-record', record),
      chips.length ? h('div.pp-chips', chips) : null,
      status.length ? h('div.pp-chips.pp-status', { role: 'list', 'aria-label': 'Status by competition' },
        status.map((x) => { x.setAttribute('role', 'listitem'); return x; })) : null));
}

// --------------------------------------------------------- career summary
function careerCard(p, female) {
  const c = p.career || {};
  const known = new Set(CAREER_ROWS.map(([k]) => k));
  const rows = [
    ...CAREER_ROWS.filter(([k]) => c[k]).map(([k, label]) => [label, c[k]]),
    ...Object.keys(c).filter((k) => !known.has(k)).map((k) => [`Other${c[k]?.label ? ` (${c[k].label})` : ''}`, c[k]]),
  ];
  const sub = 'Full-career figures from the Wikipedia infobox. They count matches outside Cricsheet’s ball-by-ball coverage'
    + (female ? ', such as older and domestic games' : ', such as older and domestic games and men’s matches involving Afghanistan, which Cricsheet withholds')
    + ', so they will not always match the competition tabs below.';
  if (!rows.length) {
    return card('career', 'Career at a glance', {},
      empty(p.wiki ? 'The linked Wikipedia article has no career statistics we could read.'
        : 'No Wikipedia article is linked to this player, so there is no full-career summary.'));
  }
  const ctst = (r) => (r.catches == null ? '–' : r.stumpings != null && r.stumpings !== 0 ? `${r.catches} / ${r.stumpings}` : String(r.catches));
  const table = h('table.data.pp-career', { 'aria-label': 'Career figures by format, from Wikipedia' },
    h('thead', h('tr',
      h('th', { scope: 'col' }, 'Format'), h('th.r', { scope: 'col' }, 'Matches'), h('th.r', { scope: 'col' }, 'Runs'),
      h('th.r', { scope: 'col' }, 'Bat avg'), h('th.r', { scope: 'col' }, '100s / 50s'), h('th.r', { scope: 'col' }, 'Top score'),
      h('th.r', { scope: 'col' }, 'Wickets'), h('th.r', { scope: 'col' }, 'Bowl avg'), h('th.r', { scope: 'col' }, 'Best'),
      h('th.r', { scope: 'col', title: 'Catches / stumpings' }, 'Ct / St'))),
    h('tbody', rows.map(([label, r]) => h('tr',
      h('th', { scope: 'row' }, label),
      h('td.r', fmt.n(r.matches)), h('td.r', fmt.n(r.runs)), h('td.r', fmt.avg(r.bat_avg)),
      h('td.r', r.hundreds == null && r.fifties == null ? '–' : `${dash(r.hundreds)} / ${dash(r.fifties)}`),
      h('td.r', r.top_score == null ? '–' : `${r.top_score}${r.not_out ? '*' : ''}`),
      h('td.r', fmt.n(r.wickets)), h('td.r', fmt.avg(r.bowl_avg)), h('td.r', dash(r.best)), h('td.r', ctst(r))))));
  return card('career', 'Career at a glance', { sub }, h('div.table-wrap', table),
    h('p.tiny.faint.pp-note', 'A dash means the infobox gives no figure. An asterisk on a top score means not out.'));
}

// ----------------------------------------------------------- scope tabs
function scopeTabs(p, scopes, meta, wanted) {
  const tablist = h('div.pp-tabs', { role: 'tablist', 'aria-label': 'Competitions' });
  const panel = h('div.pp-panel', { role: 'tabpanel', id: 'pp-panel', tabindex: '0' });
  const tabs = scopes.map((s) => {
    const cov = coverage(s.sc);
    return h('button.pp-tab', {
      type: 'button', role: 'tab', id: `pp-tab-${s.key}`, 'aria-controls': 'pp-panel', 'aria-selected': 'false', tabindex: '-1',
      onclick: () => ctl.select(s.key, { fromUser: true }),
    }, h('span.pp-tab-label', tabLabel(s)), h('span.pp-tab-sub', cov.matches ? plural(cov.matches, 'match', 'matches') : s.sc.label));
  });
  tablist.append(...tabs);
  tablist.addEventListener('keydown', (e) => {
    const i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    const j = e.key === 'ArrowRight' ? (i + 1) % tabs.length : e.key === 'ArrowLeft' ? (i - 1 + tabs.length) % tabs.length
      : e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : null;
    if (j == null) return;
    e.preventDefault();
    ctl.select(scopes[j].key, { fromUser: true, focus: true });
  });

  let current = null;
  // Keep the active tab visible inside the scrolling strip without moving the page.
  const reveal = (tab) => {
    const l = tab.offsetLeft, r = l + tab.offsetWidth;
    if (l < tablist.scrollLeft) tablist.scrollLeft = l - 16;
    else if (r > tablist.scrollLeft + tablist.clientWidth) tablist.scrollLeft = r - tablist.clientWidth + 16;
  };
  const ctl = {
    first: scopes[0].key,
    has: (key) => scopes.some((s) => s.key === key),
    select(key, { fromUser = false, focus = false } = {}) {
      const i = scopes.findIndex((s) => s.key === key);
      if (i < 0) return;
      const tab = tabs[i];
      if (key !== current) {
        current = key;
        tabs.forEach((t, k) => { t.setAttribute('aria-selected', String(k === i)); t.tabIndex = k === i ? 0 : -1; });
        panel.setAttribute('aria-labelledby', tab.id);
        clear(panel);
        panel.append(renderScope(scopes[i], p, meta));
        if (fromUser) setQuery(key === ctl.first ? {} : { s: key });
      }
      reveal(tab);
      if (focus) tab.focus();
    },
  };
  const start = wanted && ctl.has(wanted) ? wanted : ctl.first;
  if (wanted && !ctl.has(wanted)) setQuery({});
  const el = card('scopes', 'By competition', {
    sub: 'Every delivery Cricsheet holds for this player, split by competition. Ratings compare them with others in the same competition.',
  }, h('div.pp-tabs-wrap', tablist), panel);
  el.classList.add('pp-scopes');
  ctl.select(start);
  // The strip can only measure itself once the card is in the page.
  requestAnimationFrame(() => reveal(tabs[scopes.findIndex((s) => s.key === current)]));
  return { el, ctl };
}

function renderScope(s, p, meta) {
  const { key, sc } = s;
  const group = groupOf(key, meta);
  const unadjusted = group?.adjusted === false;
  const cov = coverage(sc);
  const wrap = h('div.pp-scope.fade-in');
  const facts = [
    cov.matches ? `${plural(cov.matches, 'match', 'matches')} with ball-by-ball data${cov.from != null ? `, ${years(cov.from, cov.to)}` : ''}` : null,
    sc.lastPlayed ? `last played ${day(sc.lastPlayed)}` : null,
  ].filter(Boolean).join(' · ');
  wrap.append(h('div.pp-scope-head', h('h3.display.pp-h3', sc.label), facts ? h('p.small.muted', cap(facts)) : null));
  if (unadjusted) {
    wrap.append(h('div.notice', h('div', h('strong', 'Not adjusted for opposition. '),
      `Only ${plural(group.matches, 'match', 'matches')} in this format have ball-by-ball data, too few to separate a player from the opponents they faced. Values here compare with the average across those matches.`)));
  }
  wrap.append(ratingStrip(s, group));
  const seasons = seasonsBlock(s, p);
  if (seasons) wrap.append(seasons);
  const bat = sc.batting ? battingBlock(s, p) : null;
  const bowl = sc.bowling ? bowlingBlock(s, p) : null;
  const bowlFirst = sc.bowling && (!sc.batting || sc.bowling.balls > sc.batting.balls);
  wrap.append(...(bowlFirst ? [bowl, bat] : [bat, bowl]).filter(Boolean));
  wrap.append(howToRead(s, group));
  return wrap;
}

// ---------------------------------------------------------- rating strip
function reference(s, group, who) {
  const { sc } = s;
  const opp = who === 'batter' ? 'facing the same bowlers' : 'bowling to the same batters';
  if (group?.adjusted === false) return `against the average ${who} across these matches, without an opposition adjustment`;
  if (sc.tier === 'national') return `against an average Full-Member ${who} ${opp} in the same phase, era and conditions`;
  const women = (s.info?.gender || '') === 'female' || s.key.includes('women') || ['wbbl', 'wpl', 'wcpl', 'hundred-w'].includes(s.key);
  return `against an average ${who} ${opp} in the same phase, era and conditions, on one scale shared by all the ${women ? 'women’s' : 'men’s'} leagues`;
}

function ratingCell(s, group, kind) {
  const { sc } = s;
  const fam = sc.family;
  const blk = kind === 'bat' ? sc.batting : sc.bowling;
  const pct = kind === 'bat' ? sc.batPct : sc.bowlPct;
  const title = kind === 'bat' ? 'Batting' : 'Bowling';
  const who = kind === 'bat' ? 'batter' : 'bowler';
  if (!blk) {
    return h('div.pp-rating.is-empty', h('div.eyebrow', title),
      h('p.small.muted', kind === 'bat'
        ? `No batting profile here: fewer than ${MIN_BALLS[fam]} balls faced.`
        : `No bowling profile here: fewer than ${MIN_BALLS[fam]} balls bowled.`));
  }
  return h('div.pp-rating',
    percentile(pct, `${title} percentile`),
    h('p.pp-runs', h('strong', { class: valueClass(blk.value) }, signed(blk.value)),
      ` runs ${kind === 'bat' ? 'added' : 'saved'} per 100 balls`),
    h('p.tiny.muted', `${kind === 'bat' ? 'Runs added' : 'Runs saved'} ${reference(s, group, who)}. The percentile ranks them among ${who}s with at least ${MIN_BALLS[fam]} balls ${kind === 'bat' ? 'faced' : 'bowled'} here.`));
}

function ratingStrip(s, group) {
  const { sc } = s;
  const ss = sc.seasons || [];
  const tracked = sc.tier === 'national' || !!s.info?.featured;
  const st = statusOf(sc);
  const ct = sum(ss, 'catches'), stp = sum(ss, 'stumpings');
  const facts = h('dl.pp-dl',
    h('div', h('dt', 'Status'), h('dd', st ? st.text : 'Not active')),
    h('div', h('dt', 'Captained'), h('dd', sc.captained > 0 ? plural(sc.captained, 'match', 'matches')
      : tracked ? 'None recorded' : 'Not tracked for this league')),
    h('div', h('dt', 'Last played'), h('dd', sc.lastPlayed ? day(sc.lastPlayed) : '–')),
    h('div', h('dt', stp ? 'Catches / stumpings' : 'Catches'), h('dd', stp ? `${fmt.n(ct)} / ${fmt.n(stp)}` : fmt.n(ct))));

  const flags = [];
  const collect = (rows, area) => (rows || []).forEach((r) => { if (r.flag) flags.push({ ...r, area }); });
  collect(sc.batting?.vsBowling, 'Batting against');
  collect(sc.batting?.byPhase, 'Batting in');
  collect(sc.bowling?.vsHand, 'Bowling to');
  collect(sc.bowling?.vsPosition, 'Bowling to');
  collect(sc.bowling?.vsTempo, 'Bowling to');
  collect(sc.bowling?.byPhase, 'Bowling in');
  flags.sort((a, b) => (a.flag === b.flag ? Math.abs(b.z) - Math.abs(a.z) : a.flag === 'strength' ? -1 : 1));
  const standout = h('div.pp-standout',
    h('h4.pp-h4', 'What stands out'),
    flags.length
      ? h('ul.pp-flags', flags.map((f) => h('li',
        h(`span.badge${f.flag === 'strength' ? '.good' : '.bad'}`, cap(f.flag)),
        h('span', `${f.area} ${f.group.charAt(0).toLowerCase()}${f.group.slice(1)}`),
        h('span.tiny.muted', `${signed(f.value)} per 100 balls · ${plural(f.balls, 'ball')}`))))
      : h('p.small.muted', 'No split stands clearly apart from their own overall level.'),
    h('p.tiny.faint', 'Flags compare a split with the player’s own overall level, not with the average, so a strength can still sit below average.'));
  return h('div.pp-ratings', ratingCell(s, group, 'bat'), ratingCell(s, group, 'bowl'), facts, standout);
}

// ------------------------------------------------------------- seasons
function seasonsBlock(s, p) {
  const { sc } = s;
  const ss = (sc.seasons || []).slice().sort((a, b) => a.y - b.y);
  // Charts follow the profile blocks; odd overs from a part-timer are left to the year table.
  const kinds = [];
  if (sc.batting || (!sc.bowling && ss.some((x) => x.balls > 0))) kinds.push('bat');
  if (sc.bowling) kinds.push('bowl');
  if (!ss.length || !kinds.length) return null;
  let mode = kinds.includes('bowl') && (!sc.batting || (sc.bowling && sc.bowling.balls > sc.batting.balls)) ? 'bowl' : kinds[0];
  const holder = h('div.pp-season-chart');
  const note = h('p.tiny.muted.pp-sub');
  const buttons = kinds.map((k) => h('button', { type: 'button', 'aria-pressed': String(k === mode), onclick: () => { mode = k; draw(); } },
    k === 'bat' ? 'Batting' : 'Bowling'));
  function draw() {
    buttons.forEach((b, i) => b.setAttribute('aria-pressed', String(kinds[i] === mode)));
    clear(holder);
    if (mode === 'bat') {
      note.textContent = 'Bars show runs in each calendar year. The line shows runs added per 100 balls, pulled towards zero in thin seasons.';
      holder.append(seasonChart(ss.map((x) => ({ y: x.y, bar: x.runs, line: x.balls ? x.batValue : null })), {
        barLabel: 'runs', lineLabel: 'runs added per 100 balls', lineFmt: signed,
        label: `${p.name}: runs and runs added per 100 balls by year in ${sc.label}`,
      }));
    } else {
      note.textContent = 'Bars show wickets in each calendar year. The line shows runs saved per 100 balls, pulled towards zero in thin seasons.';
      holder.append(seasonChart(ss.map((x) => ({ y: x.y, bar: x.wkts, line: x.bowlBalls ? x.bowlValue : null })), {
        barLabel: 'wickets', lineLabel: 'runs saved per 100 balls', lineFmt: signed,
        barColour: 'var(--sky-soft)', lineColour: 'var(--sky)',
        label: `${p.name}: wickets and runs saved per 100 balls by year in ${sc.label}`,
      }));
    }
  }
  draw();
  const seg = kinds.length > 1 ? h('div.seg', { role: 'group', 'aria-label': 'Season chart shows' }, buttons) : null;
  return h('section.pp-block.pp-seasons', { 'aria-label': 'Season by season' },
    h('div.pp-block-head', h('h4.pp-h4', 'Season by season'), seg),
    note, holder, seasonTable(ss));
}

function seasonTable(ss) {
  const bat = ss.some((x) => x.balls > 0), bowl = ss.some((x) => x.bowlBalls > 0);
  const cols = [['Year'], ['Matches', 'r']];
  if (bat) cols.push(['Runs', 'r'], ['Avg', 'r'], ['SR', 'r'], ['100s / 50s', 'r'], ['Runs added', 'r', 'Per 100 balls']);
  if (bowl) cols.push(['Wkts', 'r'], ['Econ', 'r'], ['Bowl avg', 'r'], ['Runs saved', 'r', 'Per 100 balls']);
  cols.push(['Ct', 'r']);
  const rows = ss.slice().reverse().map((x) => h('tr',
    h('th', { scope: 'row' }, String(x.y)), h('td.r', fmt.n(x.m)),
    bat ? [h('td.r', x.balls ? fmt.n(x.runs) : '–'), h('td.r', fmt.avg(x.avg)), h('td.r', fmt.sr(x.sr)),
      h('td.r', x.balls ? `${x.h100} / ${x.h50}` : '–'), h('td.r', { class: valueClass(x.batValue) }, signed(x.batValue))] : null,
    bowl ? [h('td.r', x.bowlBalls ? fmt.n(x.wkts) : '–'), h('td.r', num(x.econ) ? x.econ.toFixed(2) : '–'), h('td.r', fmt.avg(x.bowlAvg)),
      h('td.r', { class: valueClass(x.bowlValue) }, signed(x.bowlValue))] : null,
    h('td.r', fmt.n(x.catches))));
  return h('details.pp-details', h('summary', 'Year-by-year figures'),
    h('div.table-wrap', h('table.data', { 'aria-label': 'Figures by calendar year' },
      h('thead', h('tr', cols.map(([l, c, t]) => h('th', { class: c || '', scope: 'col', title: t || null }, l)))),
      h('tbody', rows))));
}

// ------------------------------------------------------------- batting
function splitRows(rows, kind) {
  return (rows || []).map((r) => ({
    label: r.group, value: r.value, lo: r.lo, hi: r.hi, flag: r.flag,
    sub: kind === 'bat'
      ? `${fmt.n(r.balls)} balls · avg ${num(r.avg) ? r.avg.toFixed(1) : '–'} · SR ${num(r.sr) ? Math.round(r.sr) : '–'}`
      : `${fmt.n(r.balls)} balls · ${fmt.n(r.wkts)} wkts · econ ${num(r.econ) ? r.econ.toFixed(1) : '–'}`,
    note: `${r.group}: ${signed(r.value)} runs ${kind === 'bat' ? 'added' : 'saved'} per 100 balls. 95% interval ${signed(r.lo)} to ${signed(r.hi)}, from ${plural(r.balls, 'ball')}`
      + (kind === 'bat' ? `, ${plural(r.runs, 'run')}, ${plural(r.outs, 'dismissal')}.` : `, ${plural(r.runs, 'run')} conceded, ${plural(r.wkts, 'wicket')}.`),
  }));
}

function bars(rows, kind, label, emptyText) {
  if (!rows || !rows.length) return empty(emptyText);
  const opts = kind === 'bat'
    ? { unit: 'runs added per 100 balls', label }
    : { unit: 'runs saved per 100 balls', label, posLabel: 'saves runs', negLabel: 'costs runs' };
  return scroller(divergingBars(splitRows(rows, kind), opts));
}

function battingBlock(s, p) {
  const { key, sc } = s;
  const b = sc.batting, fam = sc.family;
  const ss = sc.seasons || [];
  const stats = statGrid([
    ['Balls faced', fmt.n(b.balls)], ['Runs', fmt.n(b.runs)], ['Dismissals', fmt.n(b.outs)], ['Average', fmt.avg(b.avg)],
    ['Strike rate', fmt.sr(b.sr)], ['Dot balls', pctText(b.dotPct)], ['Boundary balls', pctText(b.bdryPct)],
    ['100s / 50s', `${sum(ss, 'h100')} / ${sum(ss, 'h50')}`],
  ]);
  const vsBowling = block('Against bowling types',
    'Runs added per 100 balls against each type. Right of the line is better than an average batter facing the same bowlers.',
    bars(b.vsBowling, 'bat', `${p.name} batting against bowling types in ${sc.label}, runs added per 100 balls`,
      'Not enough balls against any one bowling type.'));
  const phase = block('By phase', 'Runs added per 100 balls in each phase of the innings.',
    bars(b.byPhase, 'bat', `${p.name} batting by phase in ${sc.label}, runs added per 100 balls`, 'No phase has enough balls.'));
  const outs = block('How they get out',
    'Dismissals per 1,000 balls faced, each against the rate for every batter in this competition. Red marks a mode at least 1.2 times the usual rate.',
    b.dismissals?.length
      ? scroller(compareDots(b.dismissals.map((d) => ({ label: d.mode, value: d.per1000, peer: d.peerPer1000, count: d.count })),
        { unit: 'per 1000 balls', label: `${p.name}: dismissals per 1000 balls by mode, against peers, in ${sc.label}` }))
      : empty('No dismissal breakdown for this competition.'));
  const plans = b.fieldPlans || {};
  const planEls = ['pace', 'spin'].filter((f) => plans[f]).map((f) => planFigure(plans[f], `Against ${f}`, fam, p, 'bat'));
  const planBlock = h('div.pp-plans',
    h('h5.pp-h5', 'Field plans'),
    h('p.tiny.muted.pp-sub', 'Where to put nine fielders when bowling at them, built from their dismissal and scoring rates against each type.'),
    planEls.length ? h('div.pp-two', planEls)
      : empty(`Not enough balls against pace or spin for a field plan; each needs ${MIN_BALLS[fam]}.`));
  const faced = block('Bowlers faced most',
    `Bowlers with at least ${MIN_MATCHUP[fam]} balls at them, most balls first. Runs added compares them with an average batter against the same bowler, pulled towards zero for small samples.`,
    matchupTable(b.bowlers, 'bat', p));
  return h('section.pp-block', { 'aria-labelledby': `pp-${key}-bat` },
    h('div.pp-block-head', h('h4.pp-h4.pp-block-title', { id: `pp-${key}-bat` }, 'Batting')),
    stats,
    h('div.pp-two', vsBowling, h('div.stack.pp-col', phase, outs)),
    planBlock, faced);
}

function planFigure(plan, title, fam, p, kind) {
  const phase = PHASES[fam]?.[plan.phase] || '';
  const handNote = kind === 'bat'
    ? (p.hand === 'left' || p.hand === 'right' ? `drawn for a ${p.hand}-hander` : 'batting hand not recorded, so drawn for a right-hander')
    : `drawn for a ${plan.hand === 'left' ? 'left' : 'right'}-hander`;
  const context = [phase, plan.balls ? plural(plan.balls, 'ball') : null, handNote].filter(Boolean).join(' · ');
  const reasons = plan.reasons?.length
    ? h('ul.pp-reasons', plan.reasons.map((r) => h('li',
      h('strong', `${SIGNALS[r.signal] || cap(r.signal)}:`),
      ` ${num(r.index) ? r.index.toFixed(2) : '–'}× the rate of peers → ${r.action}`)))
    : h('p.small.muted', 'Their rates sit close to their peers’, so this is the standard field for the phase.');
  return h('div.pp-plan',
    title ? h('h6.pp-h6', title) : null, h('p.tiny.muted', cap(context)),
    scroller(fieldPlan(plan, { label: `${title || 'Strongest field'}: field plan with ${plan.positions.map((x) => x.name).join(', ')}` }), '.pp-field'),
    reasons);
}

function matchupTable(rows, kind, p) {
  if (!rows || !rows.length) return empty(kind === 'bat' ? 'No single bowler has bowled enough balls at them.' : 'No single batter has faced enough of their balls.');
  const head = kind === 'bat'
    ? ['Bowler', 'Balls', 'Runs', 'Outs', 'Avg', 'SR', 'Runs added']
    : ['Batter', 'Balls', 'Runs', 'Wkts', 'Avg', 'Econ', 'Runs saved'];
  const name = (r) => (typeof r.id === 'string' && ID_RE.test(r.id) ? h('a', { href: `#/player/${r.id}` }, r.name || r.id) : h('span', r.name || 'Unknown'));
  return h('div.table-wrap', h('table.data.pp-matchups', { 'aria-label': kind === 'bat' ? `Bowlers who bowled most to ${p.name}` : `Batters who faced ${p.name} most` },
    h('thead', h('tr', head.map((l, i) => h('th', { class: i ? 'r' : '', scope: 'col', title: i === 6 ? 'Per 100 balls' : null }, l)))),
    h('tbody', rows.map((r) => {
      // Strike rate is recomputed from runs and balls: some exported rows carry a wrong value.
      const sr = r.balls ? (100 * r.runs) / r.balls : null;
      return h('tr',
        h('th', { scope: 'row' }, name(r)),
        h('td.r', fmt.n(r.balls)), h('td.r', fmt.n(r.runs)),
        h('td.r', fmt.n(kind === 'bat' ? r.outs : r.wkts)),
        h('td.r', fmt.avg(r.avg)),
        h('td.r', kind === 'bat' ? fmt.sr(sr) : num(r.econ) ? r.econ.toFixed(2) : '–'),
        h('td.r', h('span', { class: valueClass(r.value) }, signed(r.value))));
    }))));
}

// ------------------------------------------------------------- bowling
function bowlingBlock(s, p) {
  const { key, sc } = s;
  const b = sc.bowling, fam = sc.family;
  const stats = statGrid([
    ['Balls bowled', fmt.n(b.balls)], ['Wickets', fmt.n(b.wkts)], ['Average', fmt.avg(b.avg)],
    ['Economy', num(b.econ) ? b.econ.toFixed(2) : '–'], ['Balls per wicket', fmt.sr(b.sr)],
    ['Dot balls', pctText(b.dotPct)], ['Boundary balls', pctText(b.bdryPct)],
  ]);
  const types = h('div.pp-chart',
    h('h5.pp-h5', 'Against batter types'),
    h('p.tiny.muted.pp-sub', 'Runs saved per 100 balls. Right of the line means fewer runs than an average bowler conceded to the same batters.'),
    h('h6.pp-h6', 'By batting hand'),
    bars(b.vsHand, 'bowl', `${p.name} bowling by batting hand in ${sc.label}, runs saved per 100 balls`, 'Batting hand is not recorded for enough of the batters they bowled to.'),
    h('h6.pp-h6', 'By batting position'),
    bars(b.vsPosition, 'bowl', `${p.name} bowling by batting position in ${sc.label}, runs saved per 100 balls`, 'No batting position has enough balls.'),
    h('h6.pp-h6', 'By batter tempo'),
    h('p.tiny.faint.pp-sub', 'Batters split into thirds by their own strike rate in this competition.'),
    bars(b.vsTempo, 'bowl', `${p.name} bowling to anchors, balanced batters and aggressors in ${sc.label}, runs saved per 100 balls`, 'Not enough balls to split by batter tempo.'));
  const phase = block('By phase', 'Runs saved per 100 balls in each phase of the innings.',
    bars(b.byPhase, 'bowl', `${p.name} bowling by phase in ${sc.label}, runs saved per 100 balls`, 'No phase has enough balls.'));
  const peers = p.bowl?.family ? `other ${p.bowl.family} bowlers` : 'other bowlers';
  const wkts = block('How they take wickets',
    `Share of their wickets by mode, against the share for ${peers} in this competition.`,
    b.wickets?.length && b.wkts
      ? scroller(compareDots(b.wickets.map((w) => ({ label: w.mode, value: w.share, peer: w.peerShare, count: w.count })),
        { unit: '% of wickets', highIsBad: false, label: `${p.name}: share of wickets by mode against peers in ${sc.label}` }))
      : empty('No wickets to break down here.'));
  const field = b.fieldPlan
    ? h('div.pp-chart', h('h5.pp-h5', 'Strongest field'),
      h('p.tiny.muted.pp-sub', 'The field their own wicket and scoring rates point to, against a typical batter.'),
      planFigure(b.fieldPlan, '', fam, p, 'bowl'))
    : block('Strongest field', null, empty('Pace or spin is not known for this bowler, so there is no peer group to build a field from.'));
  const facedBy = block('Batters faced most',
    `Batters who faced at least ${MIN_MATCHUP[fam]} of their balls, most balls first. Runs saved compares them with an average bowler against the same batter, pulled towards zero for small samples.`,
    matchupTable(b.batters, 'bowl', p));
  return h('section.pp-block', { 'aria-labelledby': `pp-${key}-bowl` },
    h('div.pp-block-head', h('h4.pp-h4.pp-block-title', { id: `pp-${key}-bowl` }, 'Bowling')),
    stats,
    h('div.pp-two', types, h('div.stack.pp-col', phase, wkts)),
    h('div.pp-two', field, facedBy));
}

// ----------------------------------------------------------- read me
function howToRead(s, group) {
  const { sc } = s;
  const fam = sc.family;
  const first = group?.adjusted === false
    ? 'Values are runs per 100 balls against the average across these matches. There are too few matches here to adjust for opposition, so treat them as rough.'
    : `Values are runs per 100 balls, adjusted for opposition: the player against an average ${sc.tier === 'national' ? 'Full-Member ' : ''}player facing the same opponents in the same phase, era and conditions. For bowling, positive means runs saved.`;
  const items = [
    first,
    'Each bar is the estimate, pulled towards zero when balls are few. The shaded whisker behind it is the 95% interval of the raw rate.',
    `A split is flagged as a strength or weakness only when it differs from the player’s own overall level by more than 1.96 standard errors and rests on at least ${MIN_BALLS[fam]} balls. With several splits on the page, about 1 in 20 flags can be chance.`,
    'Every split counts every ball faced or bowled, not just dismissals. That avoids reading a weakness off the few balls that happened to get the player out.',
    'Field positions follow convention because the source records no shot or catch locations. The number of catchers, ring fielders and boundary riders comes from the measured rates.',
  ];
  return h('aside.panel.pp-howto', { 'aria-labelledby': `pp-${s.key}-howto` },
    h('h4.pp-h4', { id: `pp-${s.key}-howto` }, 'How to read this'),
    h('ul', items.map((t) => h('li', t))));
}

// ------------------------------------------------------------ captaincy
function captaincyCard(p) {
  const rows = (p.captaincy || []).slice().sort((a, b) =>
    (a.level === b.level ? 0 : a.level === 'international' ? -1 : 1) || (Number(a.first_year) || 0) - (Number(b.first_year) || 0));
  if (!rows.length) {
    return card('captaincy', 'Captaincy', {},
      empty('Not listed as captain on the Wikipedia captaincy lists this site reads. Those lists cover national sides and the main franchise leagues.'));
  }
  const n = (v) => (v === '' || v == null ? null : Number(v));
  const table = h('table.data.pp-captaincy', { 'aria-label': 'Record as captain' },
    h('thead', h('tr',
      h('th', { scope: 'col' }, 'Team'), h('th', { scope: 'col' }, 'Format'), h('th', { scope: 'col' }, 'Span'),
      h('th.r', { scope: 'col', title: 'Played' }, 'P'), h('th.r', { scope: 'col', title: 'Won' }, 'W'), h('th.r', { scope: 'col', title: 'Lost' }, 'L'),
      h('th.r', { scope: 'col', title: 'Drawn / tied / no result' }, 'D / T / NR'), h('th.r', { scope: 'col' }, 'Win %'),
      h('th', { scope: 'col' }, h('span.sr-only', 'Results')))),
    h('tbody', rows.map((r) => {
      const span = r.ongoing === '1' ? `${r.first_year || '?'}–present` : years(r.first_year || null, r.last_year || r.first_year || null) || '–';
      const src = r.source_page
        ? h('a', { href: `https://en.wikipedia.org/w/index.php?title=${encodeURIComponent(r.source_page.replace(/ /g, '_'))}${r.revid ? `&oldid=${encodeURIComponent(r.revid)}` : ''}`, rel: 'noopener', title: r.source_page }, 'source')
        : null;
      const where = r.level === 'franchise' ? r.competition || 'Franchise' : 'International';
      return h('tr',
        h('th', { scope: 'row' }, h('div', r.country_or_team || '–'),
          h('div.tiny.faint', where, src ? ' · ' : '', src),
          r.page_total === 'mismatch' ? h('div.tiny.pp-warn', `Totals differ on the source page${r.page_total_detail ? `: ${r.page_total_detail}` : ''}`) : null),
        h('td', r.format || '–'), h('td', span),
        h('td.r', dash(r.played)), h('td.r', dash(r.won)), h('td.r', dash(r.lost)),
        h('td.r', `${dash(r.drawn)} / ${dash(r.tied)} / ${dash(r.no_result)}`),
        h('td.r', r.win_pct === '' || r.win_pct == null ? '–' : `${r.win_pct}%`),
        h('td.pp-bar-cell', resultBar({ won: n(r.won) || 0, lost: n(r.lost) || 0, drawn: n(r.drawn) || 0, tied: n(r.tied) || 0, no_result: n(r.no_result) || 0 })));
    })));
  return card('captaincy', 'Captaincy', {
    sub: 'Results as captain, from Wikipedia’s lists of national and franchise captains. A dash means the list has no such column for that format.',
    action: h('a.btn.sm', { href: `#/captains?ids=${encodeURIComponent(p.id)}` }, 'Compare captains'),
  }, h('div.table-wrap', table));
}

// --------------------------------------------------------------- squads
function squadsCard(p) {
  const rows = (p.squads || []).slice().sort((a, b) => (a.level === b.level ? 0 : a.level === 'international' ? -1 : 1));
  if (!rows.length) {
    return card('squads', 'Current squads', {},
      empty('Not named in any current squad on the Wikipedia squad pages this site reads.'));
  }
  const list = (v) => String(v || '').split(';').map((x) => x.trim()).filter(Boolean);
  const table = h('table.data.pp-squads', { 'aria-label': 'Current squads' },
    h('thead', h('tr', ['Team', 'Competition', 'Formats', 'Central contract', 'Leadership', 'Listed as', 'As of']
      .map((l) => h('th', { scope: 'col' }, l)))),
    h('tbody', rows.map((r) => {
      const capt = list(r.captain_formats), vice = list(r.vice_captain_formats);
      return h('tr',
        h('th', { scope: 'row' }, r.team || '–'),
        h('td', r.level === 'international' ? 'International' : r.competition || '–'),
        h('td', list(r.forms).join(', ') || '–'),
        h('td', r.contracted === '1' ? 'Yes' : r.contracted === '0' ? 'No' : '–'),
        h('td', capt.length || vice.length
          ? h('span.pp-lead', capt.length ? h('span.badge.c', `Captain: ${capt.join(', ')}`) : null,
            vice.length ? h('span.badge', `Vice-captain: ${vice.join(', ')}`) : null)
          : '–'),
        h('td', r.role_group ? cap(r.role_group) : '–'),
        h('td.pp-nowrap', r.page_timestamp ? day(r.page_timestamp) : '–'));
    })));
  return card('squads', 'Current squads', {
    sub: 'Squads as listed on Wikipedia when each page was last read. A dash means the page does not say.',
  }, h('div.table-wrap', table));
}
