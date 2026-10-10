// Shell: hash router, theme, navigation, data-as-of badge.
import { h, clear } from './ui/dom.js';
import { icon } from './ui/icons.js';
import { loadTeamIndex } from './ui/teams.js';
import * as data from './data.js';
import { SECTION_LABEL, sectionOf, rememberHref, rememberTitle, forget, restoreHref, visit, neighbours,
  saveScroll, savedScroll, onMemory } from './memory.js';

const routes = {
  select: () => import('./views/select.js'),
  players: () => import('./views/players.js'),
  player: () => import('./views/player.js'),
  captains: () => import('./views/captains.js'),
  versus: () => import('./views/versus.js'),
  method: () => import('./views/method.js'),
  credits: () => import('./views/credits.js'),
};
const DEFAULT_HREF = { select: '#/', players: '#/players', captains: '#/captains', versus: '#/versus' };

/** Parse "#/player/abc?x=1" -> {name: 'player', arg: 'abc', query: URLSearchParams} */
export function parseHash(hash = location.hash) {
  const raw = hash.replace(/^#\/?/, '');
  const [path, qs = ''] = raw.split('?');
  const [name = '', arg = ''] = path.split('/');
  const route = name === '' ? 'select' : name;
  return { name: routes[route] ? route : 'notfound', arg: decodeURIComponent(arg), query: new URLSearchParams(qs) };
}

let lastHash = location.hash;

/** True while `route` (a view's own route) is the page on screen. */
export function isLive(route) {
  const cur = parseHash();
  return cur.name === route.name && cur.arg === route.arg;
}

/**
 * Replace the query part of the current route without a navigation. A view
 * passes its own route, so a write that lands after the user has moved on is
 * dropped instead of rewriting another page's address.
 */
export function setQuery(params, owner) {
  if (owner && !isLive(owner)) return false;
  const { name, arg } = parseHash();
  const base = name === 'select' ? '#/' : `#/${name}${arg ? '/' + encodeURIComponent(arg) : ''}`;
  const qs = new URLSearchParams(params).toString();
  history.replaceState(null, '', qs ? `${base}?${qs}` : base);
  lastHash = location.hash;
  rememberHref(name, location.hash);
}

/** Links to the two pages used most recently, pointing the way they sit in the menu. */
function waybar(section) {
  const links = neighbours(section);
  if (!links.length) return null;
  const link = (n) => h(`a.waylink.${n.dir}`, { href: n.href },
    n.dir === 'left' ? icon('arrow', { size: 16, cls: 'flip' }) : null,
    h('span.waylink-page', SECTION_LABEL[n.section]),
    n.title ? h('span.waylink-title', n.title) : null,
    n.dir === 'right' ? icon('arrow', { size: 16 }) : null);
  return h('nav.waybar', { 'aria-label': 'Return to a page you were using' },
    h('div.waybar-side', links.filter((n) => n.dir === 'left').map(link)),
    h('div.waybar-side.right', links.filter((n) => n.dir === 'right').map(link)));
}

/** Return to a saved position once the page is tall enough; any user scroll wins. */
function restoreScroll(y, token) {
  if (!y) { window.scrollTo(0, 0); return; }
  const deadline = performance.now() + 3000;
  let cancelled = false;
  const cancel = () => { cancelled = true; };
  for (const ev of ['wheel', 'touchstart', 'keydown', 'mousedown']) window.addEventListener(ev, cancel, { once: true, passive: true });
  const attempt = () => {
    if (cancelled || token !== renderToken) return;
    const max = document.documentElement.scrollHeight - window.innerHeight;
    window.scrollTo(0, Math.min(y, Math.max(0, max)));
    if (max < y && performance.now() < deadline) requestAnimationFrame(attempt);
  };
  attempt();
}

let current = null;
let renderToken = 0;

async function render() {
  if (current && lastHash && lastHash !== location.hash) saveScroll(lastHash, window.scrollY);
  let route = parseHash();
  // A bare menu link (no query, no player) reopens the page as it was left.
  if (!route.query.toString() && !route.arg) {
    const href = restoreHref(route.name);
    if (href && href !== location.hash) { history.replaceState(null, '', href); route = parseHash(); }
  }
  lastHash = location.hash;
  const section = sectionOf(route.name);
  rememberHref(route.name, location.hash);
  visit(route.name);
  const main = document.getElementById('main');
  for (const a of document.querySelectorAll('.nav a')) {
    const active = a.dataset.route === route.name || (route.name === 'player' && a.dataset.route === 'players');
    if (active) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  }
  document.getElementById('nav').classList.remove('open');
  document.getElementById('menu-toggle').setAttribute('aria-expanded', 'false');
  if (current && current.name === route.name && current.arg === route.arg && current.view?.update) {
    current.view.update(route);   // same page, new query: let the view update in place
    return;
  }
  const token = ++renderToken;
  current?.view?.destroy?.();
  current = null;   // nothing half-built may take the in-place update path later
  clear(main);
  if (route.name === 'notfound') {
    main.append(h('div.page', h('h1.display', 'Not found'), h('p', h('a', { href: '#/' }, 'Back to the Best XI'))));
    current = null;
    return;
  }
  main.append(h('div.page', h('div.row', h('div.spinner'), h('span.muted', 'Loading…'))));
  try {
    const mod = await routes[route.name]();
    if (token !== renderToken) return;
    clear(main);
    const bar = section ? waybar(section) : null;
    if (bar) main.append(bar);
    const view = await mod.mount(main, route);
    if (token !== renderToken) return;
    current = { name: route.name, arg: route.arg, view };
    restoreScroll(savedScroll(location.hash), token);
  } catch (err) {
    if (token !== renderToken) return;
    console.error(err);
    clear(main);
    // A remembered state that no longer loads must not come back on every visit;
    // a dropped connection is no reason to forget it.
    const transient = err instanceof TypeError || /HTTP (5\d\d|0)/.test(String(err.message));
    const restored = section && !route.arg && route.query.toString() && !transient;
    if (restored) forget(section);
    else if (section) rememberTitle(section, undefined);
    main.append(h('div.page', h('div.notice.error', h('div',
      h('strong', 'This page could not load. '), String(err.message || err),
      restored ? [' ', h('a', { href: DEFAULT_HREF[section] }, 'Start afresh')] : null))));
  }
}

function initTheme() {
  const btn = document.getElementById('theme-toggle');
  const dark = () => document.documentElement.dataset.theme === 'dark' ||
    (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
  const label = () => {
    btn.setAttribute('aria-label', dark() ? 'Switch to light theme' : 'Switch to dark theme');
    btn.replaceChildren(icon(dark() ? 'sun' : 'moon', { size: 18 }));
  };
  label();
  const apply = () => {
    const next = dark() ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('be-theme', next); } catch (e) { /* storage unavailable */ }
    label();
    window.dispatchEvent(new Event('themechange'));
  };
  btn.addEventListener('click', async () => {
    // Where supported, the new theme spreads in a circle from the button.
    const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!document.startViewTransition || still) { apply(); return; }
    // Ground images for the coming theme should be ready before the sweep (at most a short wait).
    const coming = [...document.querySelectorAll(dark() ? 'img.fp-day' : 'img.fp-night')];
    for (const img of coming) img.loading = 'eager';
    await Promise.race([Promise.all(coming.map((img) => img.decode().catch(() => {}))),
      new Promise((r) => setTimeout(r, 800))]);
    const r = btn.getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    const reach = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    const t = document.startViewTransition(apply);
    t.ready.then(() => document.documentElement.animate(
      { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${reach}px at ${x}px ${y}px)`] },
      { duration: 700, easing: 'cubic-bezier(.45, 0, .2, 1)', pseudoElement: '::view-transition-new(root)' },
    )).catch(() => {});
  });
}

const NAV_ICONS = { select: 'room', players: 'profile', captains: 'captain', versus: 'compare', method: 'database', credits: 'info' };
function initNavIcons() {
  for (const a of document.querySelectorAll('.nav a')) {
    const name = NAV_ICONS[a.dataset.route];
    if (name && !a.querySelector('.icon')) a.prepend(icon(name, { size: 17 }));
  }
}

/** Menu tabs open each page as it was last left. */
function initNavLinks() {
  const sync = () => {
    for (const [name, href] of Object.entries(DEFAULT_HREF)) {
      const a = document.querySelector(`.nav a[data-route="${name}"]`);
      if (a) a.href = restoreHref(name) || href;
    }
  };
  sync();
  onMemory(sync);
}

function initMenu() {
  const btn = document.getElementById('menu-toggle');
  const nav = document.getElementById('nav');
  btn.addEventListener('click', () => {
    const open = nav.classList.toggle('open');
    btn.setAttribute('aria-expanded', String(open));
  });
}

async function initAsOf() {
  try {
    const m = await data.meta();
    const d = new Date(m.dataEnd);
    document.getElementById('asof').textContent =
      `Data to ${d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}`;
  } catch (e) { /* badge is optional */ }
}

initTheme();
initNavIcons();
initNavLinks();
initMenu();
initAsOf();
if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
// A reload returns to where the page was, not to an older visit's position.
window.addEventListener('pagehide', () => saveScroll(location.hash, window.scrollY));
window.addEventListener('hashchange', render);
loadTeamIndex().finally(render);
